#!/usr/bin/env python3
"""
Re-embed documents that failed due to connection pool timeout issues.
This script addresses the "Acquire operation took longer than maximum time" error
by implementing:
- Aggressive rate limiting
- Smaller batch sizes
- Exponential backoff with jitter
- Connection pool monitoring
- Progress tracking and resumability
"""
import os
import sys
import time
import json
import random
import traceback
from typing import List, Dict, Any, Optional
from datetime import datetime

import requests

# ------------------- CONFIG -------------------

OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "https://192.168.80.199:9200")
OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER", "admin")
OPENSEARCH_PASS = os.environ.get("OPENSEARCH_PASS", "FaraParole69")

INDEX_NAME = os.environ.get("INDEX_NAME", "real-estate-bge-v2")

# Ollama embedding service
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "bge-m3:q4_K_M")

VERIFY_TLS = False

# 🔥 CONSERVATIVE SETTINGS TO AVOID CONNECTION POOL EXHAUSTION
SCROLL_SIZE = int(os.environ.get("SCROLL_SIZE", "100"))     # Reduced from 256
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "8"))         # Reduced from 32
PIT_KEEP_ALIVE = "10m"                                      # Increased from 5m
SLEEP_BETWEEN_BATCHES = float(os.environ.get("SLEEP_BETWEEN_BATCHES", "2.0"))  # seconds
SLEEP_BETWEEN_PASSES = 10  # seconds between full passes
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 5  # seconds

# Connection pool settings
MAX_CONNECTIONS = 10  # Conservative limit
CONNECTION_TIMEOUT = 60  # seconds
READ_TIMEOUT = 120  # seconds

# Progress tracking
PROGRESS_FILE = os.environ.get("PROGRESS_FILE", "re_embed_progress.json")


# ------------------- SESSION -------------------

def create_os_session():
    """Create OpenSearch session with conservative connection settings."""
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=MAX_CONNECTIONS,
        pool_maxsize=MAX_CONNECTIONS,
        max_retries=requests.adapters.Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
    )
    
    session = requests.Session()
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.auth = (OPENSEARCH_USER, OPENSEARCH_PASS)
    session.verify = VERIFY_TLS
    session.headers.update({"Content-Type": "application/json"})
    
    return session


os_session = create_os_session()
ollama_session = requests.Session()


# ------------------- HELPERS -------------------

def log(msg: str) -> None:
    """Log with timestamp."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_progress() -> Dict[str, Any]:
    """Load progress from file."""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            log(f"Warning: Could not load progress file: {e}")
    
    return {
        "total_processed": 0,
        "total_succeeded": 0,
        "total_failed": 0,
        "last_batch_time": None,
        "passes": 0,
        "started_at": datetime.now().isoformat()
    }


def save_progress(progress: Dict[str, Any]) -> None:
    """Save progress to file."""
    try:
        progress["last_updated"] = datetime.now().isoformat()
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(progress, f, indent=2)
    except Exception as e:
        log(f"Warning: Could not save progress: {e}")


def get_failed_docs_count() -> int:
    """Count docs with embedding_status=failed or missing listing_vector."""
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
        r = os_session.get(url, data=json.dumps(query), timeout=CONNECTION_TIMEOUT)
        r.raise_for_status()
        return r.json().get("count", 0)
    except Exception as e:
        log(f"Error getting failed docs count: {e}")
        return 0


def open_pit() -> Optional[str]:
    """Open a Point-In-Time context."""
    url = f"{OPENSEARCH_HOST}/{INDEX_NAME}/_search/point_in_time?keep_alive={PIT_KEEP_ALIVE}"
    
    for attempt in range(MAX_RETRIES):
        try:
            r = os_session.post(url, timeout=CONNECTION_TIMEOUT)
            r.raise_for_status()
            pit_id = r.json().get("pit_id")
            
            if not pit_id:
                log("Failed to get pit_id from response.")
                return None
            
            log(f"PIT opened: {pit_id[:20]}...")
            return pit_id
            
        except Exception as e:
            log(f"Error opening PIT (attempt {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                delay = INITIAL_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1)
                log(f"Retrying in {delay:.1f}s...")
                time.sleep(delay)
    
    return None


def close_pit(pit_id: str) -> None:
    """Close a PIT."""
    url = f"{OPENSEARCH_HOST}/_search/point_in_time"
    try:
        os_session.delete(url, data=json.dumps({"id": pit_id}), timeout=30)
        log("PIT closed.")
    except Exception as e:
        log(f"Warning: Error closing PIT: {e}")


def build_text_for_doc(src: Dict[str, Any]) -> str:
    """Build text to embed from document source."""
    desc = src.get("description") or ""
    title = src.get("driver_title") or src.get("name") or ""
    text = f"{title}\n\n{desc}".strip()
    return text


def call_embedding_model(texts: List[str], retry_count: int = 0) -> Optional[List[List[float]]]:
    """
    Call Ollama embeddings API with exponential backoff and jitter.
    """
    if not texts:
        return []

    body = {
        "model": OLLAMA_MODEL,
        "input": texts,
    }

    for attempt in range(MAX_RETRIES):
        try:
            r = ollama_session.post(
                f"{OLLAMA_HOST}/api/embed",
                json=body,
                timeout=READ_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()

            # Handle different response formats
            if isinstance(data, dict) and "embeddings" in data:
                return data["embeddings"]
            if isinstance(data, list):
                return data

            log(f"Unexpected Ollama response structure: {type(data)}")
            return None

        except requests.exceptions.Timeout:
            log(f"Ollama timeout (attempt {attempt+1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                delay = INITIAL_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 2)
                log(f"Retrying in {delay:.1f}s...")
                time.sleep(delay)
            
        except Exception as e:
            log(f"Ollama embedding failed (attempt {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                delay = INITIAL_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 2)
                time.sleep(delay)
            else:
                traceback.print_exc()

    return None


def bulk_update_vectors(updates: List[Dict[str, Any]]) -> tuple[bool, int, int]:
    """
    Bulk update listing_vector + embedding_status.
    
    Returns: (success, num_succeeded, num_failed)
    """
    if not updates:
        return True, 0, 0

    lines = []
    for u in updates:
        _id = u["_id"]
        vector = u.get("vector")
        status = u.get("status", "success")

        doc = {"embedding_status": status}
        if vector:
            doc["listing_vector"] = vector

        lines.append(json.dumps({"update": {"_index": INDEX_NAME, "_id": _id}}))
        lines.append(json.dumps({"doc": doc}))

    ndjson_body = "\n".join(lines) + "\n"
    url = f"{OPENSEARCH_HOST}/_bulk"
    headers = {"Content-Type": "application/x-ndjson"}

    for attempt in range(MAX_RETRIES):
        try:
            r = os_session.post(url, data=ndjson_body, headers=headers, timeout=READ_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            
            # Count successes and failures
            succeeded = 0
            failed = 0
            
            if data.get("errors"):
                for item in data.get("items", []):
                    if "update" in item:
                        if item["update"].get("error"):
                            failed += 1
                            # Log first few errors
                            if failed <= 3:
                                log(f"Bulk item error: {item['update']['error']}")
                        else:
                            succeeded += 1
                return False, succeeded, failed
            
            succeeded = len(updates)
            return True, succeeded, 0
            
        except Exception as e:
            log(f"Bulk update failed (attempt {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                delay = INITIAL_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(delay)
            else:
                traceback.print_exc()
                return False, 0, len(updates)

    return False, 0, len(updates)


def process_batch_with_rate_limit(
    batch_texts: List[str], 
    batch_meta: List[Dict[str, Any]],
    progress: Dict[str, Any]
) -> tuple[int, int]:
    """
    Process a batch of documents with rate limiting.
    
    Returns: (succeeded, failed)
    """
    if not batch_meta:
        return 0, 0

    # Rate limiting: sleep between batches
    if progress.get("last_batch_time"):
        elapsed = time.time() - progress["last_batch_time"]
        if elapsed < SLEEP_BETWEEN_BATCHES:
            sleep_time = SLEEP_BETWEEN_BATCHES - elapsed
            time.sleep(sleep_time)

    # Call embedding model
    vectors = call_embedding_model(batch_texts)
    
    if vectors is None:
        # Mark all as failed for retry
        log(f"Embedding failed for batch of {len(batch_meta)} docs, marking as failed")
        failed_updates = [
            {"_id": m["_id"], "vector": None, "status": "failed"}
            for m in batch_meta
        ]
        success, _, failed = bulk_update_vectors(failed_updates)
        progress["last_batch_time"] = time.time()
        return 0, len(batch_meta)
    
    # Prepare updates
    updates = []
    for meta, vec in zip(batch_meta, vectors):
        if not vec or len(vec) == 0:
            meta["status"] = "fatal"
            meta["vector"] = None
        else:
            meta["vector"] = vec
            meta["status"] = "success"
        updates.append(meta)

    # Bulk update
    success, succeeded, failed = bulk_update_vectors(updates)
    progress["last_batch_time"] = time.time()
    
    return succeeded, failed


def process_one_pass(progress: Dict[str, Any]) -> tuple[int, int]:
    """
    One full pass over failed documents.
    
    Returns: (total_succeeded, total_failed)
    """
    pit_id = open_pit()
    if not pit_id:
        log("Could not open PIT, aborting pass.")
        return 0, 0

    total_succeeded = 0
    total_failed = 0
    search_after = None
    batch_count = 0

    try:
        while True:
            # Query for failed docs
            query = {
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
                "sort": [{"_shard_doc": "asc"}],
                "pit": {
                    "id": pit_id,
                    "keep_alive": PIT_KEEP_ALIVE,
                },
                "_source": ["name", "description", "driver_title", "embedding_status"],
            }

            if search_after is not None:
                query["search_after"] = search_after

            # Execute search
            url = f"{OPENSEARCH_HOST}/_search"
            try:
                r = os_session.post(url, data=json.dumps(query), timeout=READ_TIMEOUT)
                r.raise_for_status()
            except Exception as e:
                log(f"Search in PIT failed: {e}")
                break

            data = r.json()
            hits = data.get("hits", {}).get("hits", [])
            
            if not hits:
                break

            # Update search_after for next page
            search_after = hits[-1].get("sort")

            # Process documents in smaller batches
            batch_texts: List[str] = []
            batch_meta: List[Dict[str, Any]] = []

            for hit in hits:
                _id = hit.get("_id")
                src = hit.get("_source", {})

                text = build_text_for_doc(src)
                if not text.strip():
                    # Nothing to embed, mark as fatal
                    _, failed = bulk_update_vectors([{"_id": _id, "vector": None, "status": "fatal"}])
                    total_failed += failed
                    continue

                batch_texts.append(text)
                batch_meta.append({"_id": _id})

                # Process batch when it reaches BATCH_SIZE
                if len(batch_texts) >= BATCH_SIZE:
                    batch_count += 1
                    log(f"Processing batch {batch_count} ({len(batch_texts)} docs)...")
                    
                    succeeded, failed = process_batch_with_rate_limit(batch_texts, batch_meta, progress)
                    total_succeeded += succeeded
                    total_failed += failed
                    
                    progress["total_processed"] += len(batch_texts)
                    progress["total_succeeded"] += succeeded
                    progress["total_failed"] += failed
                    save_progress(progress)
                    
                    log(f"  ✓ {succeeded} succeeded, ✗ {failed} failed")
                    
                    batch_texts = []
                    batch_meta = []

            # Process remaining docs in batch
            if batch_texts:
                batch_count += 1
                log(f"Processing final batch {batch_count} ({len(batch_texts)} docs)...")
                
                succeeded, failed = process_batch_with_rate_limit(batch_texts, batch_meta, progress)
                total_succeeded += succeeded
                total_failed += failed
                
                progress["total_processed"] += len(batch_texts)
                progress["total_succeeded"] += succeeded
                progress["total_failed"] += failed
                save_progress(progress)
                
                log(f"  ✓ {succeeded} succeeded, ✗ {failed} failed")

        return total_succeeded, total_failed

    finally:
        close_pit(pit_id)


def main():
    """Main execution loop."""
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    log("=" * 70)
    log("Re-embed Failed Documents Script")
    log("=" * 70)
    log(f"Index: {INDEX_NAME}")
    log(f"OpenSearch: {OPENSEARCH_HOST}")
    log(f"Ollama: {OLLAMA_HOST} (model: {OLLAMA_MODEL})")
    log(f"Scroll size: {SCROLL_SIZE}, Batch size: {BATCH_SIZE}")
    log(f"Sleep between batches: {SLEEP_BETWEEN_BATCHES}s")
    log(f"Max connections: {MAX_CONNECTIONS}")
    log(f"Progress file: {PROGRESS_FILE}")
    log("=" * 70)

    progress = load_progress()
    
    if progress.get("total_processed", 0) > 0:
        log(f"Resuming from previous session:")
        log(f"  Total processed: {progress['total_processed']}")
        log(f"  Total succeeded: {progress['total_succeeded']}")
        log(f"  Total failed: {progress['total_failed']}")
        log(f"  Passes completed: {progress.get('passes', 0)}")
        log(f"  Started at: {progress.get('started_at')}")

    pass_num = progress.get("passes", 0)
    
    while True:
        pass_num += 1
        remaining = get_failed_docs_count()
        
        log("")
        log(f"{'='*70}")
        log(f"Pass #{pass_num}")
        log(f"Documents remaining (failed or missing vector): {remaining}")
        log(f"{'='*70}")

        if remaining == 0:
            log("")
            log("🎉 All documents processed successfully!")
            log(f"Session stats:")
            log(f"  Total processed: {progress['total_processed']}")
            log(f"  Total succeeded: {progress['total_succeeded']}")
            log(f"  Total failed: {progress['total_failed']}")
            break

        succeeded, failed = process_one_pass(progress)
        progress["passes"] = pass_num
        save_progress(progress)
        
        log("")
        log(f"Pass #{pass_num} completed:")
        log(f"  ✓ Succeeded: {succeeded}")
        log(f"  ✗ Failed: {failed}")
        log(f"  Session total: {progress['total_succeeded']} succeeded, {progress['total_failed']} failed")

        if succeeded == 0 and failed == 0:
            log("No documents processed in this pass.")
            log("Checking if only 'fatal' status docs remain...")
            
            # Check for fatal-only docs
            url = f"{OPENSEARCH_HOST}/{INDEX_NAME}/_count"
            query = {"query": {"term": {"embedding_status": "fatal"}}}
            try:
                r = os_session.get(url, data=json.dumps(query), timeout=30)
                fatal_count = r.json().get("count", 0)
                log(f"Documents with 'fatal' status: {fatal_count}")
            except:
                pass
            
            break

        log(f"Sleeping {SLEEP_BETWEEN_PASSES}s before next pass...")
        time.sleep(SLEEP_BETWEEN_PASSES)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n\nScript interrupted by user. Progress has been saved.")
        sys.exit(0)
    except Exception as e:
        log(f"\n\nFatal error: {e}")
        traceback.print_exc()
        sys.exit(1)
