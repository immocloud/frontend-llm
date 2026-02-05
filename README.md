# Smart Real Estate Search API

Natural language search for Romanian real estate powered by LLM query parsing and OpenSearch hybrid search.

## Server Deployment

**All repos are located at:** `/home/vlad/repos/[repo-name]` on all servers

```bash
# On 192.168.80.198 (Search API server)
cd /home/vlad/repos/frontend-llm
docker-compose -f docker-compose.api.yml up --build -d
```

## Features

- 🗣️ **Natural Language Queries** - Search in Romanian: "caut apartament 2 camere in Pallady, pet friendly"
- 🧠 **Conversation Memory** - Follow-up queries build on context: "sa fie sub 600 euro"
- 🔍 **Hybrid Search** - Combines keyword matching with neural/semantic search
- 🔐 **Keycloak Auth** - JWT authentication with DLS (Document Level Security)
- 📊 **Rich Results** - Images, attributes, relevance scores, location data

## Project Structure

```
frontend-llm/
├── api/                    # FastAPI application
│   ├── __init__.py
│   ├── auth.py            # Keycloak JWT authentication
│   ├── config.py          # Settings from environment
│   ├── main.py            # FastAPI app & endpoints
│   ├── models.py          # Pydantic models
│   └── search.py          # Search logic wrapper
├── opensearch-connector/   # OpenSearch setup scripts
│   ├── 1_create_ml_connector.py    # Create Ollama ML connector
│   ├── 2_create_ingest_pipeline.py # Create embedding pipeline
│   └── 3_update_embeddings_ollama_pit.py # Batch update embeddings
├── smart_search.py        # Core search logic (LLM parsing + query building)
├── .env.example           # Environment variables template
└── venv/                  # Python virtual environment
```

## Quick Start

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install fastapi uvicorn pydantic-settings python-jose httpx requests

# 3. Configure environment
cp .env.example .env
# Edit .env with your Keycloak/OpenSearch settings

# 4. Run the API
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/search` | POST | Natural language search |
| `/session/{id}` | GET | Get session state |
| `/session/{id}/history` | GET | Get query history |
| `/session/{id}` | DELETE | Delete session |
| `/session/{id}/reset` | POST | Reset session filters |
| `/sessions` | GET | List user's sessions |
| `/me` | GET | Current user info |

## Search Example

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-jwt-token>" \
  -d '{"query": "apartament 2 camere de inchiriat in Pallady, pet friendly"}'
```

Response includes:
- Parsed filters (location, price, rooms, features)
- Rich results with images, attributes, relevance scores
- Session ID for follow-up queries

## Configuration

See `.env.example` for all available settings:

- `AUTH_ENABLED` - Enable JWT authentication
- `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID` - Keycloak settings
- `OPENSEARCH_URL`, `OPENSEARCH_USER`, `OPENSEARCH_PASS` - OpenSearch connection
- `OLLAMA_URL`, `OLLAMA_MODEL` - LLM for query parsing

## Architecture

```
User Query → LLM Parser → OpenSearch Query Builder → Hybrid Search → Results
     ↓                           ↓
  "2 camere              bool + neural query
   pet friendly"         with must_not exclusions
```

The LLM only parses the query into structured filters - it never sees the results. This ensures:
- Deterministic, reproducible searches
- No hallucinated results
- Fast response times
