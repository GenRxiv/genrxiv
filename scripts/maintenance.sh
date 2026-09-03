#!/bin/bash
# GenRxiv maintenance mode toggle
#
# Usage:
#   scripts/maintenance.sh on  ["Message"]   # Enable maintenance mode
#   scripts/maintenance.sh off                # Disable maintenance mode
#   scripts/maintenance.sh status             # Check current status
#
# Requires an admin session token. Set ADMIN_SESSION_TOKEN in .env or
# pass it as an environment variable.
set -eu

REPO_DIR="/home/curator/genrxiv"
BASE_URL="${GENRXIV_URL:-http://localhost:8080}"

# Load env
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    . "$REPO_DIR/.env"
    set +a
fi

ADMIN_TOKEN="${ADMIN_SESSION_TOKEN:-}"
if [ -z "$ADMIN_TOKEN" ]; then
    echo "ERROR: ADMIN_SESSION_TOKEN not set in .env or environment"
    echo "To get a token:"
    echo "  1. Sign in with an admin ORCID at $BASE_URL/auth/orcid"
    echo "  2. Check your browser cookies for 'genrxiv_session'"
    echo "  3. Add ADMIN_SESSION_TOKEN=<value> to .env"
    exit 1
fi

ACTION="${1:-status}"

case "$ACTION" in
    on)
        MESSAGE="${2:-Scheduled maintenance in progress}"
        echo "Enabling maintenance mode..."
        curl -s -X POST "$BASE_URL/admin/maintenance" \
            -b "genrxiv_session=$ADMIN_TOKEN" \
            -d "enabled=true" \
            -d "message=$MESSAGE" | python3 -m json.tool 2>/dev/null || \
        curl -s -X POST "$BASE_URL/admin/maintenance" \
            -b "genrxiv_session=$ADMIN_TOKEN" \
            -d "enabled=true" \
            -d "message=$MESSAGE"
        echo ""
        echo "Maintenance mode is ON. Site shows maintenance page."
        ;;
    off)
        echo "Disabling maintenance mode..."
        curl -s -X POST "$BASE_URL/admin/maintenance" \
            -b "genrxiv_session=$ADMIN_TOKEN" \
            -d "enabled=false" | python3 -m json.tool 2>/dev/null || \
        curl -s -X POST "$BASE_URL/admin/maintenance" \
            -b "genrxiv_session=$ADMIN_TOKEN" \
            -d "enabled=false"
        echo ""
        echo "Maintenance mode is OFF. Site is live."
        ;;
    status)
        echo "Checking maintenance status..."
        curl -s "$BASE_URL/admin/maintenance" \
            -b "genrxiv_session=$ADMIN_TOKEN" | python3 -m json.tool 2>/dev/null || \
        curl -s "$BASE_URL/admin/maintenance" \
            -b "genrxiv_session=$ADMIN_TOKEN"
        echo ""
        ;;
    *)
        echo "Usage: $0 {on|off|status} [\"message\"]"
        exit 1
        ;;
esac
