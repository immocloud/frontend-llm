# Simple mock server to emulate Ollama (LLM) and OpenSearch endpoints for local testing
# Run with: python frontend-llm/tools/mock_services.py

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import uvicorn
import json
from typing import Dict

app = FastAPI()

# In-memory storage for memory index docs
memory_store: Dict[str, Dict] = {}

# LLM generate endpoint (mock of Ollama)
@app.post("/api/generate")
async def generate(payload: Request):
    data = await payload.json()
    prompt = data.get("prompt", "")

    # Return a deterministic parsed JSON based on prompt examples (very simple)
    parsed = {
        "location": None,
        "city": None,
        "transaction": None,
        "property_type": None,
        "rooms": None,
        "price_min": None,
        "price_max": None,
        "keywords": [],
        "features": {"animale": None, "fumatori": None, "parcare": None, "mobilat": None, "centrala": None},
        "exclude_agencies": False
    }

    # If prompt contains '2 camere' set rooms
    if '2 camere' in prompt.lower():
        parsed['rooms'] = 2
        parsed['keywords'].append('2 camere')

    # Return as `response` text to mimic Ollama
    return JSONResponse({"response": json.dumps(parsed, ensure_ascii=False)})


# OpenSearch-like endpoints (very small subset)
@app.head("/{index}")
async def head_index(index: str):
    # If memory index exists return 200 otherwise 404
    if index == "search-conversations":
        return Response(status_code=200)
    return Response(status_code=404)


@app.put("/{index}")
async def create_index(index: str, request: Request):
    return JSONResponse({"acknowledged": True})


@app.post("/{index}/_search")
async def search_index(index: str, request: Request):
    # Return a single fake listing hit
    sample_hit = {
        "_index": index,
        "_id": "1",
        "_score": 1.0,
        "_source": {
            "driver_title": "Apartament 2 camere in Pallady",
            "name": "Apartament test",
            "description": "Frumos apartament cu 2 camere",
            "price": 450,
            "currency": "EUR",
            "location_1": "Bucuresti",
            "location_2": "Pallady",
            "location_3": "Pallady",
            "ad_url": "https://example.com/1",
            "ad_id": "1",
            "categories": ["Inchiriere", "Apartamente", "2 camere"],
            "attributes": {"Suprafata utila": 55},
            "src_images": ["https://example.com/img1.jpg"],
            "decrypted_phone": "0712345678",
            "source": "test"
        }
    }

    return JSONResponse({
        "took": 1,
        "timed_out": False,
        "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
        "hits": {"total": {"value": 1}, "max_score": 1.0, "hits": [sample_hit]}
    })


@app.get("/{index}/_doc/{doc_id}")
async def get_doc(index: str, doc_id: str):
    key = f"{index}:{doc_id}"
    doc = memory_store.get(key)
    if not doc:
        return Response(status_code=404)
    return JSONResponse({"_index": index, "_id": doc_id, "_source": doc})


@app.put("/{index}/_doc/{doc_id}")
async def put_doc(index: str, doc_id: str, request: Request):
    payload = await request.json()
    key = f"{index}:{doc_id}"
    memory_store[key] = payload
    return JSONResponse({"result": "created", "_id": doc_id})


@app.delete("/{index}/_doc/{doc_id}")
async def delete_doc(index: str, doc_id: str):
    key = f"{index}:{doc_id}"
    memory_store.pop(key, None)
    return JSONResponse({"result": "deleted"})


@app.post("/agents/_search")
async def agents_search(request: Request):
    # Return empty results
    return JSONResponse({"hits": {"hits": []}})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9201)
