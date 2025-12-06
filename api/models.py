# api/models.py - Pydantic models for API request/response
# Rich models designed for frontend UI display

from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


# =============================================================================
# REQUEST MODELS
# =============================================================================

class SearchRequest(BaseModel):
    """Search request with natural language query"""
    query: str = Field(..., description="Natural language search query")
    size: int = Field(25, ge=1, le=100, description="Number of results")
    exclude_agencies: Optional[bool] = Field(None, description="UI toggle: true=hide agencies, false=show all, null=use query parsing")


# =============================================================================
# FILTER MODELS
# =============================================================================

class SearchFeatures(BaseModel):
    """Feature preferences (pet friendly, parking, etc.)"""
    animale: Optional[str] = None  # WANT, EXCLUDE, or None
    fumatori: Optional[str] = None
    parcare: Optional[str] = None
    mobilat: Optional[str] = None
    centrala: Optional[str] = None


class SearchFilters(BaseModel):
    """Parsed search filters from LLM"""
    location: Optional[str] = None
    city: Optional[str] = None
    transaction: Optional[str] = None
    property_type: Optional[str] = None
    rooms: Optional[int] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    keywords: List[str] = []
    features: SearchFeatures = Field(default_factory=SearchFeatures)
    exclude_agencies: bool = Field(False, description="Filter out known agents/agencies")


# =============================================================================
# RESULT MODELS - Rich data for UI cards
# =============================================================================

class SearchResult(BaseModel):
    """Single search result - streamlined for card UI"""
    
    # Identity
    id: str = Field(..., description="OpenSearch document ID")
    ad_id: Optional[str] = Field(None, description="Original ad ID from source")
    
    @field_validator('ad_id', mode='before')
    @classmethod
    def coerce_ad_id(cls, v):
        if v is None:
            return None
        return str(v)
    
    # Content
    title: str
    description: str = Field("", description="Truncated description")
    
    # Price
    price: Optional[float] = None
    currency: str = "EUR"
    
    # Location (formatted for display)
    location: str = Field("", description="Location: City, Area")
    
    # Categories (tags shown on card)
    categories: List[str] = Field(default_factory=list, description="Tags: Inchiriere, Apartamente, 2 camere")
    
    # Key attributes shown on card
    surface: Optional[str] = None  # e.g. "58 m²"
    phone: Optional[str] = None
    date: Optional[str] = None  # e.g. "12/6/25, 12:25 AM"
    
    # Images
    images: List[str] = Field(default_factory=list)
    image_count: int = 0
    
    # Source & link
    source: Optional[str] = None  # olx, anuntul, etc.
    url: Optional[str] = None  # View Original link
    
    # Relevance score (0-100) for colored bullet in UI
    score: int = Field(0, description="Relevance score 0-100 for UI indicator")
    
    # Seller info (from cross-index agent lookup)
    is_agency: bool = Field(False, description="True if seller is known agent/agency")
    seller_type: str = Field("unknown", description="private, agent, agency, or unknown")


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class SearchResponse(BaseModel):
    """Full search response"""
    success: bool = True
    query: str
    parsed_filters: SearchFilters
    total: int
    results: List[SearchResult]
    session_id: str
    user_id: str


class SessionInfo(BaseModel):
    """Session state information"""
    user_id: str
    session_id: str
    filters: SearchFilters
    query_count: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class HistoryItem(BaseModel):
    """Single query history item"""
    query: str
    timestamp: str


class UserInfo(BaseModel):
    """Current user information"""
    user_id: str
    username: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    roles: List[str] = []
    groups: List[str] = []
    is_anonymous: bool = False
