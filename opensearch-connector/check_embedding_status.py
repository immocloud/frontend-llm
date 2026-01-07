#!/usr/bin/env python3
"""
Quick script to check the status of document embeddings in the index.
"""
import os
import json
import requests
from datetime import datetime

# Configuration
OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "https://192.168.80.199:9200")
OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER", "admin")
OPENSEARCH_PASS = os.environ.get("OPENSEARCH_PASS", "FaraParole69")
INDEX_NAME = os.environ.get("INDEX_NAME", "real-estate-bge-v2")
VERIFY_TLS = False

def get_count(query):
    """Get count for a specific query."""
    url = f"{OPENSEARCH_HOST}/{INDEX_NAME}/_count"
    try:
        r = requests.get(
            url,
            data=json.dumps(query),
            auth=(OPENSEARCH_USER, OPENSEARCH_PASS),
            verify=VERIFY_TLS,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        r.raise_for_status()
        return r.json().get("count", 0)
    except Exception as e:
        print(f"Error: {e}")
        return None

def main():
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except:
        pass

    print("=" * 70)
    print(f"Embedding Status Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print(f"Index: {INDEX_NAME}")
    print(f"Host: {OPENSEARCH_HOST}")
    print()

    # Total documents
    total = get_count({"query": {"match_all": {}}})
    print(f"Total documents: {total:,}")
    print()

    # By status
    print("By embedding_status field:")
    
    for status in ["success", "failed", "fatal"]:
        count = get_count({"query": {"term": {"embedding_status": status}}})
        if count is not None:
            pct = (count / total * 100) if total else 0
            print(f"  {status:10s}: {count:6,} ({pct:5.1f}%)")
    
    # Missing status field
    missing_status = get_count({"query": {"bool": {"must_not": {"exists": {"field": "embedding_status"}}}}})
    if missing_status is not None and missing_status > 0:
        pct = (missing_status / total * 100) if total else 0
        print(f"  {'<missing>':10s}: {missing_status:6,} ({pct:5.1f}%)")
    
    print()
    
    # Has vector vs doesn't have vector
    print("By listing_vector presence:")
    has_vector = get_count({"query": {"exists": {"field": "listing_vector"}}})
    missing_vector = get_count({"query": {"bool": {"must_not": {"exists": {"field": "listing_vector"}}}}})
    
    if has_vector is not None:
        pct = (has_vector / total * 100) if total else 0
        print(f"  Has vector:     {has_vector:6,} ({pct:5.1f}%)")
    
    if missing_vector is not None:
        pct = (missing_vector / total * 100) if total else 0
        print(f"  Missing vector: {missing_vector:6,} ({pct:5.1f}%)")
    
    print()
    
    # Documents needing re-embedding (failed OR missing vector)
    needs_embedding = get_count({
        "query": {
            "bool": {
                "should": [
                    {"term": {"embedding_status": "failed"}},
                    {"bool": {"must_not": {"exists": {"field": "listing_vector"}}}},
                ],
                "minimum_should_match": 1,
            }
        }
    })
    
    if needs_embedding is not None:
        pct = (needs_embedding / total * 100) if total else 0
        print(f"🔄 Documents needing re-embedding: {needs_embedding:,} ({pct:.1f}%)")
    
    # Fatal documents
    fatal = get_count({"query": {"term": {"embedding_status": "fatal"}}})
    if fatal and fatal > 0:
        print(f"⚠️  Documents marked as fatal: {fatal:,}")
    
    print()
    
    # Check progress file if it exists
    progress_file = os.environ.get("PROGRESS_FILE", "re_embed_progress.json")
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r') as f:
                progress = json.load(f)
            
            print("Re-embedding progress:")
            print(f"  Started: {progress.get('started_at', 'N/A')}")
            print(f"  Last updated: {progress.get('last_updated', 'N/A')}")
            print(f"  Passes completed: {progress.get('passes', 0)}")
            print(f"  Documents processed: {progress.get('total_processed', 0):,}")
            print(f"  Succeeded: {progress.get('total_succeeded', 0):,}")
            print(f"  Failed: {progress.get('total_failed', 0):,}")
            
            if progress.get('total_processed', 0) > 0:
                success_rate = progress.get('total_succeeded', 0) / progress.get('total_processed', 1) * 100
                print(f"  Success rate: {success_rate:.1f}%")
            print()
        except Exception as e:
            pass
    
    print("=" * 70)

if __name__ == "__main__":
    main()
