#!/usr/bin/env python3
import os
import requests
import time

# Configuration
OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "https://192.168.80.199:9200")
OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER", "admin")
OPENSEARCH_PASS = os.environ.get("OPENSEARCH_PASS", "FaraParole69")
VERIFY = False

SOURCE_INDEX = "real-estate-2026.01.04"
DEST_INDEX = "real-estate-2026.01.04-v2"

def reindex():
    url = f"{OPENSEARCH_HOST}/_reindex"
    
    reindex_body = {
        "source": {
            "index": SOURCE_INDEX
        },
        "dest": {
            "index": DEST_INDEX,
            "pipeline": "property-vectorizer-pipeline"
        }
    }
    
    print(f"Starting reindex from '{SOURCE_INDEX}' to '{DEST_INDEX}'...")
    print("This will apply the vectorizer pipeline to generate embeddings...")
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    try:
        r = requests.post(
            url, 
            json=reindex_body, 
            auth=(OPENSEARCH_USER, OPENSEARCH_PASS), 
            verify=VERIFY,
            params={"wait_for_completion": "false"}
        )
        print(f"Status: {r.status_code}")
        response = r.json()
        print(f"Response: {response}")
        
        if r.status_code in (200, 201):
            task_id = response.get("task")
            if task_id:
                print(f"\n✅ Reindex task started: {task_id}")
                print(f"\nMonitoring progress...")
                monitor_task(task_id)
            return True
    except Exception as e:
        print(f"❌ Error during reindex: {e}")
    return False

def monitor_task(task_id):
    url = f"{OPENSEARCH_HOST}/_tasks/{task_id}"
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    while True:
        try:
            r = requests.get(url, auth=(OPENSEARCH_USER, OPENSEARCH_PASS), verify=VERIFY)
            data = r.json()
            
            if data.get("completed"):
                print("\n✅ Reindex completed!")
                print(f"Total: {data.get('task', {}).get('status', {}).get('total', 0)}")
                print(f"Created: {data.get('task', {}).get('status', {}).get('created', 0)}")
                print(f"Updated: {data.get('task', {}).get('status', {}).get('updated', 0)}")
                
                # Delete old index and create alias
                print(f"\nDeleting old index '{SOURCE_INDEX}'...")
                delete_url = f"{OPENSEARCH_HOST}/{SOURCE_INDEX}"
                requests.delete(delete_url, auth=(OPENSEARCH_USER, OPENSEARCH_PASS), verify=VERIFY)
                
                print(f"Creating alias '{SOURCE_INDEX}' -> '{DEST_INDEX}'...")
                alias_url = f"{OPENSEARCH_HOST}/_aliases"
                alias_body = {
                    "actions": [
                        {"add": {"index": DEST_INDEX, "alias": SOURCE_INDEX}}
                    ]
                }
                requests.post(alias_url, json=alias_body, auth=(OPENSEARCH_USER, OPENSEARCH_PASS), verify=VERIFY)
                print("✅ Alias created. All queries to old index name will work!")
                break
            else:
                status = data.get("task", {}).get("status", {})
                total = status.get("total", 0)
                created = status.get("created", 0)
                print(f"Progress: {created}/{total} documents processed...", end="\r")
                time.sleep(2)
        except Exception as e:
            print(f"\n❌ Error monitoring task: {e}")
            break

if __name__ == "__main__":
    reindex()
