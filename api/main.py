# api/main.py - FastAPI application
# Smart Real Estate Search API with Keycloak auth and DLS

import uuid
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import requests

from .config import settings
from .auth import (
    get_current_user, get_current_user_optional, require_role,
    TokenUser, AnonymousUser, get_user_id_for_dls
)
from .models import (
    SearchRequest, SearchResponse, SearchFilters, SearchFeatures,
    SearchResult, SessionInfo, HistoryItem, UserInfo, AddAgentRequest
)
from .search import (
    search, create_empty_memory, load_memory, save_memory,
    delete_memory, ensure_memory_index
)
from .normalize_data import normalize_phone
from datetime import datetime
import json
import logging

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smart-search-api")


# =============================================================================
# LIFESPAN
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events"""
    # Startup
    ensure_memory_index()
    yield
    # Shutdown (nothing needed)


# =============================================================================
# APP
# =============================================================================

app = FastAPI(
    title="Smart Real Estate Search API for immocloud.ro",
    description="""
Natural language search for Romanian real estate with conversation memory.

## Features
- 🔍 Natural language queries in Romanian or English
- 💬 Conversation memory - follow-up queries refine search
- 🔐 Keycloak JWT authentication
- 🛡️ Document Level Security - users only see their own sessions
- 🏷️ Rich result data for UI cards (images, attributes, etc.)

## Authentication
Pass your Keycloak JWT via `Authorization: Bearer <token>` header.
Set `AUTH_ENABLED=true` to require authentication.

## Examples
- "Caut apartament de inchiriat in Pallady cu 2 camere"
- "sa fie pet friendly" (follow-up)
- "pret maxim 600 euro" (follow-up)
    """,
    version="1.0.0",
    lifespan=lifespan
)

# CORS
origins = settings.cors_origins.split(",") if settings.cors_origins != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# HEALTH
# =============================================================================

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "smart-search",
        "auth_enabled": settings.auth_enabled
    }


# =============================================================================
# SEARCH
# =============================================================================

@app.post("/search", response_model=SearchResponse)
async def search_listings(
    request: SearchRequest,
    session_id: Optional[str] = Query(None, description="Session ID for conversation continuity"),
    user: TokenUser = Depends(get_current_user)
):
    """
    Search real estate listings using natural language.
    
    The query is parsed by an LLM to extract structured filters.
    Conversation context is maintained per session for follow-up queries.
    """
    if not session_id:
        session_id = str(uuid.uuid4())[:8]
    
    user_id = get_user_id_for_dls(user)
    
    # DEBUG LOGGING
    logger.info(f"--- SEARCH START ---")
    logger.info(f"User: {user_id} ({user.username})")
    logger.info(f"Query: {request.query}")
    logger.info(f"Config: OS={settings.opensearch_url} | LLM={settings.ollama_url}")
    if user.raw_token:
        logger.info(f"JWT: {user.raw_token[:15]}...{user.raw_token[-10:]}")
    else:
        logger.debug("No JWT token present")

    try:
        result = search(
            user_query=request.query,
            user_id=user_id,
            session_id=session_id,
            size=request.size,
            offset=request.offset,
            exclude_agencies_override=request.exclude_agencies  # UI toggle takes precedence
        )
        
        # Convert parsed to model
        parsed = result.get("parsed", {})
        features = parsed.get("features", {})
        filters = SearchFilters(
            location=parsed.get("location"),
            city=parsed.get("city"),
            transaction=parsed.get("transaction"),
            property_type=parsed.get("property_type"),
            rooms=parsed.get("rooms"),
            price_min=parsed.get("price_min"),
            price_max=parsed.get("price_max"),
            keywords=parsed.get("keywords", []),
            features=SearchFeatures(**features) if features else SearchFeatures(),
            exclude_agencies=parsed.get("exclude_agencies", False)
        )
        
        # Results are already SearchResult objects from api/search.py
        return SearchResponse(
            query=request.query,
            parsed_filters=filters,
            total=result.get("total", 0),
            results=result.get("results", []),
            session_id=session_id,
            user_id=user_id,
            message=result.get("message", ""),
            message_type=result.get("message_type", "results"),
            opensearch_query=result.get("opensearch_query")  # For frontend caching (fast pagination)
        )
        
    except Exception as e:
        logger.error(f"!! SEARCH EXCEPTION !!: {str(e)}", exc_info=True)
        # Import traceback only if needed
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SESSION MANAGEMENT
# =============================================================================

@app.get("/session/{session_id}", response_model=SessionInfo)
async def get_session(
    session_id: str,
    user: TokenUser = Depends(get_current_user)
):
    """Get current session state (DLS: own sessions only)"""
    user_id = get_user_id_for_dls(user)
    doc_id = f"{user_id}_{session_id}"
    
    response = requests.get(
        f"{settings.opensearch_url}/{settings.memory_index}/_doc/{doc_id}",
        auth=settings.opensearch_auth,
        verify=settings.opensearch_verify_ssl
    )
    
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Session not found")
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to fetch session")
    
    src = response.json().get("_source", {})
    filters_data = src.get("filters", create_empty_memory())
    features = filters_data.get("features", {})
    
    return SessionInfo(
        user_id=user_id,
        session_id=session_id,
        filters=SearchFilters(
            location=filters_data.get("location"),
            city=filters_data.get("city"),
            transaction=filters_data.get("transaction"),
            property_type=filters_data.get("property_type"),
            rooms=filters_data.get("rooms"),
            price_min=filters_data.get("price_min"),
            price_max=filters_data.get("price_max"),
            keywords=filters_data.get("keywords", []),
            features=SearchFeatures(**features) if features else SearchFeatures()
        ),
        query_count=len(src.get("query_history", [])),
        created_at=src.get("created_at"),
        updated_at=src.get("updated_at")
    )


@app.get("/session/{session_id}/history", response_model=List[HistoryItem])
async def get_session_history(
    session_id: str,
    limit: int = Query(20, ge=1, le=100),
    user: TokenUser = Depends(get_current_user)
):
    """Get query history for a session (DLS: own sessions only)"""
    user_id = get_user_id_for_dls(user)
    doc_id = f"{user_id}_{session_id}"
    
    response = requests.get(
        f"{settings.opensearch_url}/{settings.memory_index}/_doc/{doc_id}",
        auth=settings.opensearch_auth,
        verify=settings.opensearch_verify_ssl
    )
    
    if response.status_code == 404:
        return []
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to fetch history")
    
    history = response.json().get("_source", {}).get("query_history", [])
    return [HistoryItem(query=h["q"], timestamp=h["ts"]) for h in history[-limit:]]


@app.delete("/session/{session_id}")
async def delete_session_endpoint(
    session_id: str,
    user: TokenUser = Depends(get_current_user)
):
    """Delete a session (DLS: own sessions only)"""
    user_id = get_user_id_for_dls(user)
    success = delete_memory(user_id, session_id)
    
    if success:
        return {"message": "Session deleted", "session_id": session_id}
    raise HTTPException(status_code=500, detail="Failed to delete session")


@app.post("/session/{session_id}/reset")
async def reset_session(
    session_id: str,
    user: TokenUser = Depends(get_current_user)
):
    """Reset session filters but keep session ID"""
    user_id = get_user_id_for_dls(user)
    empty = create_empty_memory()
    save_memory(user_id, session_id, empty)
    
    return {"message": "Session reset", "session_id": session_id, "filters": empty}


# =============================================================================
# USER SESSIONS
# =============================================================================

@app.get("/sessions")
async def list_user_sessions(
    limit: int = Query(10, ge=1, le=50),
    user: TokenUser = Depends(get_current_user)
):
    """List all sessions for current user (DLS enforced)"""
    user_id = get_user_id_for_dls(user)
    
    query = {
        "size": limit,
        "query": {"term": {"user_id": user_id}},
        "sort": [{"updated_at": "desc"}],
        "_source": ["session_id", "query_history", "created_at", "updated_at"]
    }
    
    response = requests.post(
        f"{settings.opensearch_url}/{settings.memory_index}/_search",
        json=query,
        auth=settings.opensearch_auth,
        verify=settings.opensearch_verify_ssl
    )
    
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to fetch sessions")
    
    hits = response.json().get("hits", {}).get("hits", [])
    sessions = []
    for hit in hits:
        src = hit["_source"]
        history = src.get("query_history", [])
        sessions.append({
            "session_id": src.get("session_id"),
            "query_count": len(history),
            "last_query": history[-1]["q"] if history else None,
            "created_at": src.get("created_at"),
            "updated_at": src.get("updated_at")
        })
    
    return {"user_id": user_id, "sessions": sessions}


# =============================================================================
# USER INFO
# =============================================================================

@app.get("/me", response_model=UserInfo)
async def get_current_user_info(user: TokenUser = Depends(get_current_user)):
    """Get information about current authenticated user"""
    return UserInfo(
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        name=user.name,
        roles=user.roles,
        groups=user.groups,
        is_anonymous=isinstance(user, AnonymousUser)
    )


# =============================================================================
# ADMIN
# =============================================================================

@app.post("/admin/normalize-phones")
async def trigger_normalization(
    background_tasks: BackgroundTasks, 
    key: str = Query(..., description="Admin API Key")
):
    """Async trigger for phone normalization"""
    # Simple auth check (could be improved)
    if key != settings.admin_api_key: # Assuming this exists or we use a hardcoded one for now
         raise HTTPException(status_code=403, detail="Invalid admin key")

    from .normalize_data import normalize_phones_task
    background_tasks.add_task(normalize_phones_task)
    return {"message": "Normalization job started in background"}

@app.post("/admin/populate-agents")
async def trigger_populate_agents(
    background_tasks: BackgroundTasks, 
    key: str = Query(..., description="Admin API Key")
):
    """Async trigger for rebuilding agents index"""
    if key != settings.admin_api_key:
         raise HTTPException(status_code=403, detail="Invalid admin key")

    from .populate_agents import populate_agents_task
    background_tasks.add_task(populate_agents_task)
    return {"message": "Agent population job started in background"}


@app.post("/admin/add-agent")
async def add_agent_manual(
    request: AddAgentRequest,
    user: TokenUser = Depends(get_current_user)
):
    """
    Manually add a phone number to the agents index and update existing listings.
    Restricted to specific user.
    """
    ALLOWED_USER = "vladxpetrescu@gmail.com"
    
    # 1. Auth Check - strict check on email
    if not user.email or user.email.lower() != ALLOWED_USER.lower():
        raise HTTPException(status_code=403, detail="You are not authorized to perform this action.")
    
    # 2. Validation
    clean_phone = normalize_phone(request.phone)
    if not clean_phone:
        raise HTTPException(status_code=400, detail="Invalid phone number format")
        
    # 3. Index into 'agents'
    try:
        doc = {
            "phone": clean_phone,
            "agency_name": request.agency_name,
            "type": "agency",
            "reported_by": user.email,
            "reported_at": datetime.utcnow().isoformat()
        }
        
        # Use phone as ID to enforce uniqueness
        requests.put(
            f"{settings.opensearch_url}/agents/_doc/{clean_phone}",
            json=doc,
            auth=settings.opensearch_auth,
            verify=settings.opensearch_verify_ssl,
            timeout=5
        )
        
        # 4. Trigger update on existing listings
        # Use update_by_query to find all docs with this phone and set is_agency=true
        update_query = {
            "query": {
                "term": {
                    "decrypted_phone.keyword": clean_phone
                }
            },
            "script": {
                "source": "ctx._source.is_agency = true",
                "lang": "painless"
            }
        }
        
        # Check if we need keyword or text field. In 'real-estate-*', decrypted_phone is usually text+keyword.
        # Check mapping or just try 'decrypted_phone' if keyword is not set.
        # But 'term' query works best on 'keyword'.
        # Let's try matching both to be safe or just use matching query.
        
        # Better query:
        update_body = {
            "query": {
                "match": {"decrypted_phone": clean_phone}
            },
            "script": {
                "source": "ctx._source.is_agency = true",
                "lang": "painless"
            }
        }
        
        resp = requests.post(
            f"{settings.opensearch_url}/real-estate-*/_update_by_query?conflicts=proceed",
            json=update_body,
            auth=settings.opensearch_auth,
            verify=settings.opensearch_verify_ssl,
            timeout=30 # longer timeout for bulk update
        )
        
        updated_count = 0
        if resp.status_code == 200:
            updated_count = resp.json().get("updated", 0)
        
        return {
            "message": f"Agent added successfully. Phone: {clean_phone}",
            "updated_listings": updated_count,
            "doc": doc
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# RUN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
