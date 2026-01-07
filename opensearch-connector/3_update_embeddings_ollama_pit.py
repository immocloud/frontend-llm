#!/usr/bin/env python3
import os
import sys
import time
import json
import traceback
from typing import List, Dict, Any, Optional

import requests

# ------------------- CONFIG -------------------

OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "https://192.168.80.199:9200")
OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER", "admin")
OPENSEARCH_PASS = os.environ.get("OPENSEARCH_PASS", "FaraParole69")

INDEX_NAME = os.environ.get("INDEX_NAME", "real-estate-bge-v2")

# 🔥 OLLAMA CONFIG
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "bge-m3:q4_K_M")

VERIFY_TLS = False  # OpenSearch TLS verify

SCROLL_SIZE = int(os.environ.get("SCROLL_SIZE", "256"))  # docs per PIT page
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "32"))     # docs per embedding call
PIT_KEEP_ALIVE = "5m"
SLEEP_BETWEEN_PASSES = 5  # seconds


# ------------------- SESSION -------------------

os_session = requests.Session()
os_session.auth = (OPENSEARCH_USER, OPENSEARCH_PASS)
os_session.verify = VERIFY_TLS
os_session.headers.update({"Content-Type": "application/json"})

ollama_session = requests.Session()  # no auth, local


# ------------------- HELPERS -------------------

def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_remaining_count() -> int:
    """Count docs that either have embedding_status=failed OR missing listing_vector."""
    url = f"{OPENSEARCH_HOST}/{INDEX_NAME}/_count"
    query = {
        "query": {
            "bool": {
                "should": [
                    {"term": {"embedding_status": "failed"}},
                    {"bool": {"must_not": {"exists": {"field": "listing_vector"}}}},
                ],
                "minimum_should_match": 1,
            }
        }
    }
    try:
        r = os_session.get(url, data=json.dumps(query), timeout=30)
        r.raise_for_status()
        return r.json().get("count", 0)
    except Exception as e:
        log(f"Error getting remaining count: {e}")
        return 0


def open_pit() -> Optional[str]:
    """Open a Point-In-Time context for the index."""
    url = f"{OPENSEARCH_HOST}/{INDEX_NAME}/_search/point_in_time?keep_alive={PIT_KEEP_ALIVE}"
    try:
        r = os_session.post(url, timeout=30)
        r.raise_for_status()
        pit_id = r.json().get("pit_id")
        if not pit_id:
            log("Failed to get pit_id from response.")
            return None
        return pit_id
    except Exception as e:
        log(f"Error opening PIT: {e}")
        return None


def close_pit(pit_id: str) -> None:
    """Close a PIT."""
    url = f"{OPENSEARCH_HOST}/_search/point_in_time"
    try:
        os_session.delete(url, data=json.dumps({"id": pit_id}), timeout=10)
    except Exception:
        pass


def build_text_for_doc(src: Dict[str, Any]) -> str:
    """Build text to embed from title + description."""
    desc = src.get("description") or ""
    title = src.get("driver_title") or src.get("name") or ""
    text = f"{title}\n\n{desc}".strip()
    return text


def call_embedding_model(texts: List[str]) -> Optional[List[List[float]]]:
    """
    Call Ollama embeddings API with a batch of texts.
    Uses /api/embed (new endpoint) which returns L2-normalized vectors.
    """
    if not texts:
        return []

    body = {
        "model": OLLAMA_MODEL,
        "input": texts,
    }

    try:
        r = ollama_session.post(
            f"{OLLAMA_HOST}/api/embed",
            json=body,
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()

        # Ollama docs: /api/embed returns a JSON array by default.
        # Some versions wrap in {"embeddings": [...]}.
        if isinstance(data, dict) and "embeddings" in data:
            return data["embeddings"]
        if isinstance(data, list):
            return data

        log(f"Unexpected Ollama embed response structure: {data}")
        return None

    except Exception as e:
        log(f"Ollama embedding failed: {e}")
        traceback.print_exc()
        return None


def bulk_update_vectors(updates: List[Dict[str, Any]]) -> bool:
    """
    Bulk update / upsert listing_vector + embedding_status.
    updates: list of { "_id": ..., "vector": [...], "status": "success"/"failed"/"fatal" }
    """
    if not updates:
        return True

    lines = []
    for u in updates:
        _id = u["_id"]
        vector = u.get("vector")
        status = u.get("status", "success")

        doc = {
            "embedding_status": status,
        }
        if vector:
            doc["listing_vector"] = vector

        lines.append(json.dumps({"update": {"_index": INDEX_NAME, "_id": _id}}))
        lines.append(json.dumps({"doc": doc}))

    ndjson_body = "\n".join(lines) + "\n"
    url = f"{OPENSEARCH_HOST}/_bulk"
    headers = {"Content-Type": "application/x-ndjson"}

    try:
        r = os_session.post(url, data=ndjson_body, headers=headers, timeout=120)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            for item in data.get("items", [])[:5]:
                if "update" in item and item["update"].get("error"):
                    log(f"Bulk item error: {item['update']['error']}")
            return False
        return True
    except Exception as e:
        log(f"Exception during bulk update: {e}")
        traceback.print_exc()
        return False


def process_once() -> int:
    """
    One full pass over the index using PIT:
    - open PIT
    - page through docs with size=SCROLL_SIZE + search_after
    - embed in batches of BATCH_SIZE
    - bulk update listing_vector + embedding_status
    """
    pit_id = open_pit()
    if not pit_id:
        log("Could not open PIT, aborting pass.")
        return 0

    total_processed = 0
    search_after = None

    try:
        while True:
            query: Dict[str, Any] = {
                "size": SCROLL_SIZE,
                "query": {
                    "bool": {
                        "should": [
                            {"term": {"embedding_status": "failed"}},
                            {"bool": {"must_not": {"exists": {"field": "listing_vector"}}}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "sort": [
                    {"_shard_doc": "asc"}
                ],
                "pit": {
                    "id": pit_id,
                    "keep_alive": PIT_KEEP_ALIVE,
                },
                "_source": [
                    "name",
                    "description",
                    "driver_title",
                    "embedding_status",
                ],
            }

            if search_after is not None:
                query["search_after"] = search_after

            url = f"{OPENSEARCH_HOST}/_search"
            try:
                r = os_session.post(url, data=json.dumps(query), timeout=120)
                r.raise_for_status()
            except Exception as e:
                log(f"Search in PIT failed: {e}")
                break

            data = r.json()
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break

            # Prepare next page
            search_after = hits[-1].get("sort")

            # Batch texts for embedding
            batch_texts: List[str] = []
            batch_meta: List[Dict[str, Any]] = []

            def flush_batch():
                nonlocal total_processed, batch_texts, batch_meta
                if not batch_meta:
                    return

                vectors = call_embedding_model(batch_texts)
                if vectors is None:
                    # mark as failed so they can be retried on next pass
                    log("Ollama call failed for batch, marking docs as failed.")
                    failed_updates = [
                        {"_id": m["_id"], "vector": None, "status": "failed"}
                        for m in batch_meta
                    ]
                    bulk_update_vectors(failed_updates)
                else:
                    updates = []
                    for meta, vec in zip(batch_meta, vectors):
                        if not vec:
                            meta["status"] = "fatal"
                        else:
                            meta["vector"] = vec
                            meta["status"] = "success"
                        updates.append(meta)

                    if bulk_update_vectors(updates):
                        total_processed += len(updates)

                batch_texts = []
                batch_meta = []

            for hit in hits:
                _id = hit.get("_id")
                src = hit.get("_source", {})

                text = build_text_for_doc(src)
                if not text.strip():
                    # nothing to embed, mark as fatal
                    batch_meta.append({"_id": _id, "vector": None, "status": "fatal"})
                    continue

                batch_texts.append(text)
                batch_meta.append({"_id": _id, "vector": None, "status": "success"})

                if len(batch_texts) >= BATCH_SIZE:
                    flush_batch()

            # flush remaining
            if batch_texts or batch_meta:
                flush_batch()

        return total_processed

    finally:
        close_pit(pit_id)


def main():
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    log(f"Starting embedding repair on index '{INDEX_NAME}' using Ollama model '{OLLAMA_MODEL}'")
    log(f"OpenSearch: {OPENSEARCH_HOST}")
    log(f"Ollama: {OLLAMA_HOST}")
    log(f"Scroll/PIT page size: {SCROLL_SIZE}, batch size: {BATCH_SIZE}")

    while True:
        remaining = get_remaining_count()
        log(f"Documents remaining to process (failed or missing vector): {remaining}")

        if remaining == 0:
            log("All documents processed successfully. 🎉")
            break

        processed = process_once()
        log(f"Pass completed, processed {processed} documents.")

        if processed == 0:
            log("No documents processed in this pass. Probably only 'fatal' docs remain.")
            break

        log(f"Sleeping {SLEEP_BETWEEN_PASSES}s before next pass...")
        time.sleep(SLEEP_BETWEEN_PASSES)


if __name__ == "__main__":
    main()
