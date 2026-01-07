import os
import json
import requests
import warnings

# Suppress warnings
warnings.filterwarnings("ignore")

# Configuration
OPENSEARCH_URL = "https://192.168.80.199:9200"
AUTH = ("admin", "FaraParole69")
INDEX_PATTERN = "real-estate-*"
BATCH_SIZE = 500

def normalize_phone(phone):
    """Normalize phone number: digits only, handle 000000/empty."""
    if not phone:
        return None
    
    # Remove all non-digit characters
    cleaned = ''.join(filter(str.isdigit, str(phone)))
    
    # Check for invalid values
    if not cleaned or cleaned == '000000' or len(cleaned) < 3:
         return None
         
    return cleaned

def normalize_phones_task():
    print(f"Connecting to OpenSearch at {OPENSEARCH_URL} via requests...")
    
    session = requests.Session()
    session.auth = AUTH
    session.verify = False
    
    # 1. Initial Search (Scroll)
    query = {
        "size": BATCH_SIZE,
        "_source": ["decrypted_phone"],
        "query": {
            "exists": {"field": "decrypted_phone"}
        }
    }
    
    try:
        resp = session.post(
            f"{OPENSEARCH_URL}/{INDEX_PATTERN}/_search?scroll=5m",
            json=query,
            headers={"Content-Type": "application/json"}
        )
        resp.raise_for_status()
        data = resp.json()
        
        scroll_id = data.get("_scroll_id")
        hits = data["hits"]["hits"]
        total = data["hits"]["total"]["value"]
        
        print(f"Found {total} documents to scan.")
    except Exception as e:
        print(f"Initial search failed: {e}")
        return

    processed_count = 0
    updated_count = 0
    
    actions = []

    while hits and scroll_id:
        for doc in hits:
            doc_id = doc["_id"]
            index = doc["_index"]
            original_phone = doc["_source"].get("decrypted_phone")
            
            normalized = normalize_phone(original_phone)
            
            # Determine if update is needed
            if normalized != original_phone:
                new_val = normalized if normalized else "N/A"
                
                # Prepare bulk action (update)
                # Bulk format:
                # { "update": { "_id": "1", "_index": "index1" } }
                # { "doc": { "field1": "value1" } }
                
                action_meta = json.dumps({
                    "update": {
                        "_id": doc_id,
                        "_index": index
                    }
                })
                action_doc = json.dumps({
                    "doc": {
                        "decrypted_phone": new_val
                    }
                })
                actions.append(f"{action_meta}\n{action_doc}")
                updated_count += 1
            
            processed_count += 1
        
        # Flush batch
        if len(actions) >= (BATCH_SIZE / 2): # Bulk operations count as 2 lines per doc
             bulk_body = "\n".join(actions) + "\n"
             try:
                 bulk_resp = session.post(
                     f"{OPENSEARCH_URL}/_bulk",
                     data=bulk_body,
                     headers={"Content-Type": "application/json"}
                 )
                 bulk_resp.raise_for_status()
                 if bulk_resp.json().get("errors"):
                     print(f"Bulk update had errors: {bulk_resp.text[:200]}")
             except Exception as e:
                 print(f"Bulk update failed: {e}")
             
             print(f"Processed {processed_count}/{total} docs, queued {updated_count} updates...")
             actions = []

        # Get next batch
        try:
            resp = session.post(
                f"{OPENSEARCH_URL}/_search/scroll",
                json={"scroll": "5m", "scroll_id": scroll_id},
                headers={"Content-Type": "application/json"}
            )
            resp.raise_for_status()
            data = resp.json()
            scroll_id = data.get("_scroll_id")
            hits = data["hits"]["hits"]
            
            if not hits:
                break
                
        except Exception as e:
            print(f"Scroll failed: {e}")
            break

    # Final batch flush
    if actions:
        bulk_body = "\n".join(actions) + "\n"
        try:
             bulk_resp = session.post(
                 f"{OPENSEARCH_URL}/_bulk",
                 data=bulk_body,
                 headers={"Content-Type": "application/json"}
             )
             bulk_resp.raise_for_status()
        except Exception as e:
             print(f"Final bulk update failed: {e}")

    # Clear scroll context
    try:
        session.delete(
            f"{OPENSEARCH_URL}/_search/scroll",
            json={"scroll_id": [scroll_id]},
            headers={"Content-Type": "application/json"}
        )
    except:
        pass

    print(f"Done! Processed: {processed_count}, Updated: {updated_count}")

if __name__ == "__main__":
    normalize_phones_task()
