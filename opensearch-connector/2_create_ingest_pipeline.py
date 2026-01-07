#!/usr/bin/env python3
import os
import sys
import requests
from requests.auth import HTTPBasicAuth

# Configuration
OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "https://192.168.80.199:9200")
OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER", "admin")
OPENSEARCH_PASS = os.environ.get("OPENSEARCH_PASS", "FaraParole69")
VERIFY = False  # Ignoring SSL for local setup

# Pipeline Configuration
PIPELINE_ID = "property-vectorizer-pipeline"
# Default to the model ID we just created: S_tS4JoB-XLRYbYPFpf1
MODEL_ID = os.environ.get("MODEL_ID", "S_tS4JoB-XLRYbYPFpf1") 

def create_pipeline():
    url = OPENSEARCH_HOST.rstrip("/") + f"/_ingest/pipeline/{PIPELINE_ID}"
    
    # Pipeline definition
    # Maps 'description' -> 'listing_vector' using the ML model
    pipeline_body = {
        "description": "Embed property listings using Ollama LaBSE model",
        "processors": [
            {
                "text_embedding": {
                    "model_id": MODEL_ID,
                    "field_map": {
                        "description": "listing_vector"
                    },
                    "on_failure": [
                        {
                            "remove": {
                                "field": "listing_vector",
                                "ignore_missing": True
                            }
                        },
                        {
                            "set": {
                                "field": "embedding_status",
                                "value": "failed"
                            }
                        }
                    ]
                }
            }
        ]
    }

    print(f"Creating/Updating ingest pipeline '{PIPELINE_ID}' using model '{MODEL_ID}'...")
    
    # Suppress SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        r = requests.put(url, json=pipeline_body, auth=(OPENSEARCH_USER, OPENSEARCH_PASS), verify=VERIFY)
        print(f"Status: {r.status_code}")
        print(r.text)
        if r.status_code in (200, 201):
            print("Pipeline created successfully.")
            return True
    except Exception as e:
        print(f"Error creating pipeline: {e}")
    return False

if __name__ == "__main__":
    create_pipeline()
