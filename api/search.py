# api/search.py - Core search logic
# LLM parsing + OpenSearch query building + result formatting

import re
import json
import httpx
import requests
import unicodedata
from copy import deepcopy
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from .config import settings
from .models import SearchResult, SearchFilters, SearchFeatures

# =============================================================================
# CONSTANTS
# =============================================================================

VALID_TRANSACTIONS = ["Vanzare", "Inchiriere"]
VALID_PROPERTY_TYPES = ["Apartamente", "Case", "Garsoniera", "Terenuri", "Vile", "Spatii", "Birou"]

KNOWN_CITIES = {
    "bucuresti": "Bucuresti", "bucharest": "Bucuresti",
    "timisoara": "Timis", "cluj": "Cluj", "cluj-napoca": "Cluj",
    "iasi": "Iasi", "constanta": "Constanta", "brasov": "Brasov",
    "sibiu": "Sibiu", "oradea": "Bihor", "craiova": "Dolj",
    "arad": "Arad", "ploiesti": "Prahova",
}

FEATURE_PATTERNS = {
    "animale": {
        "positive_boost": "accepta animale pet friendly pisici caini animale de companie se accepta animal",
        "negative_patterns": [
            "nu se accepta animale", "nu se acceptă animale", "nu accept animale",
            "nu accepta animale", "nu acceptam animale", "fara animale", "fără animale",
            "exclus animale", "nu se accepta animale de companie", "nu accept animale de companie",
            "nu sunt acceptate animale", "nu se acceptă animale de companie",
        ]
    },
    "fumatori": {
        "positive_boost": "fumatori acceptati se poate fuma accept fumatori",
        "negative_patterns": [
            "nu accept fumatori", "nu accept fumători", "fara fumatori", "fără fumători",
            "nefumatori", "non fumatori", "nu se fumeaza", "interzis fumatul", "exclus fumatori",
        ]
    },
    "parcare": {
        "positive_boost": "loc parcare garaj parcare inclusa parcare subterana boxa",
        "negative_patterns": ["fara parcare", "fără parcare", "nu are parcare"]
    },
    "mobilat": {
        "positive_boost": "mobilat complet utilat mobilat modern complet mobilat",
        "negative_patterns": ["nemobilat", "neutilat", "fara mobila", "fără mobilă", "gol"]
    },
    "centrala": {
        "positive_boost": "centrala proprie centrala termica incalzire autonoma",
        "negative_patterns": ["fara centrala", "încălzire centralizată"]
    },
}


# =============================================================================
# UTILITIES
# =============================================================================

def strip_diacritics(text: str) -> str:
    """Remove Romanian diacritics"""
    if not text:
        return text
    normalized = unicodedata.normalize('NFD', text)
    return ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')


def normalize_city(city: str) -> Optional[str]:
    """Normalize city name to match location_1 field"""
    if not city:
        return None
    city_lower = strip_diacritics(city.lower().strip())
    if city_lower in KNOWN_CITIES:
        return KNOWN_CITIES[city_lower]
    for key, value in KNOWN_CITIES.items():
        if strip_diacritics(key) == city_lower:
            return value
    return city.strip().title()


def validate_transaction(t: str) -> Optional[str]:
    if not t:
        return None
    t = strip_diacritics(t.strip().lower())
    if t in ["vanzare", "vand", "cumpar", "cumparare", "vânzare"]:
        return "Vanzare"
    elif t in ["inchiriere", "inchiriez", "chirie", "închiriere"]:
        return "Inchiriere"
    return None


def validate_property_type(p: str) -> Optional[str]:
    if not p:
        return None
    p = strip_diacritics(p.strip().lower())
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
# MEMORY FUNCTIONS
# =============================================================================

def create_empty_memory() -> Dict[str, Any]:
    """Create fresh memory state"""
    return {
        "location": None, "city": None, "transaction": None,
        "property_type": None, "rooms": None, "price_min": None,
        "price_max": None, "keywords": [],
        "features": {
            "animale": None, "fumatori": None, "parcare": None,
            "mobilat": None, "centrala": None,
        }
    }


def load_memory(user_id: str, session_id: str) -> Dict[str, Any]:
    """Load memory from OpenSearch"""
    doc_id = f"{user_id}_{session_id}"
    try:
        response = requests.get(
            f"{settings.opensearch_url}/{settings.memory_index}/_doc/{doc_id}",
            auth=settings.opensearch_auth,
            verify=settings.opensearch_verify_ssl,
            timeout=5
        )
        if response.status_code == 200:
            return response.json()["_source"].get("filters", create_empty_memory())
    except:
        pass
    return create_empty_memory()


def save_memory(user_id: str, session_id: str, filters: Dict, query: str = None):
    """Save memory to OpenSearch"""
    doc_id = f"{user_id}_{session_id}"
    now = datetime.now(timezone.utc).isoformat()
    
    # Get existing to preserve history
    try:
        existing = requests.get(
            f"{settings.opensearch_url}/{settings.memory_index}/_doc/{doc_id}",
            auth=settings.opensearch_auth,
            verify=settings.opensearch_verify_ssl,
            timeout=5
        )
        query_history = []
        created_at = now
        if existing.status_code == 200:
            src = existing.json()["_source"]
            query_history = src.get("query_history", [])
            created_at = src.get("created_at", now)
    except:
        query_history = []
        created_at = now
    
    if query:
        query_history.append({"q": query, "ts": now})
        query_history = query_history[-50:]  # Keep last 50
    
    doc = {
        "user_id": user_id,
        "session_id": session_id,
        "filters": filters,
        "query_history": query_history,
        "created_at": created_at,
        "updated_at": now
    }
    
    requests.put(
        f"{settings.opensearch_url}/{settings.memory_index}/_doc/{doc_id}",
        json=doc,
        auth=settings.opensearch_auth,
        verify=settings.opensearch_verify_ssl,
        timeout=5
    )


def delete_memory(user_id: str, session_id: str) -> bool:
    """Delete session memory"""
    doc_id = f"{user_id}_{session_id}"
    try:
        response = requests.delete(
            f"{settings.opensearch_url}/{settings.memory_index}/_doc/{doc_id}",
            auth=settings.opensearch_auth,
            verify=settings.opensearch_verify_ssl,
            timeout=5
        )
        return response.status_code in [200, 404]
    except:
        return False


def ensure_memory_index():
    """Create memory index if it doesn't exist"""
    mapping = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "user_id": {"type": "keyword"},
                "session_id": {"type": "keyword"},
                "filters": {"type": "object", "enabled": False},
                "query_history": {"type": "nested", "properties": {
                    "q": {"type": "text"},
                    "ts": {"type": "date"}
                }},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"}
            }
        }
    }
    
    try:
        response = requests.head(
            f"{settings.opensearch_url}/{settings.memory_index}",
            auth=settings.opensearch_auth,
            verify=settings.opensearch_verify_ssl
        )
        if response.status_code == 404:
            requests.put(
                f"{settings.opensearch_url}/{settings.memory_index}",
                json=mapping,
                auth=settings.opensearch_auth,
                verify=settings.opensearch_verify_ssl
            )
    except:
        pass


# =============================================================================
# ASSISTANT MESSAGE GENERATION
# =============================================================================

def generate_assistant_message(parsed: Dict, total: int, query: str) -> tuple[str, str]:
    """
    Generate a friendly assistant message based on search results.
    Returns (message, message_type)
    """
    import random
    
    # Build context parts
    location_parts = []
    if parsed.get("location"):
        location_parts.append(parsed["location"])
    if parsed.get("city"):
        location_parts.append(parsed["city"])
    location_str = ", ".join(location_parts) if location_parts else None
    
    property_type = parsed.get("property_type", "proprietăți")
    if property_type == "Apartamente":
        property_type = "apartamente"
    elif property_type == "Case":
        property_type = "case"
    elif property_type == "Garsoniera":
        property_type = "garsoniere"
    else:
        property_type = "proprietăți"
    
    transaction = parsed.get("transaction")
    if transaction == "Inchiriere":
        transaction_str = "de închiriat"
    elif transaction == "Vanzare":
        transaction_str = "de vânzare"
    else:
        transaction_str = ""
    
    # Price range
    price_parts = []
    if parsed.get("price_min") and parsed.get("price_max"):
        price_parts.append(f"între {parsed['price_min']} și {parsed['price_max']}€")
    elif parsed.get("price_min"):
        price_parts.append(f"de la {parsed['price_min']}€")
    elif parsed.get("price_max"):
        price_parts.append(f"până la {parsed['price_max']}€")
    price_str = price_parts[0] if price_parts else None
    
    # Rooms
    rooms = parsed.get("rooms")
    rooms_str = f"cu {rooms} camere" if rooms else None
    
    # Features
    features = parsed.get("features", {})
    feature_strs = []
    if features.get("animale") == "WANT":
        feature_strs.append("pet friendly")
    if features.get("parcare") == "WANT":
        feature_strs.append("cu parcare")
    if features.get("mobilat") == "WANT":
        feature_strs.append("mobilat")
    
    # Build the message
    if total == 0:
        # No results
        no_result_messages = [
            f"Nu am găsit {property_type} {transaction_str} care să corespundă criteriilor tale. Încearcă să lărgești aria de căutare sau să ajustezi filtrele.",
            f"Hmm, nu am găsit nimic. Poate încerci cu alte criterii sau într-o altă zonă?",
            f"Din păcate, nu există {property_type} disponibile cu aceste filtre. Vrei să încercăm altceva?",
        ]
        return random.choice(no_result_messages), "no_results"
    
    # Has results - build natural message
    intro_phrases = [
        f"Am găsit {total} {property_type}",
        f"Sunt {total} {property_type} disponibile",
        f"Iată {total} {property_type}",
        f"Am identificat {total} {property_type}",
    ]
    
    message_parts = [random.choice(intro_phrases)]
    
    if transaction_str:
        message_parts.append(transaction_str)
    if location_str:
        message_parts.append(f"în {location_str}")
    if price_str:
        message_parts.append(price_str)
    if rooms_str:
        message_parts.append(rooms_str)
    if feature_strs:
        message_parts.append(", ".join(feature_strs))
    
    message = " ".join(message_parts) + "."
    
    # Add helpful suggestions for refinement
    if total > 50:
        suggestions = [
            " Poți rafina căutarea specificând zona exactă sau intervalul de preț.",
            " Încearcă să adaugi mai multe detalii pentru rezultate mai precise.",
            " Spune-mi dacă vrei să filtrez după numărul de camere sau alte facilități.",
        ]
        message += random.choice(suggestions)
    elif total > 0 and total <= 10:
        encouragements = [
            " Arată bine! Verifică rezultatele de mai jos.",
            " Câteva opțiuni interesante! 👇",
            " Iată ce am găsit pentru tine.",
        ]
        message += random.choice(encouragements)
    
    return message, "results"


# =============================================================================
# LLM PARSING
# =============================================================================

def parse_query_with_llm(user_query: str, current_context: Dict) -> Dict:
    """Use LLM to parse natural language query"""
    
    context_str = json.dumps(current_context, ensure_ascii=False, indent=2)
    
    prompt = f'''You are a Romanian real estate search parser. Parse the user's query into structured JSON.

CURRENT SEARCH CONTEXT (from previous queries in this conversation):
{context_str}

USER QUERY: "{user_query}"

CRITICAL RULES:
1. ALWAYS preserve ALL existing context values, EXCEPT the fields explicitly mentioned in the new query
2. If user mentions a NEW location (e.g., "sector 3", "Titan", "Pallady"), UPDATE the location field - keep all other filters
3. If user says "acum vreau", "dar in", "pe alea din", "doar in", "schimba" - this MODIFIES only that specific filter
4. For features (animale, fumatori, parcare, mobilat, centrala):
   - "WANT" = user wants this feature
   - "EXCLUDE" = user doesn't want this
   - null = not mentioned, keep existing value
5. For exclude_agencies:
   - Set to true if user says: "fara agentii", "doar particulari", "nu agenti", "private only", "no agents"
   - Keep existing value if not mentioned

EXAMPLES of REFINEMENT queries (keep all context, change only what's mentioned):
- Context has "location": "Sector 1" -> Query: "acum vreau din sector 3" -> Output: "location": "Sector 3" (keep ALL other fields!)
- Context has "price_max": 800 -> Query: "dar cu maxim 600 euro" -> Output: "price_max": 600 (keep ALL other fields!)
- Context has rooms: null -> Query: "cu 2 camere" -> Output: "rooms": 2 (keep ALL other fields!)

OUTPUT FORMAT (JSON only - include ALL fields, preserve context for unchanged fields):
{{
  "location": "neighborhood/sector or null if not mentioned at all",
  "city": "city or null",
  "transaction": "Vanzare" or "Inchiriere" or null,
  "property_type": "Apartamente" or "Case" or "Garsoniera" or null,
  "rooms": number or null,
  "price_min": number or null,
  "price_max": number or null,
  "keywords": ["array of terms"],
  "features": {{
    "animale": "WANT" or "EXCLUDE" or null,
    "fumatori": "WANT" or "EXCLUDE" or null,
    "parcare": "WANT" or "EXCLUDE" or null,
    "mobilat": "WANT" or "EXCLUDE" or null,
    "centrala": "WANT" or "EXCLUDE" or null
  }},
  "exclude_agencies": true or false
}}

Parse and output ONLY valid JSON:'''

    try:
        response = httpx.post(
            f"{settings.ollama_url}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 2000}  # Increased for thinking models
            },
            timeout=settings.ollama_timeout
        )
        
        raw_json = response.json()
        result = raw_json.get("response", "").strip()
        if not result:
            print(f"[LLM] Empty response - model used {raw_json.get('eval_count', 0)} tokens for thinking")
            return current_context
        
        # Extract JSON
        if "```" in result:
            match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', result)
            if match:
                result = match.group(1)
        
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            result = result[start:end]
        
        # Clean common issues
        result = re.sub(r',\s*}', '}', result)
        result = re.sub(r',\s*]', ']', result)
        result = result.replace('\n', ' ')
        
        parsed = json.loads(result)
        return validate_parsed_result(parsed, current_context, user_query)
        
    except Exception as e:
        print(f"LLM parsing error: {e}")
        return current_context


def validate_parsed_result(parsed: Dict, context: Dict, user_query: str = "") -> Dict:
    """Validate and normalize LLM output"""
    result = deepcopy(context)
    
    if parsed.get("location"):
        result["location"] = strip_diacritics(parsed["location"])
    if parsed.get("city"):
        result["city"] = normalize_city(parsed["city"])
    if parsed.get("transaction"):
        v = validate_transaction(parsed["transaction"])
        if v:
            result["transaction"] = v
    if parsed.get("property_type"):
        v = validate_property_type(parsed["property_type"])
        if v:
            result["property_type"] = v
    if parsed.get("rooms") is not None:
        rooms = parsed["rooms"]
        if isinstance(rooms, int) and 1 <= rooms <= 5:
            result["rooms"] = rooms
    if parsed.get("price_min") is not None:
        result["price_min"] = int(parsed["price_min"]) if parsed["price_min"] else None
    if parsed.get("price_max") is not None:
        result["price_max"] = int(parsed["price_max"]) if parsed["price_max"] else None
    
    # Keywords - merge
    if parsed.get("keywords"):
        existing = set(result.get("keywords", []) or [])
        new = set(parsed["keywords"]) if isinstance(parsed["keywords"], list) else set()
        result["keywords"] = list(existing | new)
    
    # Features
    if parsed.get("features"):
        for f in ["animale", "fumatori", "parcare", "mobilat", "centrala"]:
            val = parsed["features"].get(f)
            if val in ["WANT", "EXCLUDE"]:
                result["features"][f] = val
            elif val is None and f in parsed["features"]:
                result["features"][f] = None
    
    # Exclude agencies filter - check LLM output AND original query keywords
    exclude_keywords = ["fara agentii", "fără agenții", "doar particulari", "nu agenti",
                        "private only", "no agents", "fara agentie", "fără agenție",
                        "particulari", "fara agenti"]
    query_lower = user_query.lower() if user_query else ""
    
    if parsed.get("exclude_agencies") is True or any(kw in query_lower for kw in exclude_keywords):
        result["exclude_agencies"] = True
    
    return result


# =============================================================================
# OPENSEARCH QUERY BUILDER
# =============================================================================

def build_opensearch_query(parsed: Dict, size: int = 25) -> Dict:
    """Build OpenSearch query from parsed filters"""
    
    must = []
    should = []
    must_not = []
    
    # Location
    location = parsed.get("location")
    if location:
        loc_lower = location.lower()
        if "sector" in loc_lower:
            match = re.search(r'(\d+)', location)
            if match:
                sector_num = match.group(1)
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
            must.append({
                "bool": {
                    "should": [
                        {"term": {"location_3": {"value": location, "boost": 3.0}}},
                        {"match": {"location_3": {"query": location, "fuzziness": "AUTO", "boost": 2.5}}},
                        {"match": {"driver_title": {"query": location, "boost": 2.0}}},
                        {"match": {"description": {"query": location, "boost": 1.0}}}
                    ],
                    "minimum_should_match": 1
                }
            })
    
    if parsed.get("city"):
        must.append({"term": {"location_1": parsed["city"]}})
    
    if parsed.get("transaction"):
        must.append({"term": {"categories": parsed["transaction"]}})
    
    if parsed.get("property_type"):
        must.append({"term": {"categories": parsed["property_type"]}})
    
    if parsed.get("rooms"):
        rooms = parsed["rooms"]
        if rooms == 1:
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
    
    # Keywords
    for kw in parsed.get("keywords", []):
        must.append({
            "bool": {
                "should": [
                    {"match": {"driver_title": {"query": kw, "boost": 2.0}}},
                    {"match": {"description": {"query": kw, "boost": 1.0}}}
                ],
                "minimum_should_match": 1
            }
        })
    
    # Features
    features = parsed.get("features", {})
    neural_boost_texts = []
    
    for fname, fval in features.items():
        if not fval or fname not in FEATURE_PATTERNS:
            continue
        pattern = FEATURE_PATTERNS[fname]
        if fval == "WANT":
            neural_boost_texts.append(pattern["positive_boost"])
            for phrase in pattern["negative_patterns"]:
                must_not.append({"match_phrase": {"description": phrase}})
        elif fval == "EXCLUDE":
            neural_boost_texts.extend(pattern["negative_patterns"][:3])
    
    if neural_boost_texts:
        should.append({
            "neural": {
                "listing_vector": {
                    "query_text": " ".join(neural_boost_texts),
                    "model_id": settings.embedding_model_id,
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
            "driver_title", "name", "description", "price", "currency",
            "location_1", "location_2", "location_3", "coordinates",
            "ad_url", "ad_id", "categories", "attributes",
            "src_images", "images", "decrypted_phone", "source", "ad_source",
            "valid_from", "user_name"
        ]
    }
    
    if should:
        query["query"]["bool"]["should"] = should
        query["query"]["bool"]["minimum_should_match"] = 0
    if must_not:
        query["query"]["bool"]["must_not"] = must_not
    
    return query


# =============================================================================
# RESULT FORMATTING
# =============================================================================

def format_result(hit: Dict, max_score: float) -> SearchResult:
    """Format a single search result for card UI - streamlined"""
    src = hit.get("_source", {})
    
    # Calculate relevance score (0-100)
    raw_score = hit.get("_score", 0)
    score = int((raw_score / max_score) * 100) if max_score > 0 else 0
    score = min(100, max(0, score))  # Clamp to 0-100
    
    # Clean description (truncate for card preview)
    desc = src.get("description", "") or ""
    desc = desc.replace("<br />", " ").replace("<br>", " ").replace("\n", " ")
    if len(desc) > 300:
        desc = desc[:300] + "..."
    
    # Build location: "City, Area" format
    loc_parts = []
    if src.get("location_1"):
        loc_parts.append(src["location_1"])
    if src.get("location_2"):
        loc_parts.append(src["location_2"])
    location = ", ".join(loc_parts)
    
    # Images
    images = src.get("src_images", []) or src.get("images", []) or []
    images = [img for img in images if img and img.startswith("http") and not img.endswith(".svg")]
    
    # Format date nicely
    date_str = None
    valid_from = src.get("valid_from")
    if valid_from:
        try:
            dt = datetime.fromisoformat(valid_from.replace("Z", "+00:00"))
            date_str = dt.strftime("%m/%d/%y, %I:%M %p")
        except:
            date_str = valid_from
    
    # Extract surface from attributes
    surface = None
    attrs = src.get("attributes", {})
    if isinstance(attrs, dict):
        surface = attrs.get("Suprafata utila") or attrs.get("Suprafata") or attrs.get("suprafata_utila")
    
    return SearchResult(
        id=hit.get("_id", ""),
        ad_id=src.get("ad_id"),
        title=src.get("driver_title") or src.get("name") or "No title",
        description=desc,
        price=src.get("price"),
        currency=src.get("currency") or "EUR",
        location=location,
        categories=src.get("categories", []) or [],
        surface=surface,
        phone=src.get("decrypted_phone") or "N/A",
        date=date_str,
        images=images[:5],  # Limit to 5 for card
        image_count=len(images),
        source=src.get("ad_source") or src.get("source"),
        url=src.get("ad_url"),
        score=score,
    )


# =============================================================================
# MAIN SEARCH FUNCTION
# =============================================================================

def execute_search(query: Dict) -> Dict:
    """Execute search against OpenSearch"""
    response = requests.post(
        f"{settings.opensearch_url}/{settings.opensearch_index}/_search",
        json=query,
        auth=settings.opensearch_auth,
        verify=settings.opensearch_verify_ssl,
        timeout=10
    )
    if response.status_code != 200:
        raise Exception(f"OpenSearch error: {response.status_code}")
    return response.json()


def lookup_agents(phones: List[str]) -> Dict[str, Dict]:
    """
    Cross-index lookup: check which phones belong to known agents.
    Returns dict: phone -> {is_agency, seller_type, agency_name}
    """
    if not phones:
        return {}
    
    # Filter out invalid phones
    valid_phones = [p for p in phones if p and p != 'N/A' and len(p) >= 10]
    if not valid_phones:
        return {}
    
    try:
        query = {
            "query": {
                "terms": {"phone": valid_phones}
            },
            "_source": ["phone", "type", "agency_name"],
            "size": len(valid_phones)
        }
        
        response = requests.post(
            f"{settings.opensearch_url}/agents/_search",
            json=query,
            auth=settings.opensearch_auth,
            verify=settings.opensearch_verify_ssl,
            timeout=5
        )
        
        if response.status_code != 200:
            # Agents index might not exist yet - that's ok
            return {}
        
        result = response.json()
        
        # Build lookup dict
        agent_lookup = {}
        for hit in result.get('hits', {}).get('hits', []):
            src = hit['_source']
            agent_lookup[src['phone']] = {
                'is_agency': True,
                'seller_type': src.get('type', 'agent'),
                'agency_name': src.get('agency_name')
            }
        
        return agent_lookup
        
    except Exception as e:
        # Don't fail search if agent lookup fails
        print(f"Agent lookup failed: {e}")
        return {}


def enrich_with_agent_info(results: List[SearchResult], agent_lookup: Dict) -> List[SearchResult]:
    """Add is_agency flag to results based on agent lookup"""
    for result in results:
        phone = result.phone
        if phone in agent_lookup:
            result.is_agency = agent_lookup[phone]['is_agency']
            result.seller_type = agent_lookup[phone]['seller_type']
        else:
            result.is_agency = False
            result.seller_type = 'private'
    return results


def search(
    user_query: str,
    user_id: str,
    session_id: str,
    size: int = 25,
    exclude_agencies_override: Optional[bool] = None
) -> Dict:
    """
    Main search function
    
    Args:
        exclude_agencies_override: UI toggle override
            - None: use query parsing (natural language detection)
            - True: always exclude agencies  
            - False: always include agencies
    """
    
    # Load memory
    memory = load_memory(user_id, session_id)
    
    # Parse with LLM
    parsed = parse_query_with_llm(user_query, memory)
    
    # UI toggle overrides query parsing
    if exclude_agencies_override is not None:
        parsed["exclude_agencies"] = exclude_agencies_override
    
    # Save updated memory
    save_memory(user_id, session_id, parsed, user_query)
    
    # Build and execute query
    os_query = build_opensearch_query(parsed, size)
    results = execute_search(os_query)
    
    hits = results.get("hits", {}).get("hits", [])
    total = results.get("hits", {}).get("total", {}).get("value", 0)
    max_score = results.get("hits", {}).get("max_score") or 1.0
    
    # Format results
    formatted = [format_result(hit, max_score) for hit in hits]
    
    # Cross-index lookup: enrich with agent info
    phones = [r.phone for r in formatted]
    agent_lookup = lookup_agents(phones)
    formatted = enrich_with_agent_info(formatted, agent_lookup)
    
    # Apply exclude_agencies filter (post-filter after enrichment)
    if parsed.get("exclude_agencies"):
        original_count = len(formatted)
        formatted = [r for r in formatted if not r.is_agency]
        excluded_count = original_count - len(formatted)
        if excluded_count > 0:
            print(f"Excluded {excluded_count} agency listings")
    
    # Generate assistant message
    message, message_type = generate_assistant_message(parsed, total, user_query)
    
    return {
        "parsed": parsed,
        "total": total,
        "max_score": max_score,
        "results": formatted,
        "message": message,
        "message_type": message_type,
    }
