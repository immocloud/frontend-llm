# api/auth.py - Keycloak JWT Authentication
# Validates JWT tokens and extracts user information for DLS

import httpx
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, ExpiredSignatureError
from pydantic import BaseModel

from .config import settings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("keycloak-auth")

# =============================================================================
# MODELS
# =============================================================================

class TokenUser(BaseModel):
    """User information extracted from JWT token"""
    user_id: str  # sub claim
    username: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    roles: List[str] = []
    groups: List[str] = []
    raw_token: Optional[str] = None


class AnonymousUser(TokenUser):
    """Anonymous user when auth is disabled"""
    user_id: str = "anonymous"
    username: str = "anonymous"


# =============================================================================
# JWKS CACHE
# =============================================================================

_jwks_cache: Dict[str, Any] = {}
_jwks_cache_time: Optional[datetime] = None
JWKS_CACHE_TTL = 3600  # 1 hour


async def get_jwks() -> Dict[str, Any]:
    """Fetch JWKS from Keycloak with caching"""
    global _jwks_cache, _jwks_cache_time
    
    now = datetime.utcnow()
    
    if _jwks_cache and _jwks_cache_time:
        if (now - _jwks_cache_time).total_seconds() < JWKS_CACHE_TTL:
            return _jwks_cache
    
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(settings.keycloak_jwks_url, timeout=10.0)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_cache_time = now
            return _jwks_cache
    except Exception as e:
        if _jwks_cache:
            return _jwks_cache
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot fetch JWKS from Keycloak: {e}"
        )


def get_signing_key(jwks: Dict[str, Any], token: str) -> Optional[Dict]:
    """Get the signing key that matches the token's kid"""
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None
    except JWTError:
        return None


# =============================================================================
# TOKEN VALIDATION
# =============================================================================

async def decode_and_validate_token(token: str) -> TokenUser:
    """Decode and validate a Keycloak JWT token"""
    
    logger.info(f"Validating token: {token[:10]}...{token[-10:]}")
    
    jwks = await get_jwks()
    signing_key = get_signing_key(jwks, token)
    
    if not signing_key:
        logger.error("No matching signing key found in JWKS")
        logger.error(f"Available token KIDs: {[k.get('kid') for k in jwks.get('keys', [])]}")
        try:
            unverified_header = jwt.get_unverified_header(token)
            logger.error(f"Token header: {unverified_header}")
        except JWTError as e:
            logger.error(f"Invalid token format: {e}")
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: signing key not found or malformed token"
        )
    
    try:
        # Note: verify_aud is disabled because tokens may be issued for different clients
        # OpenSearch also has verify_audience: false in its config
        logger.info(f"Decoding with issuer: {settings.keycloak_issuer}")
        
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=settings.keycloak_issuer,
            options={"verify_aud": False, "verify_iss": True, "verify_exp": True}
        )
        
        user_id = payload.get("sub")
        if not user_id:
            logger.error("Token missing 'sub' claim")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject"
            )
        
        logger.info(f"Token valid for user: {payload.get('preferred_username')} ({user_id})")
        
        # Extract roles
        roles = []
        if "realm_access" in payload:
            roles.extend(payload["realm_access"].get("roles", []))
        if "resource_access" in payload:
            client_access = payload["resource_access"].get(settings.keycloak_client_id, {})
            roles.extend(client_access.get("roles", []))
        
        return TokenUser(
            user_id=user_id,
            username=payload.get("preferred_username"),
            email=payload.get("email"),
            name=payload.get("name"),
            roles=roles,
            groups=payload.get("groups", []),
            raw_token=token
        )
        
    except ExpiredSignatureError:
        logger.warning(f"Token expired. Token: {token[:20]}...{token[-20:]}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except JWTError as e:
        logger.error(f"JWT Validation Error: {e}")
        try:
             # Try to decode without verification to see what's wrong (debug only)
            unverified = jwt.get_unverified_claims(token)
            logger.error(f"Unverified claims: {unverified}")
            logger.error(f"Expected issuer: {settings.keycloak_issuer}")
        except Exception as ex:
            logger.error(f"Failed to decode unverified claims: {ex}")
            pass
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")


# =============================================================================
# FASTAPI DEPENDENCIES
# =============================================================================

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> TokenUser:
    """Get current authenticated user from JWT"""
    
    if not settings.auth_enabled:
        logger.debug("Auth disabled, returning anonymous user")
        return AnonymousUser()
    
    if not credentials:
        if settings.allow_anonymous:
            logger.debug("No credentials, but anonymous allowed")
            return AnonymousUser()
        logger.warning("No credentials provided and anonymous access disabled")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return await decode_and_validate_token(credentials.credentials)


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> Optional[TokenUser]:
    """Optional auth - returns None if no valid token"""
    if not credentials:
        return None
    try:
        return await decode_and_validate_token(credentials.credentials)
    except HTTPException:
        return None


def require_role(required_role: str):
    """Dependency factory to require a specific role"""
    async def role_checker(user: TokenUser = Depends(get_current_user)) -> TokenUser:
        if required_role not in user.roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Role '{required_role}' required")
        return user
    return role_checker


def get_user_id_for_dls(user: TokenUser) -> str:
    """
    Get user ID for Document Level Security.
    Uses preferred_username to match OpenSearch's subject_key configuration.
    """
    # OpenSearch is configured with subject_key: "preferred_username"
    # So we use username for DLS consistency
    return user.username or user.user_id
