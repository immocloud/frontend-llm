# api/config.py - Configuration management
# Loads settings from environment variables with sensible defaults

import os
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # ==========================================================================
    # AUTHENTICATION / KEYCLOAK
    # ==========================================================================
    auth_enabled: bool = False
    allow_anonymous: bool = True
    
    keycloak_url: str = "https://auth.immocloud.ro"
    keycloak_internal_url: Optional[str] = None
    keycloak_realm: str = "immocloud"
    keycloak_client_id: str = "immo-search"
    
    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"
    
    @property
    def keycloak_jwks_url(self) -> str:
        # Use internal URL if available for fetching certs, otherwise public
        base_url = self.keycloak_internal_url or self.keycloak_url
        return f"{base_url}/realms/{self.keycloak_realm}/protocol/openid-connect/certs"
    
    # ==========================================================================
    # OPENSEARCH
    # ==========================================================================
    opensearch_url: str = "https://192.168.80.199:9200"
    opensearch_user: str = "admin"
    opensearch_pass: str = "FaraParole69"
    opensearch_index: str = "real-estate-*"
    opensearch_verify_ssl: bool = False
    
    # Memory/sessions index
    memory_index: str = "search-conversations"
    
    # Embedding model for neural search
    embedding_model_id: str = "NV1NjpsB_9h2UAIWX3NH"
    
    @property
    def opensearch_auth(self) -> tuple:
        return (self.opensearch_user, self.opensearch_pass)
    
    # ==========================================================================
    # LLM / OLLAMA
    # ==========================================================================
    ollama_url: str = "http://192.168.80.197:11434"
    ollama_model: str = "gpt-oss:20b-cloud"
    ollama_timeout: int = 120
    admin_api_key: str = "secret-admin-key"
    
    # ==========================================================================
    # API SERVER
    # ==========================================================================
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    
    # CORS
    cors_origins: str = "*"  # Comma-separated list or "*"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Convenience exports
settings = get_settings()
