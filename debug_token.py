import asyncio
import jwt
from jwt import PyJWKClient
import sys

# The token user provided
TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJ4bkVGLXRjQy1hOUZ4MEVheDVCV09KSVF6eDN2TkVteERmNGkybG52cEJnIn0.eyJleHAiOjE3Njc3MDQxODYsImlhdCI6MTc2NzcwMzI4NiwiYXV0aF90aW1lIjoxNzY3NjkyMDcwLCJqdGkiOiJvbnJ0YWM6NzYwZGQ2YmYtYjE1OS01NmFhLTgzYjMtOTgxNTQ4NjEzOGZjIiwiaXNzIjoiaHR0cHM6Ly9hdXRoLmltbW9jbG91ZC5yby9yZWFsbXMvaW1tb2Nsb3VkIiwiYXVkIjoiYWNjb3VudCIsInN1YiI6Ijk5ZDdhOWVjLWEzYTYtNDUxZC05YzE5LTU1YjBlN2U3ZjMwOCIsInR5cCI6IkJlYXJlciIsImF6cCI6ImZlY2xpZW50Iiwic2lkIjoiMmU1YjVkOWYtZDAzMC0yYmFmLWQ5OWQtYjA5NjM3NzliNDhkIiwiYWNyIjoiMCIsImFsbG93ZWQtb3JpZ2lucyI6WyJodHRwOi8vbG9jYWxob3N0OioiLCJodHRwczovL2Rldi5pbW1vY2xvdWQucm8iLCJodHRwczovL2RlbW8uaW1tb2Nsb3VkLnJvIl0sInJlYWxtX2FjY2VzcyI6eyJyb2xlcyI6WyJkZWZhdWx0LXJvbGVzLWltbW9jbG91ZCIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJhY2NvdW50Ijp7InJvbGVzIjpbIm1hbmFnZS1hY2NvdW50IiwibWFuYWdlLWFjY291bnQtbGlua3MiLCJ2aWV3LXByb2ZpbGUiXX19LCJzY29wZSI6Im9wZW5pZCBwcm9maWxlIGVtYWlsIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsIm5hbWUiOiJWbGFkIFBldHJlc2N1IiwicHJlZmVycmVkX3VzZXJuYW1lIjoidmxhZHhwZXRyZXNjdUBnbWFpbC5jb20iLCJnaXZlbl9uYW1lIjoiVmxhZCIsImZhbWlseV9uYW1lIjoiUGV0cmVzY3UiLCJlbWFpbCI6InZsYWR4cGV0cmVzY3VAZ21haWwuY29tIn0.nbX-1463ugghh0tRjKBMztXj23DyGhUGGyNsgbkXXjf_s_ztTvKXImDOaFkd9_b0LpSRLvJzx6eWo5xAW-2vDBlqFrJIC1QBi7Ji1pXI63z7oMjzVQeSDZe0iaSLUT_0nM0uCl_VChHytezao3rGOCF_ZKZytmRDEwg16poYlgnDnYz0XetwJyXcGVHlkwnRIZDXeKkrLoPAuJrem9Eo5G2MshPbeMlzPIfH8I8VRNQyG07S569KuuuQeDHqO6a0qEDdqU13P1ffsVB_JRoEZaJ6ui9zPz9VZy0yVwnXxtX00znXyXlNIOvx_fRNBx1EDCi8fXeMMGsTOKCTyGVmaw"
JWKS_URL = "https://auth.immocloud.ro/realms/immocloud/protocol/openid-connect/certs"
ISSUER = "https://auth.immocloud.ro/realms/immocloud"

def validate_token():
    print(f"Validating token against {JWKS_URL}")
    
    try:
        # Use PyJWKClient to fetch keys
        jwks_client = PyJWKClient(JWKS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(TOKEN)
        
        print(f"Key ID found: {signing_key.key_id}")
        
        data = jwt.decode(
            TOKEN,
            signing_key.key,
            algorithms=["RS256"],
            issuer=ISSUER,
            options={"verify_aud": False}
        )
        print("SUCCESS! Token is valid.")
        print(f"User: {data.get('preferred_username')}")
        
    except jwt.ExpiredSignatureError:
        print("ERROR: Token received is Expired!")
    except jwt.InvalidIssuerError:
        print("ERROR: Invalid Issuer!")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    validate_token()
