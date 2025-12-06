# Smart Real Estate Search API - Complete Documentation

## Overview

A natural language search API for Romanian real estate with:
- **LLM Query Parsing**: Parses Romanian/English natural language into structured filters
- **Conversation Memory**: Follow-up queries refine previous searches
- **Agent Detection**: Cross-index lookup to identify agency listings
- **Keycloak JWT Auth**: Optional authentication with DLS (Document Level Security)
- **BGE-M3 Embeddings**: Semantic search using OpenSearch neural queries

## Deployment

### Docker

```bash
cd /home/vlad/repos/frontend-llm
docker-compose -f docker-compose.api.yml up --build -d
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_ENABLED` | `false` | Enable Keycloak JWT validation |
| `KEYCLOAK_REALM_URL` | `https://auth.immocloud.ro/realms/immocloud` | Keycloak realm URL |
| `OPENSEARCH_URL` | `https://192.168.40.101:9200` | OpenSearch cluster URL |
| `OPENSEARCH_INDEX` | `real-estate-*` | Index pattern for listings |
| `OLLAMA_URL` | `http://192.168.10.115:11434` | Ollama LLM server |
| `OLLAMA_MODEL` | `gpt-oss:20b-cloud` | Model for query parsing |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |

---

## API Endpoints

### OpenAPI Spec

```
GET /openapi.json   # Full OpenAPI 3.0 specification
GET /docs           # Swagger UI
GET /redoc          # ReDoc UI
```

---

## 1. Search Listings

**POST /search**

Natural language search with optional UI toggles.

### Request

```typescript
interface SearchRequest {
  query: string;              // Natural language query (required)
  size?: number;              // Results per page (1-100, default: 25)
  exclude_agencies?: boolean; // UI toggle: true=hide agencies, false=show all, null=use NLP
}
```

### Query Parameter

```
?session_id=abc123   // Optional: session ID for conversation continuity
```

### Response

```typescript
interface SearchResponse {
  success: boolean;
  query: string;
  parsed_filters: SearchFilters;
  total: number;
  results: SearchResult[];
  session_id: string;
  user_id: string;
}

interface SearchFilters {
  location: string | null;      // Neighborhood (e.g., "Titan", "Pallady")
  city: string | null;          // City (normalized: "Bucuresti")
  transaction: string | null;   // "Vanzare" | "Inchiriere"
  property_type: string | null; // "Apartamente" | "Case" | "Garsoniera"
  rooms: number | null;         // 1-5
  price_min: number | null;
  price_max: number | null;
  keywords: string[];           // ["modern", "balcon", etc.]
  features: SearchFeatures;
  exclude_agencies: boolean;    // Whether agencies were filtered
}

interface SearchFeatures {
  animale: "WANT" | "EXCLUDE" | null;   // Pet friendly
  fumatori: "WANT" | "EXCLUDE" | null;  // Smokers allowed
  parcare: "WANT" | "EXCLUDE" | null;   // Parking
  mobilat: "WANT" | "EXCLUDE" | null;   // Furnished
  centrala: "WANT" | "EXCLUDE" | null;  // Central heating
}

interface SearchResult {
  id: string;
  ad_id: string;
  title: string;
  description: string;          // Truncated to ~300 chars
  price: number | null;
  currency: string;             // "EUR" | "RON"
  location: string;             // "Bucuresti, Sector 3"
  categories: string[];         // ["Inchiriere", "Apartamente", "2 camere"]
  surface: string | null;       // "52 m²"
  phone: string;
  date: string;                 // "12/06/25, 10:30 AM"
  images: string[];             // First 5 image URLs
  image_count: number;          // Total images available
  source: string;               // "olx" | "romimo" | "anuntul"
  url: string;                  // Link to original listing
  score: number;                // Relevance 0-100 (for UI colored bullets)
  is_agency: boolean;           // True if phone found in agents index
  seller_type: string;          // "private" | "agent" | "agency"
}
```

### Example: Basic Search

```bash
curl -X POST 'http://localhost:8000/search' \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "apartament 2 camere Titan sub 500 euro",
    "size": 10
  }'
```

### Example: With UI Toggle (Exclude Agencies)

```bash
curl -X POST 'http://localhost:8000/search' \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "apartament Titan",
    "exclude_agencies": true
  }'
```

### Example: Conversational Follow-up

```bash
# First query
curl -X POST 'http://localhost:8000/search?session_id=my-session' \
  -d '{"query": "apartament Titan 2 camere"}'

# Follow-up (preserves context)
curl -X POST 'http://localhost:8000/search?session_id=my-session' \
  -d '{"query": "dar cu parcare"}'
```

---

## 2. Session Management

### List User Sessions

**GET /sessions**

Returns all sessions for the authenticated user.

```bash
curl -H 'Authorization: Bearer <token>' http://localhost:8000/sessions
```

Response:
```json
{
  "sessions": [
    {
      "session_id": "abc123",
      "last_query": "apartament Titan",
      "updated_at": "2025-12-06T10:30:00Z",
      "filters": { ... }
    }
  ]
}
```

### Get Session Info

**GET /session/{session_id}**

```bash
curl http://localhost:8000/session/abc123
```

### Get Session History

**GET /session/{session_id}/history**

Returns query history for a session.

```bash
curl http://localhost:8000/session/abc123/history
```

Response:
```json
{
  "session_id": "abc123",
  "history": [
    {
      "query": "apartament Titan",
      "timestamp": "2025-12-06T10:30:00Z",
      "filters": { ... }
    }
  ]
}
```

### Reset Session

**POST /session/{session_id}/reset**

Clears search context for a session.

```bash
curl -X POST http://localhost:8000/session/abc123/reset
```

---

## 3. User Info

**GET /me**

Returns current user info from JWT.

```bash
curl -H 'Authorization: Bearer <token>' http://localhost:8000/me
```

Response:
```json
{
  "user_id": "d992e423-1395-4997-bf32-418120bfe68d",
  "username": "orgadmin1",
  "email": "orgadmin1@imomo.com",
  "org": "apisix",
  "roles": ["orgadmin"]
}
```

---

## 4. Health Check

**GET /health**

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "healthy",
  "service": "smart-search",
  "auth_enabled": false
}
```

---

## Authentication

### When AUTH_ENABLED=true

All endpoints except `/health` require a valid Keycloak JWT:

```bash
curl -H 'Authorization: Bearer <keycloak-jwt>' http://localhost:8000/search ...
```

### When AUTH_ENABLED=false (development)

All endpoints work without authentication. User ID defaults to "anonymous".

---

## UI Integration Guide

### 1. Search Component

```typescript
// React example
const [excludeAgencies, setExcludeAgencies] = useState(true); // Default: hide agencies
const [sessionId, setSessionId] = useState<string | null>(null);

async function search(query: string) {
  const params = new URLSearchParams();
  if (sessionId) params.set('session_id', sessionId);
  
  const response = await fetch(`/api/search?${params}`, {
    method: 'POST',
    headers: { 
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`  // If auth enabled
    },
    body: JSON.stringify({
      query,
      size: 25,
      exclude_agencies: excludeAgencies
    })
  });
  
  const data = await response.json();
  setSessionId(data.session_id);  // Preserve for follow-ups
  return data;
}
```

### 2. Agency Toggle Component

```tsx
<Switch 
  checked={!excludeAgencies}  // ON = show agencies
  onChange={(checked) => setExcludeAgencies(!checked)}
  label={excludeAgencies ? "Doar particulari" : "Toate anunțurile"}
/>
```

### 3. Result Card with Score Indicator

```tsx
function ScoreIndicator({ score }: { score: number }) {
  // score: 0-100
  const color = score >= 80 ? 'green' : score >= 60 ? 'yellow' : 'red';
  return <div className={`score-dot ${color}`} title={`${score}% relevant`} />;
}

function ResultCard({ result }: { result: SearchResult }) {
  return (
    <div className="card">
      <ScoreIndicator score={result.score} />
      {result.is_agency && <span className="badge">Agenție</span>}
      <h3>{result.title}</h3>
      <p>{result.price} {result.currency}</p>
      <p>{result.location}</p>
      {/* ... */}
    </div>
  );
}
```

### 4. Conversation Flow

The API maintains context per session. Use the same `session_id` for follow-up queries:

```
User: "apartament Titan 2 camere"
→ Returns 2-room apartments in Titan

User: "dar cu parcare" (same session)
→ Returns 2-room apartments in Titan WITH parking

User: "pana in 500 euro" (same session)  
→ Returns 2-room apartments in Titan with parking UNDER 500€
```

---

## Natural Language Examples

### Romanian Queries
- "Caut apartament de inchiriat in Pallady cu 2 camere"
- "Casa de vanzare in Cluj sub 150000 euro"
- "Garsoniera mobilata cu centrala proprie"
- "apartament pet friendly in Titan"
- "fara agentii" / "doar particulari" (triggers exclude_agencies)

### English Queries
- "2 bedroom apartment in Bucharest for rent"
- "House for sale under 200k"
- "no agents please"

### Follow-up Queries
- "dar mai ieftin" (but cheaper)
- "si cu parcare" (and with parking)
- "fara fumatori" (no smokers)

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Frontend  │────▶│  Search API  │────▶│    OpenSearch   │
│   (React)   │     │   (FastAPI)  │     │   (real-estate) │
└─────────────┘     └──────┬───────┘     └─────────────────┘
                           │
                    ┌──────▼───────┐
                    │  Ollama LLM  │
                    │ (Query Parse)│
                    └──────────────┘
```

### Indices
- `real-estate-*` - Main listings (~27k documents)
- `search-conversations` - Session memory (DLS enabled)
- `agents` - Known agent phones (for is_agency detection)

---

## Files Structure

```
api/
├── main.py        # FastAPI app, endpoints
├── models.py      # Pydantic request/response models
├── search.py      # LLM parsing, OpenSearch queries, agent lookup
├── auth.py        # Keycloak JWT validation
├── config.py      # Settings from environment
└── requirements.txt
```

---

## Changelog

### 2025-12-06
- Added `exclude_agencies` UI toggle parameter to SearchRequest
- Added `is_agency` and `seller_type` fields to SearchResult
- Implemented cross-index agent lookup from `agents` index
- Added relevance `score` (0-100) for UI colored indicators
- Natural language detection for "fara agentii", "doar particulari"
