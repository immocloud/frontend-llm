# Admin API Documentation

This document describes the administrative endpoints available in the Smart Search API for data maintenance tasks.

**Base URL**: `https://nls.immocloud.ro` (Production) or `http://localhost:8000` (Local)
**Authentication**: All admin endpoints require the `key` query parameter (default: `secret-admin-key`).

---

## 1. Normalize Phone Numbers

Triggers a background job to scan all listings in `real-estate-*` indices and normalize their phone numbers.

**Logic:**
- Scans all documents (scroll API).
- Strips non-digit characters from the `decrypted_phone` field.
- Sets empty or "000000" phones to "N/A".
- Performs bulk updates in-place.
- **Dependency**: Uses `requests` directly to avoid `opensearch-py` version conflicts.

**Endpoint:**
`POST /admin/normalize-phones`

**Parameters:**
- `key` (string, required): Admin API key.

**Curl Example:**
```bash
# Production
curl -X POST "https://nls.immocloud.ro/admin/normalize-phones?key=secret-admin-key"

# Local
curl -X POST "http://localhost:8000/admin/normalize-phones?key=secret-admin-key"
```

**Response:**
```json
{
  "message": "Normalization job started in background"
}
```

---

## 2. Rebuild Agents Index

Triggers a background job to identify agencies based on phone number aggregation and rebuild the `agents` index.

**Logic:**
1.  **Flush**: Deletes the existing `agents` index and recreates it with strict mapping (`phone` as keyword).
2.  **Aggregate**: Scans `real-estate-*` for phone numbers appearing in > 5 listings.
3.  **Populate**: Inserts identified agencies into the `agents` index with metadata (agency name, listing count).

**When to run:**
- Run this **after** the normalization job completes to ensure accurate aggregation.
- Run periodically (e.g., weekly) to update the agency list.

**Endpoint:**
`POST /admin/populate-agents`

**Parameters:**
- `key` (string, required): Admin API key.

**Curl Example:**
```bash
# Production
curl -X POST "https://nls.immocloud.ro/admin/populate-agents?key=secret-admin-key"

# Local
curl -X POST "http://localhost:8000/admin/populate-agents?key=secret-admin-key"
```

**Response:**
```json
{
  "message": "Agent population job started in background"
}
```

---

## 3. Manual Agent Reporting

Allows specific users (currently `vladxpetrescu@gmail.com`, `ancampetrescu@gmail.com`) to manually flag a phone number as an agency.
This immediately adds the number to the `agents` index and updates all existing listings in `real-estate-*`. 

**Endpoint:**
`POST /admin/add-agent`

**Auth:**
Requires standard Bearer Token (JWT).

**Body:**
```json
{
  "phone": "0722123456",
  "agency_name": "Manual Report"
}
```

**Curl Example:**
```bash
curl -X POST "https://nls.immocloud.ro/admin/add-agent" \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"phone": "0744111222", "agency_name": "Bad Actor Inc"}'
```

**Response:**
```json
{
  "message": "Agent added successfully. Phone: 0744111222",
  "updated_listings": 15,
  "doc": { ... }
}
```

---

## Monitoring

Since these are background tasks, check the container logs to monitor progress:

```bash
docker logs -f smart-search-api
```

**Sample Logs:**
```
Found 43848 documents to scan.
Processed 500/43848 docs, queued 12 updates...
...
Done! Processed: 43848, Updated: 26115
```
