#!/bin/bash
# GenRxiv post-restore test runner
#
# Runs the full test suite against a test database after restoring
# from backup. If all tests pass, the deployment is verified.
#
# Usage:
#   scripts/test-after-restore.sh
#
# Exits 0 if all tests pass, 1 otherwise.
set -eu

REPO_DIR="/home/curator/genrxiv"
DB_CONTAINER="deploy-db-1"
API_CONTAINER="deploy-api-1"

# Load env
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    . "$REPO_DIR/.env"
    set +a
fi

DB_PASSWORD="${DB_PASSWORD:-}"
if [ -z "$DB_PASSWORD" ]; then
    echo "ERROR: DB_PASSWORD not set"
    exit 1
fi

echo "=== GenRxiv Post-Restore Tests ==="
echo ""

# --- 1. Ensure test database exists ---
echo "[1/3] Preparing test database..."
sg docker -c "docker exec -e PGPASSWORD='$DB_PASSWORD' $DB_CONTAINER psql -U genrxiv -d postgres -c 'DROP DATABASE IF EXISTS genrxiv_test WITH (FORCE);'" 2>&1 || true
sg docker -c "docker exec -e PGPASSWORD='$DB_PASSWORD' $DB_CONTAINER psql -U genrxiv -d postgres -c 'CREATE DATABASE genrxiv_test OWNER genrxiv;'" 2>&1
echo "Test database ready."

# --- 2. Copy test files into container ---
echo ""
echo "[2/3] Copying test files..."
cd "$REPO_DIR"
sg docker -c "docker cp api/test_api.py $API_CONTAINER:/app/test_api.py"
sg docker -c "docker cp api/conftest.py $API_CONTAINER:/app/conftest.py"
sg docker -c "docker cp api/articles.py $API_CONTAINER:/app/articles.py"
sg docker -c "docker cp api/main.py $API_CONTAINER:/app/main.py"
sg docker -c "docker cp api/auth.py $API_CONTAINER:/app/auth.py"
sg docker -c "docker cp api/web.py $API_CONTAINER:/app/web.py"
sg docker -c "docker cp api/sitemap.py $API_CONTAINER:/app/sitemap.py"
sg docker -c "docker cp api/oai.py $API_CONTAINER:/app/oai.py"
sg docker -c "docker cp api/notifications.py $API_CONTAINER:/app/notifications.py"
sg docker -c "docker cp api/orcid_client.py $API_CONTAINER:/app/orcid_client.py"
sg docker -c "docker cp api/config.py $API_CONTAINER:/app/config.py"
sg docker -c "docker cp api/ratelimit.py $API_CONTAINER:/app/ratelimit.py"
sg docker -c "docker cp api/db.py $API_CONTAINER:/app/db.py"
sg docker -c "docker cp api/screening.py $API_CONTAINER:/app/screening.py"
sg docker -c "docker cp api/migrate.py $API_CONTAINER:/app/migrate.py"
sg docker -c "docker cp api/migrations $API_CONTAINER:/app/migrations"
echo "Files copied."

# --- 3. Run tests ---
echo ""
echo "[3/3] Running API tests..."
sg docker -c "docker exec -w /app -e DATABASE_URL_TEST=\"postgresql://genrxiv:$DB_PASSWORD@db/genrxiv_test\" -e RATE_LIMIT_ENABLED=false $API_CONTAINER python -m pytest test_api.py -v" 2>&1

TEST_EXIT=$?

if [ $TEST_EXIT -eq 0 ]; then
    echo ""
    echo "=== ALL TESTS PASSED ==="
    echo "The deployment is verified. You can safely:"
    echo "  1. Disable maintenance mode: scripts/maintenance.sh off"
    echo "  2. Verify the site at https://genrxiv.org"
    exit 0
else
    echo ""
    echo "=== TESTS FAILED ==="
    echo "DO NOT disable maintenance mode. Investigate the failures first."
    exit 1
fi
