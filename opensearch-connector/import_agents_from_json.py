#!/usr/bin/env python3
import json
import requests
from requests.auth import HTTPBasicAuth

# Read the dev export data
with open('dev_agents_export.json', 'r') as f:
    data = json.load(f)

# OpenSearch connection
OPENSEARCH_HOST = "https://192.168.80.199:9200"
USERNAME = "admin"
PASSWORD = "FaraParole69"

# Prepare bulk data
bulk_data = []
for hit in data['hits']['hits']:
    # Index action
    bulk_data.append(json.dumps({
        "index": {
            "_index": "agents",
            "_id": hit['_id']
        }
    }))
    # Document source
    bulk_data.append(json.dumps(hit['_source']))

# Join with newlines and add final newline
bulk_payload = '\n'.join(bulk_data) + '\n'

# Send bulk request
response = requests.post(
    f"{OPENSEARCH_HOST}/_bulk",
    headers={'Content-Type': 'application/x-ndjson'},
    data=bulk_payload,
    auth=HTTPBasicAuth(USERNAME, PASSWORD),
    verify=False
)

print(f"Status: {response.status_code}")
result = response.json()
print(f"Took: {result.get('took')}ms")
print(f"Errors: {result.get('errors')}")

if result.get('errors'):
    # Show first few errors
    for item in result.get('items', [])[:5]:
        if 'error' in item.get('index', {}):
            print(f"Error: {item['index']['error']}")
else:
    print(f"Successfully imported {len(data['hits']['hits'])} agents")
