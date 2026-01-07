#!/usr/bin/env python3
"""
Create the agents index in OpenSearch for MVP agent detection.

This is a simple lookup table of known agent phone numbers.
Cross-index lookup happens at search time to flag results.

Usage:
    python create_agents_index.py
"""

import requests
from requests.auth import HTTPBasicAuth

# OpenSearch config
OPENSEARCH_HOST = "https://192.168.80.199:9200"
OPENSEARCH_AUTH = HTTPBasicAuth("admin", "FaraParole69")
VERIFY_SSL = False

INDEX_NAME = "agents"

# Index mapping
MAPPING = {
    "mappings": {
        "properties": {
            "phone": { 
                "type": "keyword" 
            },
            "type": { 
                "type": "keyword"  # agent, agency, developer
            },
            "agency_name": { 
                "type": "text",
                "fields": {
                    "keyword": { "type": "keyword" }
                }
            },
            "source": { 
                "type": "keyword"  # scraped, manual
            },
            "scraped_at": { 
                "type": "date" 
            },
            "ad_count": { 
                "type": "integer" 
            },
            "confidence": {
                "type": "float"
            }
        }
    },
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0
    }
}


def create_index():
    """Create the agents index"""
    
    # Check if exists
    response = requests.head(
        f"{OPENSEARCH_HOST}/{INDEX_NAME}",
        auth=OPENSEARCH_AUTH,
        verify=VERIFY_SSL
    )
    
    if response.status_code == 200:
        print(f"Index '{INDEX_NAME}' already exists")
        return
    
    # Create index
    response = requests.put(
        f"{OPENSEARCH_HOST}/{INDEX_NAME}",
        json=MAPPING,
        auth=OPENSEARCH_AUTH,
        verify=VERIFY_SSL
    )
    
    if response.status_code == 200:
        print(f"✅ Created index '{INDEX_NAME}'")
    else:
        print(f"❌ Failed to create index: {response.text}")


def bulk_insert_agents(agents: list):
    """Bulk insert agents into the index"""
    
    if not agents:
        print("No agents to insert")
        return
    
    # Build bulk request body
    bulk_body = ""
    for agent in agents:
        phone = agent['phone']
        bulk_body += f'{{"index": {{"_id": "{phone}"}}}}\n'
        bulk_body += f'{{"phone": "{phone}", "type": "{agent.get("type", "agent")}", '
        bulk_body += f'"agency_name": "{agent.get("agency_name", "")}", '
        bulk_body += f'"source": "{agent.get("source", "manual")}", '
        bulk_body += f'"ad_count": {agent.get("ad_count", 0)}}}\n'
    
    response = requests.post(
        f"{OPENSEARCH_HOST}/{INDEX_NAME}/_bulk",
        data=bulk_body,
        headers={"Content-Type": "application/x-ndjson"},
        auth=OPENSEARCH_AUTH,
        verify=VERIFY_SSL
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Inserted {len(agents)} agents (errors: {result.get('errors', False)})")
    else:
        print(f"❌ Bulk insert failed: {response.text}")


def count_agents():
    """Count agents in the index"""
    response = requests.get(
        f"{OPENSEARCH_HOST}/{INDEX_NAME}/_count",
        auth=OPENSEARCH_AUTH,
        verify=VERIFY_SSL
    )
    
    if response.status_code == 200:
        count = response.json()['count']
        print(f"📊 Total agents in index: {count}")
        return count
    return 0


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings()
    
    print("=" * 50)
    print("Creating Agents Index for MVP")
    print("=" * 50)
    
    create_index()
    count_agents()
    
    print("\n" + "=" * 50)
    print("To insert agents, use:")
    print("=" * 50)
    print("""
from create_agents_index import bulk_insert_agents

agents = [
    {"phone": "0722123456", "type": "agent", "agency_name": "Imobiliare XYZ"},
    {"phone": "0733987654", "type": "agency", "agency_name": "RE/MAX Romania"},
]

bulk_insert_agents(agents)
""")
