#!/usr/bin/env python3
import os
import json
import sys
import requests
from requests.auth import HTTPBasicAuth

# Configuration
OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "https://192.168.80.199:9200")
OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER", "admin")
OPENSEARCH_PASS = os.environ.get("OPENSEARCH_PASS", "FaraParole69")
VERIFY = False  # User requested to ignore SSL verification issues implicitly by context

# Ollama details (updated to BGE-M3 on 80.197)
OLLAMA_ENDPOINT = "http://192.168.80.197:11434"
OLLAMA_MODEL = "bge-m3"

CONNECTOR_NAME = "bge-m3-embedding"
MODEL_NAME = "bge_m3_embedding_model"

def create_connector():
    url = OPENSEARCH_HOST.rstrip("/") + "/_plugins/_ml/connectors/_create"
    body = {
        "name": CONNECTOR_NAME,
        "description": "Ollama BGE-M3 embedding connector",
        "version": "1",
        "protocol": "http",
        "parameters": {
            "endpoint": OLLAMA_ENDPOINT,
            "model": OLLAMA_MODEL
        },
        "credential": {
            "openAI_key": "dummy"
        },
        "actions": [
            {
                "action_type": "PREDICT",
                "method": "POST",
                "url": "${parameters.endpoint}/v1/embeddings",
                "headers": {
                    "Content-Type": "application/json"
                },
                "request_body": "{ \"input\": ${parameters.input}, \"model\": \"${parameters.model}\" }",
                "pre_process_function": "connector.pre_process.openai.embedding",
                "post_process_function": "connector.post_process.openai.embedding"
            }
        ],
        "client_config": {
            "max_connection": 100,
            "connection_timeout": 30000,
            "read_timeout": 30000,
            "retry_backoff_millis": 200,
            "retry_timeout_seconds": 30,
            "max_retry_times": 0,
            "retry_backoff_policy": "constant"
        }
    }
    
    print(f"Creating connector '{CONNECTOR_NAME}'...")
    try:
        r = requests.post(url, json=body, auth=(OPENSEARCH_USER, OPENSEARCH_PASS), verify=VERIFY)
        print(f"Status: {r.status_code}")
        print(r.text)
        if r.status_code in (200, 201):
            return r.json().get("connector_id")
    except Exception as e:
        print(f"Error creating connector: {e}")
    return None

def create_model(connector_id):
    # Try _register first as it is standard for remote models in newer versions
    url = OPENSEARCH_HOST.rstrip("/") + "/_plugins/_ml/models/_register"
    body = {
        "name": MODEL_NAME,
        "function_name": "remote",
        "description": "Embedding model via BGE-M3 on Ollama",
        "connector_id": connector_id
    }
    
    print(f"Creating/Registering model '{MODEL_NAME}' with connector_id={connector_id}...")
    try:
        r = requests.post(url, json=body, auth=(OPENSEARCH_USER, OPENSEARCH_PASS), verify=VERIFY)
        if r.status_code == 404:
             # Fallback to _create if _register is not found (older versions)
             url = OPENSEARCH_HOST.rstrip("/") + "/_plugins/_ml/models/_create"
             r = requests.post(url, json=body, auth=(OPENSEARCH_USER, OPENSEARCH_PASS), verify=VERIFY)

        print(f"Status: {r.status_code}")
        print(r.text)
        if r.status_code in (200, 201):
            return r.json().get("model_id")
    except Exception as e:
        print(f"Error creating model: {e}")
    return None

def deploy_model(model_id):
    url = OPENSEARCH_HOST.rstrip("/") + f"/_plugins/_ml/models/{model_id}/_deploy"
    print(f"Deploying model '{model_id}'...")
    try:
        r = requests.post(url, auth=(OPENSEARCH_USER, OPENSEARCH_PASS), verify=VERIFY)
        print(f"Status: {r.status_code}")
        print(r.text)
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"Error deploying model: {e}")
    return False

def update_pipeline(model_id):
    """Update the ingest pipeline to use the new BGE-M3 model and tidy failure flags."""
    pipeline_name = "property-vectorizer-pipeline"
    url = f"{OPENSEARCH_HOST.rstrip('/')}/_ingest/pipeline/{pipeline_name}"
    body = {
        "description": "Embed property listings using BGE-M3, clear failure flags on success",
        "processors": [
            {
                "text_embedding": {
                    "model_id": model_id,
                    "field_map": { "description": "listing_vector" },
                    "on_failure": [
                        { "remove": { "field": "listing_vector", "ignore_missing": True } },
                        { "set": { "field": "embedding_status", "value": "failed" } },
                        { "set": { "field": "failure_message", "value": "{{ _ingest.on_failure_message }}" } }
                    ]
                }
            },
            { "remove": { "if": "ctx.listing_vector != null", "field": ["embedding_status", "failure_message"], "ignore_missing": True } }
        ]
    }

    print(f"Updating pipeline '{pipeline_name}' to model_id={model_id}...")
    try:
        r = requests.put(url, json=body, auth=(OPENSEARCH_USER, OPENSEARCH_PASS), verify=VERIFY)
        print(f"Status: {r.status_code}")
        print(r.text)
        return r.status_code == 200
    except Exception as e:
        print(f"Error updating pipeline: {e}")
        return False

def main():
    # Suppress SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    connector_id = create_connector()
    if not connector_id:
        print("Failed to create connector. Exiting.")
        sys.exit(1)
        
    model_id = create_model(connector_id)
    if not model_id:
        print("Failed to create model. Exiting.")
        sys.exit(1)

    # Deploy the model so it can be used
    if not deploy_model(model_id):
        print("Model deploy failed.")
        sys.exit(1)

    # Update pipeline to point to the new model
    if not update_pipeline(model_id):
        print("Pipeline update failed.")
        sys.exit(1)

    print("Connector, model, and pipeline updated for BGE-M3.")

if __name__ == "__main__":
    main()
