#!/usr/bin/env python3
import os
import requests
from requests.auth import HTTPBasicAuth

# Configuration
OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "https://192.168.80.199:9200")
OPENSEARCH_USER = os.environ.get("OPENSEARCH_USER", "admin")
OPENSEARCH_PASS = os.environ.get("OPENSEARCH_PASS", "FaraParole69")
VERIFY = False

TEMPLATE_NAME = "real-estate-template"
INDEX_PATTERN = "real-estate-*"

def create_index_template():
    url = f"{OPENSEARCH_HOST}/_index_template/{TEMPLATE_NAME}"
    
    template_body = {
        "index_patterns": [INDEX_PATTERN],
        "template": {
            "settings": {
                "index": {
                    "mapping": {
                        "total_fields": {
                            "limit": "2000"
                        }
                    },
                    "refresh_interval": "30s",
                    "number_of_shards": "2",
                    "default_pipeline": "property-vectorizer-pipeline",
                    "knn": "true",
                    "analysis": {
                        "filter": {
                            "romanian_snowball": {
                                "type": "snowball",
                                "language": "Romanian"
                            },
                            "romanian_stop": {
                                "type": "stop",
                                "stopwords": "_romanian_"
                            }
                        },
                        "analyzer": {
                            "ro_analyzer": {
                                "filter": [
                                    "lowercase",
                                    "asciifolding",
                                    "romanian_stop",
                                    "romanian_snowball"
                                ],
                                "tokenizer": "standard"
                            }
                        }
                    },
                    "number_of_replicas": "1"
                }
            },
            "mappings": {
                "dynamic_templates": [
                    {
                        "disable_dynamic_attrs": {
                            "path_match": "attributes.*",
                            "mapping": {
                                "type": "object",
                                "enabled": False
                            }
                        }
                    }
                ],
                "properties": {
                    "location_1": {"type": "keyword"},
                    "geo_location": {"type": "geo_point"},
                    "visible": {"type": "boolean"},
                    "valid_from": {"type": "date"},
                    "description": {
                        "analyzer": "ro_analyzer",
                        "type": "text"
                    },
                    "location_2": {"type": "keyword"},
                    "location_3": {"type": "keyword"},
                    "driver_title": {
                        "analyzer": "ro_analyzer",
                        "type": "text"
                    },
                    "price": {"type": "long"},
                    "name": {
                        "analyzer": "ro_analyzer",
                        "type": "text"
                    },
                    "listing_vector": {
                        "type": "knn_vector",
                        "dimension": 1024
                    },
                    "processed_at": {"type": "date"},
                    "currency": {"type": "keyword"},
                    "attributes": {
                        "type": "object",
                        "enabled": False
                    },
                    "categories": {"type": "keyword"},
                    "image_tags": {"type": "keyword"}
                }
            }
        }
    }
    
    print(f"Creating index template '{TEMPLATE_NAME}' for pattern '{INDEX_PATTERN}'...")
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    try:
        r = requests.put(url, json=template_body, auth=(OPENSEARCH_USER, OPENSEARCH_PASS), verify=VERIFY)
        print(f"Status: {r.status_code}")
        print(r.text)
        if r.status_code in (200, 201):
            print("✅ Index template created successfully.")
            print(f"\nNext steps:")
            print(f"1. New indices matching '{INDEX_PATTERN}' will use this template automatically")
            print(f"2. Existing indices need to be reindexed to get the vector field")
            return True
    except Exception as e:
        print(f"❌ Error creating template: {e}")
    return False

if __name__ == "__main__":
    create_index_template()
