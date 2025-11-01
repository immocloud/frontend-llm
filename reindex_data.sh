#!/bin/bash
# ==============================================
# REINDEX OLD REAL ESTATE INDICES TO -VECTOR VERSIONS
# ==============================================

OPENSEARCH_URL="https://192.168.40.101:9200"
USERNAME="admin"
PASSWORD="FaraParole69"
PIPELINE="property-vectorizer-pipeline"
CURL_OPTS="-k -u ${USERNAME}:${PASSWORD} -H Content-Type:application/json"

echo "🔍 Fetching indices..."
INDICES=$(curl -s $CURL_OPTS "$OPENSEARCH_URL/_cat/indices?h=index" | grep '^real-estate-' | grep -v -- '-vector$' | sort)

if [ -z "$INDICES" ]; then
  echo "❌ No source indices found."
  exit 1
fi

for INDEX in $INDICES; do
  DEST="${INDEX}-vector"
  echo "🚀 Reindexing $INDEX → $DEST ..."

  REINDEX_PAYLOAD=$(cat <<EOF
{
  "source": { "index": "$INDEX" },
  "dest": {
    "index": "$DEST",
    "pipeline": "$PIPELINE"
  }
}
EOF
)

  # Start async reindex
  RESPONSE=$(curl -s -w "%{http_code}" -o /tmp/reindex_resp.json \
    $CURL_OPTS -X POST "$OPENSEARCH_URL/_reindex?wait_for_completion=false" \
    -d "$REINDEX_PAYLOAD")

  HTTP_CODE=$(tail -n1 <<< "$RESPONSE")
  TASK_ID=$(jq -r '.task' /tmp/reindex_resp.json)

  if [ "$HTTP_CODE" != "200" ]; then
    echo "❌ Failed to start reindex for $INDEX (HTTP $HTTP_CODE)"
    cat /tmp/reindex_resp.json
    continue
  fi

  echo "🕒 Task ID: $TASK_ID"

  # Poll until complete
  while true; do
    STATUS=$(curl -s $CURL_OPTS "$OPENSEARCH_URL/_tasks/$TASK_ID" | jq -r '.completed')
    if [ "$STATUS" == "true" ]; then
      echo "✅ Reindex completed for $INDEX"
      break
    else
      echo "⏳ Still processing $INDEX... waiting 20s"
      sleep 20
    fi
  done

  # Add alias so queries can hit latest data
  echo "🔗 Updating alias real-estate-latest → $DEST"
  curl -s $CURL_OPTS -X POST "$OPENSEARCH_URL/_aliases" -d "{
    \"actions\": [
      { \"remove\": { \"index\": \"$INDEX\", \"alias\": \"real-estate-latest\" } },
      { \"add\": { \"index\": \"$DEST\", \"alias\": \"real-estate-latest\" } }
    ]
  }" > /dev/null

  echo "--------------------------------------"
done

echo "🎉 All indices reindexed successfully!"
