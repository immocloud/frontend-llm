#!/bin/bash
# =============================================================================
# SETUP OPENSEARCH DLS (Document Level Security) FOR USER DATA ISOLATION
# =============================================================================
# This script configures OpenSearch Security to:
# 1. Accept JWT tokens from Keycloak
# 2. Map JWT 'sub' claim to backend roles
# 3. Create a role with DLS that filters documents by user_id
#
# Prerequisites:
# - OpenSearch Security plugin enabled
# - Admin access to OpenSearch
# =============================================================================

set -e

# Configuration - adjust these
OPENSEARCH_URL="${OPENSEARCH_URL:-https://192.168.80.199:9200}"
OPENSEARCH_USER="${OPENSEARCH_USER:-admin}"
OPENSEARCH_PASS="${OPENSEARCH_PASS:-FaraParole69}"
KEYCLOAK_URL="${KEYCLOAK_URL:-https://keycloak.example.com}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-master}"

CURL_OPTS="-k -u ${OPENSEARCH_USER}:${OPENSEARCH_PASS} -H Content-Type:application/json"

echo "🔐 Setting up OpenSearch DLS for user data isolation"
echo "   OpenSearch: $OPENSEARCH_URL"
echo "   Keycloak:   $KEYCLOAK_URL/realms/$KEYCLOAK_REALM"
echo ""

# =============================================================================
# STEP 1: Create role with DLS for search-conversations index
# =============================================================================
echo "📋 Creating 'search_user' role with DLS..."

# This role:
# - Allows read/write to search-conversations index
# - DLS query filters documents where user_id matches the backend role
# - The backend role will be set to the JWT 'sub' claim (user ID)

curl -s $CURL_OPTS -X PUT "$OPENSEARCH_URL/_plugins/_security/api/roles/search_user" -d '
{
  "cluster_permissions": [],
  "index_permissions": [
    {
      "index_patterns": ["search-conversations"],
      "dls": "{\"term\": {\"user_id\": \"${user.name}\"}}",
      "fls": [],
      "masked_fields": [],
      "allowed_actions": [
        "crud",
        "create_index"
      ]
    },
    {
      "index_patterns": ["real-estate-*"],
      "dls": "",
      "fls": [],
      "masked_fields": ["decrypted_phone"],
      "allowed_actions": [
        "read"
      ]
    }
  ],
  "tenant_permissions": []
}' | jq .

echo ""

# =============================================================================
# STEP 2: Create roles mapping for JWT authentication
# =============================================================================
echo "🔗 Creating role mapping for 'search_user'..."

# This maps ALL authenticated users to the search_user role
# The ${user.name} in DLS will be populated from JWT 'sub' claim

curl -s $CURL_OPTS -X PUT "$OPENSEARCH_URL/_plugins/_security/api/rolesmapping/search_user" -d '
{
  "backend_roles": [],
  "hosts": [],
  "users": ["*"]
}' | jq .

echo ""

# =============================================================================
# STEP 3: Configure JWT authentication (requires config.yml update)
# =============================================================================
echo "📝 JWT Authentication Configuration"
echo ""
echo "To enable JWT auth from Keycloak, add this to your opensearch-security/config.yml:"
echo ""
cat << 'EOF'
config:
  dynamic:
    authc:
      jwt_auth_domain:
        description: "Authenticate via Keycloak JWT"
        http_enabled: true
        transport_enabled: false
        order: 0
        http_authenticator:
          type: jwt
          challenge: false
          config:
            signing_key: "-----BEGIN PUBLIC KEY-----\n<YOUR_KEYCLOAK_PUBLIC_KEY>\n-----END PUBLIC KEY-----"
            jwt_header: "Authorization"
            jwt_url_parameter: null
            roles_key: "realm_access.roles"
            subject_key: "sub"
        authentication_backend:
          type: noop
EOF

echo ""
echo "To get the public key from Keycloak:"
echo "  curl -s $KEYCLOAK_URL/realms/$KEYCLOAK_REALM | jq -r '.public_key'"
echo ""

# =============================================================================
# STEP 4: Verify setup
# =============================================================================
echo "✅ Verifying role was created..."
curl -s $CURL_OPTS "$OPENSEARCH_URL/_plugins/_security/api/roles/search_user" | jq .

echo ""
echo "✅ Verifying role mapping..."
curl -s $CURL_OPTS "$OPENSEARCH_URL/_plugins/_security/api/rolesmapping/search_user" | jq .

echo ""
echo "🎉 DLS setup complete!"
echo ""
echo "Next steps:"
echo "1. Update opensearch-security/config.yml with JWT auth config"
echo "2. Run securityadmin.sh to apply config changes"
echo "3. Set AUTH_ENABLED=true in your API .env file"
echo "4. Test with a valid Keycloak JWT token"
