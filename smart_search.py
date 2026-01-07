# smart_search.py - LLM query parser + OpenSearch hybrid search
# Solid version with proper validation and edge case handling

import json
import re
import httpx
import requests
import unicodedata
import uuid
from datetime import datetime, timezone
from urllib3.exceptions import InsecureRequestWarning
from copy import deepcopy
from typing import Optional, Dict, Any, List

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# =============================================================================
# CONFIGURATION
# =============================================================================

OLLAMA_URL = "http://192.168.10.115:11434"
OLLAMA_MODEL = "gpt-oss:20b-cloud"
OPENSEARCH_URL = "https://192.168.80.199:9200"
OPENSEARCH_AUTH = ("admin", "FaraParole69")
INDEX_PATTERN = "real-estate-*"
EMBEDDING_MODEL_ID = "RP2W5ZoB-XLRYbYP-LKJ"

# Conversation memory index (with DLS)
MEMORY_INDEX = "search-conversations"

# Valid values from the actual data
VALID_TRANSACTIONS = ["Vanzare", "Inchiriere"]
VALID_PROPERTY_TYPES = ["Apartamente", "Case", "Garsoniera", "Terenuri", "Vile", "Spatii", "Birou"]
VALID_ROOMS = [1, 2, 3, 4, 5]

# Major cities in Romania (as they appear in location_1)
KNOWN_CITIES = {
    "bucuresti": "Bucuresti",
    "bucharest": "Bucuresti",
    "timisoara": "Timis",
    "cluj": "Cluj",
    "cluj-napoca": "Cluj",
    "iasi": "Iasi",
    "constanta": "Constanta",
    "brasov": "Brasov",
    "sibiu": "Sibiu",
    "oradea": "Bihor",
    "craiova": "Dolj",
    "arad": "Arad",
    "ploiesti": "Prahova",
}

# =============================================================================
# FEATURE PATTERNS - Real phrases from the dataset
# =============================================================================

FEATURE_PATTERNS = {
    "animale": {
        "positive_boost": "accepta animale pet friendly pisici caini animale de companie se accepta animal",
        "negative_patterns": [
            # Exact phrases found in data
            "nu se accepta animale",
            "nu se acceptă animale",
            "nu accept animale",
            "nu accepta animale",
            "nu acceptam animale",
            "fara animale",
            "fără animale",
            "exclus animale",
            # Compound phrases
            "nu se accepta animale de companie",
            "nu accept animale de companie",
            "nu sunt acceptate animale",
            "nu se acceptă animale de companie",
        ]
    },
    "fumatori": {
        "positive_boost": "fumatori acceptati se poate fuma accept fumatori",
        "negative_patterns": [
            "nu accept fumatori",
            "nu accept fumători",
            "fara fumatori",
            "fără fumători",
            "nefumatori",
            "non fumatori",
            "nu se fumeaza",
            "interzis fumatul",
            "exclus fumatori",
            "nu fumatori",
        ]
    },
    "parcare": {
        "positive_boost": "loc parcare garaj parcare inclusa parcare subterana boxa",
        "negative_patterns": [
            "fara parcare",
            "fără parcare",
            "nu are parcare",
            "fara loc parcare",
        ]
    },
    "mobilat": {
        "positive_boost": "mobilat complet utilat mobilat modern complet mobilat",
        "negative_patterns": [
            "nemobilat",
            "neutilat",
            "fara mobila",
            "fără mobilă",
            "gol",
        ]
    },
    "centrala": {
        "positive_boost": "centrala proprie centrala termica incalzire autonoma",
        "negative_patterns": [
            "fara centrala",
            "încălzire centralizată",
        ]
    },
}

# =============================================================================
# UTILITIES
# =============================================================================

def strip_diacritics(text: str) -> str:
    """Remove Romanian diacritics: ă->a, â->a, î->i, ș->s, ț->t"""
    if not text:
        return text
    normalized = unicodedata.normalize('NFD', text)
    return ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')


def normalize_city(city: str) -> Optional[str]:
    """Normalize city name to match location_1 field values"""
    if not city:
        return None
    
    city_lower = strip_diacritics(city.lower().strip())
    
    # Direct match in known cities
    if city_lower in KNOWN_CITIES:
        return KNOWN_CITIES[city_lower]
    
    # Try without diacritics
    for key, value in KNOWN_CITIES.items():
        if strip_diacritics(key) == city_lower:
            return value
    
    # Return as-is but with proper capitalization
    return city.strip().title()


def validate_transaction(transaction: str) -> Optional[str]:
    """Validate and normalize transaction type"""
    if not transaction:
        return None
    
    t = strip_diacritics(transaction.strip().lower())
    
    if t in ["vanzare", "vand", "cumpar", "cumparare", "vânzare"]:
        return "Vanzare"
    elif t in ["inchiriere", "inchiriez", "chirie", "închiriere"]:
        return "Inchiriere"
    
    return None


def validate_property_type(prop_type: str) -> Optional[str]:
    """Validate and normalize property type"""
    if not prop_type:
        return None
    
    p = strip_diacritics(prop_type.strip().lower())
    
    if p in ["apartament", "apartamente", "ap"]:
        return "Apartamente"
    elif p in ["casa", "case", "vila", "vile"]:
        return "Case"
    elif p in ["garsoniera", "garsoniere", "studio"]:
        return "Garsoniera"
    elif p in ["teren", "terenuri"]:
        return "Terenuri"
    
    return None

# =============================================================================
# CONVERSATION MEMORY - Persistent in OpenSearch with DLS
# =============================================================================

def create_empty_memory() -> Dict[str, Any]:
    """Create a fresh memory state"""
    return {
        "location": None,
        "city": None,
        "transaction": None,
        "property_type": None,
        "rooms": None,
        "price_min": None,
        "price_max": None,
        "keywords": [],  # Arbitrary search terms: modern, balcon, televizor, etc.
        "features": {
            "animale": None,
            "fumatori": None,
            "parcare": None,
            "mobilat": None,
            "centrala": None,
        }
    }


def ensure_memory_index():
    """Create the conversation memory index with DLS-ready mapping"""
    mapping = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0
        },
        "mappings": {
            "properties": {
                "user_id": {"type": "keyword"},  # For DLS filtering
                "session_id": {"type": "keyword"},
                "filters": {"type": "object", "enabled": False},  # Store as-is
                "query_history": {"type": "text"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"}
            }
        }
    }
    
    # Check if index exists
    response = requests.head(
        f"{OPENSEARCH_URL}/{MEMORY_INDEX}",
        auth=OPENSEARCH_AUTH,
        verify=False
    )
    
    if response.status_code == 404:
        # Create index
        response = requests.put(
            f"{OPENSEARCH_URL}/{MEMORY_INDEX}",
            json=mapping,
            auth=OPENSEARCH_AUTH,
            verify=False
        )
        if response.status_code in [200, 201]:
            print(f"✅ Created memory index: {MEMORY_INDEX}")
        else:
            print(f"⚠️ Failed to create memory index: {response.text}")


def load_memory(user_id: str, session_id: str) -> Dict[str, Any]:
    """Load conversation memory from OpenSearch"""
    doc_id = f"{user_id}_{session_id}"
    
    response = requests.get(
        f"{OPENSEARCH_URL}/{MEMORY_INDEX}/_doc/{doc_id}",
        auth=OPENSEARCH_AUTH,
        verify=False
    )
    
    if response.status_code == 200:
        doc = response.json()
        return doc["_source"].get("filters", create_empty_memory())
    
    return create_empty_memory()


def save_memory(user_id: str, session_id: str, filters: Dict, query: str = None):
    """Save conversation memory to OpenSearch"""
    doc_id = f"{user_id}_{session_id}"
    now = datetime.now(timezone.utc).isoformat()
    
    # Get existing doc to append query history
    existing = requests.get(
        f"{OPENSEARCH_URL}/{MEMORY_INDEX}/_doc/{doc_id}",
        auth=OPENSEARCH_AUTH,
        verify=False
    )
    
    query_history = []
    created_at = now
    if existing.status_code == 200:
        src = existing.json()["_source"]
        query_history = src.get("query_history", [])
        created_at = src.get("created_at", now)
    
    if query:
        query_history.append({"q": query, "ts": now})
        # Keep last 50 queries
        query_history = query_history[-50:]
    
    doc = {
        "user_id": user_id,
        "session_id": session_id,
        "filters": filters,
        "query_history": query_history,
        "created_at": created_at,
        "updated_at": now
    }
    
    response = requests.put(
        f"{OPENSEARCH_URL}/{MEMORY_INDEX}/_doc/{doc_id}",
        json=doc,
        auth=OPENSEARCH_AUTH,
        verify=False
    )
    
    return response.status_code in [200, 201]


def delete_memory(user_id: str, session_id: str):
    """Delete conversation memory"""
    doc_id = f"{user_id}_{session_id}"
    requests.delete(
        f"{OPENSEARCH_URL}/{MEMORY_INDEX}/_doc/{doc_id}",
        auth=OPENSEARCH_AUTH,
        verify=False
    )


# Global memory (for CLI mode - will be replaced by user/session in API mode)
conversation_memory = create_empty_memory()
current_user_id = "cli_user"
current_session_id = str(uuid.uuid4())[:8]

# =============================================================================
# LLM PARSING
# =============================================================================

def parse_query_with_llm(user_query: str, current_context: Dict) -> Dict:
    """Use LLM to parse natural language query into structured filters"""
    
    context_str = json.dumps(current_context, ensure_ascii=False, indent=2)
    
    prompt = f'''You are a Romanian real estate search parser. Parse the user's query into structured JSON.

CURRENT SEARCH CONTEXT:
{context_str}

USER QUERY: "{user_query}"

RULES:
1. If the query REFINES the search (starts with "dar", "si", "doar", "numai"), preserve context and modify only mentioned fields
2. If the query is a NEW search (mentions a new location or completely different criteria), start fresh
3. For features (animale, fumatori, parcare, mobilat, centrala):
   - "WANT" = user wants this feature (e.g., "pet friendly", "cu parcare")  
   - "EXCLUDE" = user doesn't want this (e.g., "fara animale", "nefumatori")
   - null = not mentioned

OUTPUT FORMAT (JSON only, no explanation):
{{
  "location": "neighborhood name or null",
  "city": "city name or null",
  "transaction": "Vanzare" or "Inchiriere" or null,
  "property_type": "Apartamente" or "Case" or "Garsoniera" or null,
  "rooms": number or null,
  "price_min": number or null,
  "price_max": number or null,
  "keywords": ["array of search terms like: modern, balcon, televizor, renovat, vedere, etc."],
  "features": {{
    "animale": "WANT" or "EXCLUDE" or null,
    "fumatori": "WANT" or "EXCLUDE" or null,
    "parcare": "WANT" or "EXCLUDE" or null,
    "mobilat": "WANT" or "EXCLUDE" or null,
    "centrala": "WANT" or "EXCLUDE" or null
  }}
}}

Parse this query and output ONLY the JSON:'''

    try:
        response = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,  # Low temperature for consistent parsing
                    "num_predict": 500,
                }
            },
            timeout=30.0
        )
        
        result = response.json()["response"].strip()
        
        # Extract JSON from response
        # Handle markdown code blocks
        if "```" in result:
            match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', result)
            if match:
                result = match.group(1)
        
        # Find JSON object
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            result = result[start:end]
        
        # Clean up common JSON issues from LLM output
        result = re.sub(r',\s*}', '}', result)  # Remove trailing commas
        result = re.sub(r',\s*]', ']', result)  # Remove trailing commas in arrays
        result = result.replace('\n', ' ')  # Remove newlines that break strings
        
        parsed = json.loads(result)
        
        # Post-process and validate
        return validate_parsed_result(parsed, current_context)
        
    except Exception as e:
        print(f"LLM parsing error: {e}")
        # Return current context on error
        return current_context


def validate_parsed_result(parsed: Dict, context: Dict) -> Dict:
    """Validate and normalize LLM output"""
    
    result = deepcopy(context)  # Start with context
    
    # Update with parsed values, validating each
    if parsed.get("location"):
        result["location"] = strip_diacritics(parsed["location"])
    
    if parsed.get("city"):
        result["city"] = normalize_city(parsed["city"])
    
    if parsed.get("transaction"):
        validated = validate_transaction(parsed["transaction"])
        if validated:
            result["transaction"] = validated
    
    if parsed.get("property_type"):
        validated = validate_property_type(parsed["property_type"])
        if validated:
            result["property_type"] = validated
    
    if parsed.get("rooms") is not None:
        rooms = parsed["rooms"]
        if isinstance(rooms, int) and 1 <= rooms <= 5:
            result["rooms"] = rooms
    
    if parsed.get("price_min") is not None:
        result["price_min"] = int(parsed["price_min"]) if parsed["price_min"] else None
    
    if parsed.get("price_max") is not None:
        result["price_max"] = int(parsed["price_max"]) if parsed["price_max"] else None
    
    # Keywords - merge with existing, deduplicate
    if parsed.get("keywords"):
        existing_kw = set(result.get("keywords", []) or [])
        new_kw = set(parsed["keywords"]) if isinstance(parsed["keywords"], list) else set()
        result["keywords"] = list(existing_kw | new_kw)
    
    # Features
    if parsed.get("features"):
        for feature in ["animale", "fumatori", "parcare", "mobilat", "centrala"]:
            val = parsed["features"].get(feature)
            if val in ["WANT", "EXCLUDE"]:
                result["features"][feature] = val
            elif val is None and feature in parsed["features"]:
                result["features"][feature] = None
    
    return result

# =============================================================================
# OPENSEARCH QUERY BUILDER
# =============================================================================

def build_opensearch_query(parsed: Dict, size: int = 25) -> Dict:
    """Build OpenSearch query from parsed filters"""
    
    must = []
    should = []
    must_not = []
    
    # Location filters - search across multiple fields with fuzzy matching
    location = parsed.get("location")
    if location:
        loc_lower = location.lower()
        
        # Check if it's a sector (for Bucuresti)
        if "sector" in loc_lower:
            # Normalize sector: could be "Sector 3", "Sectorul 3", "sector 3"
            match = re.search(r'(\d+)', location)
            if match:
                sector_num = match.group(1)
                # Search both "Sector X" and "Sectorul X" variants
                must.append({
                    "bool": {
                        "should": [
                            {"term": {"location_2": f"Sector {sector_num}"}},
                            {"term": {"location_2": f"Sectorul {sector_num}"}}
                        ],
                        "minimum_should_match": 1
                    }
                })
        else:
            # It's a neighborhood - search across location_3, title, and description
            # This handles partial matches like "Pallady" matching "Theodor Pallady"
            must.append({
                "bool": {
                    "should": [
                        # Exact match on location_3 (highest priority)
                        {"term": {"location_3": {"value": location, "boost": 3.0}}},
                        # Fuzzy/partial match on location_3
                        {"match": {"location_3": {"query": location, "fuzziness": "AUTO", "boost": 2.5}}},
                        # Match in driver_title
                        {"match": {"driver_title": {"query": location, "boost": 2.0}}},
                        # Match in description
                        {"match": {"description": {"query": location, "boost": 1.0}}}
                    ],
                    "minimum_should_match": 1
                }
            })
    
    if parsed.get("city"):
        must.append({"term": {"location_1": parsed["city"]}})
    
    # Transaction type
    if parsed.get("transaction"):
        must.append({"term": {"categories": parsed["transaction"]}})
    
    # Property type
    if parsed.get("property_type"):
        must.append({"term": {"categories": parsed["property_type"]}})
    
    # Rooms
    if parsed.get("rooms"):
        rooms = parsed["rooms"]
        if rooms == 1:
            # Could be "1 camere" or "Garsoniera"
            must.append({
                "bool": {
                    "should": [
                        {"term": {"categories": "1 camere"}},
                        {"term": {"categories": "Garsoniera"}}
                    ],
                    "minimum_should_match": 1
                }
            })
        else:
            must.append({"term": {"categories": f"{rooms} camere"}})
    
    # Price range
    price_filter = {}
    if parsed.get("price_min"):
        price_filter["gte"] = parsed["price_min"]
    if parsed.get("price_max"):
        price_filter["lte"] = parsed["price_max"]
    if price_filter:
        must.append({"range": {"price": price_filter}})
    
    # Keywords - search in title and description
    keywords = parsed.get("keywords", [])
    if keywords:
        for kw in keywords:
            must.append({
                "bool": {
                    "should": [
                        {"match": {"driver_title": {"query": kw, "boost": 2.0}}},
                        {"match": {"description": {"query": kw, "boost": 1.0}}}
                    ],
                    "minimum_should_match": 1
                }
            })
    
    # Features - semantic search + exclusions
    features = parsed.get("features", {})
    neural_boost_texts = []
    
    for feature_name, feature_value in features.items():
        if not feature_value or feature_name not in FEATURE_PATTERNS:
            continue
            
        pattern = FEATURE_PATTERNS[feature_name]
        
        if feature_value == "WANT":
            # Boost positive matches via neural search
            neural_boost_texts.append(pattern["positive_boost"])
            
            # Exclude listings with negative phrases
            for phrase in pattern["negative_patterns"]:
                must_not.append({"match_phrase": {"description": phrase}})
                
        elif feature_value == "EXCLUDE":
            # User explicitly doesn't want this feature
            # Boost listings that say they don't have it
            neural_boost_texts.extend(pattern["negative_patterns"][:3])
    
    # Neural search boost
    if neural_boost_texts:
        should.append({
            "neural": {
                "listing_vector": {
                    "query_text": " ".join(neural_boost_texts),
                    "model_id": EMBEDDING_MODEL_ID,
                    "k": 100
                }
            }
        })
    
    # Build final query
    query = {
        "size": size,
        "query": {
            "bool": {
                "must": must if must else [{"match_all": {}}],
            }
        },
        "_source": [
            "driver_title", "description", "price", "currency",
            "location_1", "location_2", "location_3",
            "ad_url", "categories", "attributes"
        ]
    }
    
    if should:
        query["query"]["bool"]["should"] = should
        query["query"]["bool"]["minimum_should_match"] = 0
    
    if must_not:
        query["query"]["bool"]["must_not"] = must_not
    
    return query

# =============================================================================
# SEARCH EXECUTION
# =============================================================================

def execute_search(query: Dict) -> Dict:
    """Execute search against OpenSearch"""
    
    response = requests.post(
        f"{OPENSEARCH_URL}/{INDEX_PATTERN}/_search",
        json=query,
        auth=OPENSEARCH_AUTH,
        verify=False,
        timeout=10
    )
    
    if response.status_code != 200:
        raise Exception(f"OpenSearch error: {response.status_code} - {response.text}")
    
    return response.json()


def get_relevance_tag(score: float, max_score: float) -> str:
    """Convert score to a relevance tag with emoji"""
    if max_score == 0:
        return "⚪ N/A"
    
    pct = (score / max_score) * 100
    
    if pct >= 90:
        return f"🟢 {pct:.0f}%"  # Excellent match
    elif pct >= 70:
        return f"🟡 {pct:.0f}%"  # Good match
    elif pct >= 50:
        return f"🟠 {pct:.0f}%"  # Fair match
    else:
        return f"🔴 {pct:.0f}%"  # Weak match


def search(user_query: str, user_id: str = None, session_id: str = None, verbose: bool = True) -> Dict:
    """Main search function with persistent memory"""
    global conversation_memory, current_user_id, current_session_id
    
    # Use provided user/session or defaults
    uid = user_id or current_user_id
    sid = session_id or current_session_id
    
    # Load memory from OpenSearch
    memory = load_memory(uid, sid)
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"Query: {user_query}")
        print(f"Session: {uid}/{sid}")
        print('='*60)
    
    # Step 1: Parse with LLM
    if verbose:
        print("\n[1] Parsing query...")
    
    parsed = parse_query_with_llm(user_query, memory)
    
    if verbose:
        print(f"Parsed filters: {json.dumps(parsed, indent=2, ensure_ascii=False)}")
    
    # Save updated memory to OpenSearch
    save_memory(uid, sid, parsed, user_query)
    
    # Also update global for CLI convenience
    conversation_memory = deepcopy(parsed)
    
    # Step 2: Build query
    if verbose:
        print("\n[2] Building OpenSearch query...")
    
    os_query = build_opensearch_query(parsed)
    
    if verbose:
        print(f"Query: {json.dumps(os_query, indent=2, ensure_ascii=False)}")
    
    # Step 3: Execute
    if verbose:
        print("\n[3] Searching...")
    
    results = execute_search(os_query)
    hits = results.get("hits", {}).get("hits", [])
    total = results.get("hits", {}).get("total", {}).get("value", 0)
    max_score = results.get("hits", {}).get("max_score") or 1.0
    
    if verbose:
        print(f"\n✅ Found {total} results!")
        print("-" * 60)
        
        for i, hit in enumerate(hits[:10], 1):
            src = hit["_source"]
            score = hit.get("_score", 0)
            relevance = get_relevance_tag(score, max_score)
            
            title = src.get("driver_title", "No title")[:50]
            price = src.get("price", "N/A")
            currency = src.get("currency", "EUR")
            loc = src.get("location_3") or src.get("location_2") or "?"
            categories = src.get("categories", [])
            
            print(f"{i}. [{relevance}] {title}")
            print(f"   💰 {price} {currency} | 📍 {loc} | 🏷️ {', '.join(categories[:3])}")
            
            # Show description snippet if it contains feature keywords
            desc = src.get("description", "")[:250]
            desc_clean = desc.replace("<br />", " ").replace("\n", " ")
            keywords = ["animal", "fumator", "parcare", "mobilat", "centrala", "pet"]
            if any(kw in desc_clean.lower() for kw in keywords):
                print(f"   📝 {desc_clean[:150]}...")
            print()
        
        if total > 10:
            print(f"... and {total - 10} more results\n")
    
    # Add relevance to each result
    for hit in hits:
        hit["_relevance_pct"] = (hit.get("_score", 0) / max_score) * 100 if max_score else 0
    
    return {
        "parsed": parsed,
        "query": os_query,
        "total": total,
        "max_score": max_score,
        "results": hits,
        "session": {"user_id": uid, "session_id": sid}
    }

# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    global conversation_memory, current_user_id, current_session_id
    
    # Ensure memory index exists
    ensure_memory_index()
    
    print("🏠 Smart Real Estate Search")
    print("=" * 40)
    print(f"Session: {current_user_id}/{current_session_id}")
    print("Commands: 'reset' | 'memory' | 'history' | 'exit'")
    print("=" * 40 + "\n")
    
    while True:
        try:
            query = input("🔍 Search: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break
        
        if not query:
            continue
        
        cmd = query.lower()
        
        if cmd in ["exit", "quit", "q"]:
            print("Bye!")
            break
        
        if cmd == "reset":
            delete_memory(current_user_id, current_session_id)
            conversation_memory = create_empty_memory()
            current_session_id = str(uuid.uuid4())[:8]
            print(f"🔄 Memory cleared! New session: {current_session_id}\n")
            continue
        
        if cmd == "memory":
            mem = load_memory(current_user_id, current_session_id)
            print(f"Current memory: {json.dumps(mem, indent=2, ensure_ascii=False)}\n")
            continue
        
        if cmd == "history":
            # Fetch history from OpenSearch
            doc_id = f"{current_user_id}_{current_session_id}"
            response = requests.get(
                f"{OPENSEARCH_URL}/{MEMORY_INDEX}/_doc/{doc_id}",
                auth=OPENSEARCH_AUTH,
                verify=False
            )
            if response.status_code == 200:
                history = response.json()["_source"].get("query_history", [])
                print("📜 Query history:")
                for h in history[-10:]:
                    print(f"  - {h['q']}")
                print()
            else:
                print("No history yet.\n")
            continue
        
        try:
            search(query, verbose=True)
        except Exception as e:
            print(f"❌ Error: {e}\n")


if __name__ == "__main__":
    main()
