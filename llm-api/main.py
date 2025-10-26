from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import os

app = FastAPI(title="Neura LLM Middleware")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST")
OPENSEARCH_USER = os.getenv("OPENSEARCH_USER")
OPENSEARCH_PASS = os.getenv("OPENSEARCH_PASS")

MODEL = "gemma:2b"  # or mistral:7b-instruct-q4_K_M


class QueryInput(BaseModel):
    prompt: str


@app.get("/status")
def status():
    try:
        ollama_ok = requests.get(f"{OLLAMA_HOST}/api/tags").status_code == 200
        os_ok = requests.get(f"{OPENSEARCH_HOST}", auth=(OPENSEARCH_USER, OPENSEARCH_PASS), verify=False).status_code == 200
        return {"ollama": ollama_ok, "opensearch": os_ok}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query")
def query_llm(data: QueryInput):
    system_prompt = (
        "Ești un asistent care generează interogări OpenSearch în format JSON valid pentru un index imobiliar. "
        "Returnează EXCLUSIV JSON, fără text, fără explicații, fără ``` sau alte delimitatoare. "
        "Câmpuri disponibile: name, description, location_1, location_2, location_3, price, valid_from, visible. "
        "Structura trebuie să urmeze formatul corect pentru OpenSearch: "
        "{ \"query\": { \"bool\": { \"must\": [ {\"match\": {...}}, {\"range\": {...}} ] } } }. "
        "Pentru prețuri, folosește range -> {\"lte\": valoare}. "
        "Pentru locații, folosește match pe location_1 și location_2. "
        "Pentru căutări generale, folosește multi_match pe name și description."
    )


    # Step 1: Ask LLM to generate the OpenSearch query
    payload = {
        "model": MODEL,
        "stream": False,
        "prompt": f"{system_prompt}\n\nCerere: {data.prompt}"
    }

    llm_response = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload)
    if llm_response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to query LLM")

    text = llm_response.json().get("response", "")
    try:
        os_query = eval(text)  # may switch to json.loads() if model outputs clean JSON
    except Exception:
        raise HTTPException(status_code=500, detail=f"Invalid JSON from model: {text}")

    # Step 2: Send to OpenSearch
    os_response = requests.post(
        f"{OPENSEARCH_HOST}/real-estate/_search",
        json=os_query,
        auth=(OPENSEARCH_USER, OPENSEARCH_PASS),
        verify=False
    )

    if os_response.status_code != 200:
        raise HTTPException(status_code=500, detail=f"OpenSearch error: {os_response.text}")

    return {
        "generated_query": os_query,
        "results": os_response.json().get("hits", {}).get("hits", [])
    }
