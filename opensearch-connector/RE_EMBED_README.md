# Re-embedding Failed Documents

## Problem

Documents fail to embed due to AWS SDK connection pool exhaustion with the error:

```
Error communicating with remote model: Acquire operation took longer than the configured maximum time. 
This indicates that a request cannot get a connection from the pool within the specified maximum time.
```

## Solution

The `re_embed_failed_docs.py` script addresses this by:

1. **Aggressive rate limiting** - Configurable sleep between batches
2. **Smaller batch sizes** - Reduced from 32 to 8 (configurable)
3. **Connection pool limits** - Conservative max connections setting
4. **Exponential backoff with jitter** - Retries with randomized delays
5. **Progress tracking** - Saves progress and can resume if interrupted
6. **Better error handling** - Categorizes failures and retries appropriately

## Usage

### 1. Check Current Status

```bash
cd /home/vlad/repos/frontend-llm/opensearch-connector
python3 check_embedding_status.py
```

This shows:
- Total documents in the index
- Breakdown by embedding status (success/failed/fatal)
- Documents with/without vectors
- Current re-embedding progress

### 2. Run Re-embedding Script

```bash
python3 re_embed_failed_docs.py
```

The script will:
- Query for documents with `embedding_status=failed` or missing `listing_vector`
- Process them in small batches with rate limiting
- Save progress to `re_embed_progress.json`
- Continue until all documents are processed or only fatal errors remain

### 3. Monitor Progress

In another terminal:
```bash
# Watch the progress in real-time
watch -n 10 python3 check_embedding_status.py

# Or check the progress file
cat re_embed_progress.json
```

## Configuration

Environment variables (with defaults):

```bash
# OpenSearch settings
export OPENSEARCH_HOST="https://192.168.40.101:9200"
export OPENSEARCH_USER="admin"
export OPENSEARCH_PASS="FaraParole69"
export INDEX_NAME="real-estate-bge-v2"

# Ollama settings
export OLLAMA_HOST="http://localhost:11434"
export OLLAMA_MODEL="bge-m3:q4_K_M"

# Performance tuning (adjust based on your system)
export SCROLL_SIZE="100"                  # Documents per page (default: 100)
export BATCH_SIZE="8"                     # Documents per embedding call (default: 8)
export SLEEP_BETWEEN_BATCHES="2.0"        # Seconds between batches (default: 2.0)
export PROGRESS_FILE="re_embed_progress.json"
```

### Tuning Guidelines

**If you're still getting timeout errors:**
- Decrease `BATCH_SIZE` (try 4 or even 2)
- Increase `SLEEP_BETWEEN_BATCHES` (try 3.0 or 5.0)

**If processing is too slow and no errors:**
- Increase `BATCH_SIZE` (try 16 or 24)
- Decrease `SLEEP_BETWEEN_BATCHES` (try 1.0 or 0.5)
- Increase `SCROLL_SIZE` (try 200 or 500)

**Connection pool settings** (edit in script if needed):
- `MAX_CONNECTIONS = 10` - Conservative limit
- `CONNECTION_TIMEOUT = 60` - Connection timeout in seconds
- `READ_TIMEOUT = 120` - Read timeout in seconds

## Document Status

The script uses three status values:

- **`success`** - Document embedded successfully
- **`failed`** - Embedding failed (will be retried)
- **`fatal`** - Document has no text to embed (empty title + description)

## Progress Tracking

Progress is saved to `re_embed_progress.json`:

```json
{
  "total_processed": 1234,
  "total_succeeded": 1200,
  "total_failed": 34,
  "passes": 3,
  "started_at": "2026-01-06T10:30:00",
  "last_updated": "2026-01-06T11:45:00",
  "last_batch_time": 1704539100.123
}
```

If the script is interrupted (Ctrl+C or crash), it will resume from where it left off.

## Workflow

1. **Initial run**: Script processes all failed/missing documents
2. **Subsequent passes**: Re-attempts any documents that failed in previous passes
3. **Completion**: Stops when no documents need processing or only fatal errors remain

## Example Session

```bash
# Check status
$ python3 check_embedding_status.py
======================================================================
Embedding Status Report - 2026-01-06 10:30:00
======================================================================
Index: real-estate-bge-v2
Host: https://192.168.40.101:9200

Total documents: 50,000

By embedding_status field:
  success   : 48,234 ( 96.5%)
  failed    :  1,750 (  3.5%)
  fatal     :     16 (  0.0%)

🔄 Documents needing re-embedding: 1,750 (3.5%)
======================================================================

# Start re-embedding
$ python3 re_embed_failed_docs.py
======================================================================
Re-embed Failed Documents Script
======================================================================
Index: real-estate-bge-v2
OpenSearch: https://192.168.40.101:9200
Ollama: http://localhost:11434 (model: bge-m3:q4_K_M)
Scroll size: 100, Batch size: 8
Sleep between batches: 2.0s
Max connections: 10
======================================================================

======================================================================
Pass #1
Documents remaining (failed or missing vector): 1,750
======================================================================
[2026-01-06 10:31:00] PIT opened: VGhpcyBpcyBhIHRlc3Q...
[2026-01-06 10:31:05] Processing batch 1 (8 docs)...
[2026-01-06 10:31:07]   ✓ 8 succeeded, ✗ 0 failed
[2026-01-06 10:31:10] Processing batch 2 (8 docs)...
...
```

## Troubleshooting

### Still getting connection pool errors?

1. Further reduce `BATCH_SIZE` to 2-4
2. Increase `SLEEP_BETWEEN_BATCHES` to 5-10 seconds
3. Check if the Ollama service is under heavy load from other processes
4. Consider scaling up the Ollama instance or using multiple instances

### Script hangs or times out?

- Increase `CONNECTION_TIMEOUT` and `READ_TIMEOUT` in the script
- Check network connectivity to OpenSearch and Ollama
- Look for slow queries in OpenSearch logs

### All documents marked as failed?

- Check Ollama service is running: `curl http://localhost:11434/api/tags`
- Verify model is loaded: should see `bge-m3:q4_K_M` in the list
- Check Ollama logs for errors

### Want to reset and start over?

```bash
# Delete progress file
rm re_embed_progress.json

# Optional: Reset all failed documents to re-process
# (create a script to set all embedding_status back to null)
```

## Integration with Existing Scripts

This script complements the existing embedding scripts:

- **`3_update_embeddings_ollama_pit.py`** - Initial embedding of all documents
- **`re_embed_failed_docs.py`** - Re-process failed documents with better resilience
- **`reindex_with_vectors.py`** - Reindex with ML pipeline
- **`check_embedding_status.py`** - Monitor status

Use the re-embed script specifically when you see connection pool timeout errors affecting your embeddings.
