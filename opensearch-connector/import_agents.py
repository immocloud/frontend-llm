#!/usr/bin/env python3
import requests
import json

OPENSEARCH_URL = "https://192.168.80.199:9200"
OPENSEARCH_AUTH = ("admin", "FaraParole69")

# Create index with mapping
mapping = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0
    },
    "mappings": {
        "properties": {
            "phone": {"type": "keyword"},
            "type": {"type": "keyword"},
            "agency_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "listing_count": {"type": "integer"},
            "last_updated": {"type": "date"}
        }
    }
}

print("Creating agents index...")
r = requests.put(
    f"{OPENSEARCH_URL}/agents",
    json=mapping,
    auth=OPENSEARCH_AUTH,
    verify=False
)
print(f"Status: {r.status_code}")

# Your dev data dump from the file
agents_data = {
    "0722825870": {"phone": "0722825870", "type": "agency", "agency_name": "Consultant Imobiliar", "listing_count": 43, "last_updated": "2025-12-12T12:28:18.170067"},
    "0744863386": {"phone": "0744863386", "type": "agency", "agency_name": "AM", "listing_count": 43, "last_updated": "2025-12-12T12:28:18.220608"},
    "0723232359": {"phone": "0723232359", "type": "agency", "agency_name": "Gabriel Andrei", "listing_count": 42, "last_updated": "2025-12-12T12:28:18.262012"},
    # ... I'll parse all from the dump
}

# Build bulk request from the dump you provided
print("\nParsing dump and building bulk request...")

# I'll write a proper importer - let me get ALL the data from your dump first
