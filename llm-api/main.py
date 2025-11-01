from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests, json, os, re, time
from datetime import datetime

app = FastAPI()

# --- Config ---
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST")
OPENSEARCH_USER = os.getenv("OPENSEARCH_USER")
OPENSEARCH_PASS = os.getenv("OPENSEARCH_PASS")

LOG_DIR = "/app/logs"
os.makedirs(LOG_DIR, exist_ok=True)


# --- Models ---
class QueryRequest(BaseModel):
    prompt: str
    model: str = "gpt-oss:20b"


# --- Step 1: Ask LLM for intent JSON only ---
def call_llm(prompt: str, model: str):
    full_prompt = f"""
    You are an intent extraction assistant for real estate searches.

    The user will write a search request in Romanian (e.g. "apartamente cu 2 camere în Titan sub 150000 euro").
    You must return ONLY a JSON object describing the intent — NO markdown, NO explanations, NO extra text.

    Expected keys:
    - transaction: "inchiriere" or "vanzare" if mentioned
    - property_type: e.g. "apartamente", "case", "terenuri"
    - num_rooms: integer if specified
    - price_max: integer if specified
    - currency: "EUR" or "RON" if mentioned
    - location: general area (city, sector, or neighborhood)
    - location_text: copy of the raw location text from the user query

    Example input: apartamente cu 2 camere în Cluj sub 100000 euro
    Example output:
    {{
      "transaction": "vanzare",
      "property_type": "apartamente",
      "num_rooms": 2,
      "price_max": 100000,
      "currency": "EUR",
      "location": "Cluj",
      "location_text": "Cluj"
    }}

    User request: "{prompt}"
    """

    start = time.time()
    resp = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={"model": model, "prompt": full_prompt, "stream": False},
        timeout=180,
    )
    elapsed = time.time() - start

    resp.raise_for_status()
    response = resp.json().get("response", "").strip()
    return response, elapsed


# --- Step 2: Parse and normalize ---
def parse_intent(raw):
    clean = re.sub(r"```.*?```", "", raw, flags=re.DOTALL).strip()
    try:
        data = json.loads(clean)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    # Normalize variants
    mapping = {
        "price": "price_max",
        "max_price": "price_max",
        "pret_maxim": "price_max",
    }
    for old, new in mapping.items():
        if old in data and new not in data:
            data[new] = data[old]

    # Lowercase text values
    for k, v in data.items():
        if isinstance(v, str):
            data[k] = v.strip().lower()

    return data


# --- Step 3: Deterministic hybrid query builder ---
def build_query(intent):
    must = []
    should = []

    # Transaction, property type, room count
    if intent.get("transaction"):
        must.append({"match": {"categories": intent["transaction"].capitalize()}})
    if intent.get("property_type"):
        must.append({"match": {"categories": intent["property_type"].capitalize()}})
    if intent.get("num_rooms"):
        must.append({"match": {"categories": f"{intent['num_rooms']} camere"}})

    # Price and currency
    if intent.get("price_max"):
        must.append({"range": {"price": {"lte": int(intent["price_max"])}}})
    if intent.get("currency"):
        must.append({"term": {"currency": intent["currency"].upper()}})

    # Location search — no hardcoding
    if loc := intent.get("location"):
        should.extend([
            {"match": {"location_1": loc}},
            {"match": {"location_2": loc}},
            {"match": {"location_3": loc}},
            {"multi_match": {
                "query": loc,
                "fields": ["name", "description", "driver_title"],
                "fuzziness": "AUTO"
            }}
        ])

    query = {
        "query": {
            "bool": {
                "must": must,
                "should": should,
                "minimum_should_match": 1 if should else 0,
            }
        },
        "sort": [{"valid_from": "desc"}],
    }

    return query


# --- Step 4: Fallback fulltext ---
def fallback_query(prompt):
    return {
        "query": {
            "multi_match": {
                "query": prompt,
                "fields": ["name", "description", "driver_title", "location_1", "location_2", "location_3"],
                "fuzziness": "AUTO",
            }
        },
        "sort": [{"valid_from": "desc"}],
    }


# --- Step 5: Execute query ---
def run_opensearch_query(body):
    start = time.time()
    r = requests.post(
        f"{OPENSEARCH_HOST}/real-estate/_search",
        auth=(OPENSEARCH_USER, OPENSEARCH_PASS),
        json=body,
        verify=False,
        timeout=60,
    )
    elapsed = time.time() - start
    r.raise_for_status()
    return r.json().get("hits", {}).get("hits", []), elapsed


# --- API ---
@app.post("/query")
def query(req: QueryRequest):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    raw, llm_time = call_llm(req.prompt, req.model)
    with open(f"{LOG_DIR}/llm_raw_{ts}.txt", "w") as f:
        f.write(raw)

    intent = parse_intent(raw)
    if not intent:
        print("[WARN] Invalid intent — using fallback query.")
        query_body = fallback_query(req.prompt)
    else:
        query_body = build_query(intent)

    with open(f"{LOG_DIR}/executed_query_{ts}.json", "w") as f:
        json.dump(query_body, f, indent=2)

    results, search_time = run_opensearch_query(query_body)
    total_time = llm_time + search_time

    return {
        "results": results,
        "original_prompt": req.prompt,
        "generated_query": query_body,
        "model": req.model,
        "timing": {
            "llm_seconds": round(llm_time, 2),
            "search_seconds": round(search_time, 2),
            "total_seconds": round(total_time, 2)
        }
    }


@app.get("/status")
def status():
    try:
        r = requests.get(OPENSEARCH_HOST, auth=(OPENSEARCH_USER, OPENSEARCH_PASS), verify=False, timeout=5)
        r.raise_for_status()
        return {"status": "ok", "opensearch": r.status_code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
