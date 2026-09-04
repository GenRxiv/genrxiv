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
echo "[1/4] Preparing test database..."
sg docker -c "docker exec -e PGPASSWORD='$DB_PASSWORD' $DB_CONTAINER psql -U genrxiv -d postgres -c 'DROP DATABASE IF EXISTS genrxiv_test WITH (FORCE);'" 2>&1 || true
sg docker -c "docker exec -e PGPASSWORD='$DB_PASSWORD' $DB_CONTAINER psql -U genrxiv -d postgres -c 'CREATE DATABASE genrxiv_test OWNER genrxiv;'" 2>&1
echo "Test database ready."

# --- 2. Copy test files into container ---
echo ""
echo "[2/4] Copying test files..."
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
echo "[3/4] Running API tests..."
sg docker -c "docker exec -w /app -e DATABASE_URL_TEST=\"postgresql://genrxiv:$DB_PASSWORD@db/genrxiv_test\" -e RATE_LIMIT_ENABLED=false $API_CONTAINER python -m pytest test_api.py -v" 2>&1

TEST_EXIT=$?

if [ $TEST_EXIT -ne 0 ]; then
    echo ""
    echo "=== TESTS FAILED ==="
    echo "DO NOT disable maintenance mode. Investigate the failures first."
    exit 1
fi

# --- 4. Screening connection smoke test ---
echo ""
echo "[4/4] Checking Cloudflare Workers AI connection..."
SCREENING_ENABLED="${SCREENING_ENABLED:-false}"
if [ "$SCREENING_ENABLED" = "true" ] || [ "$SCREENING_ENABLED" = "1" ] || [ "$SCREENING_ENABLED" = "yes" ]; then
    sg docker -c "docker exec -w /app $API_CONTAINER python -c \"
from screening import screen_submission
result = screen_submission(
    title='Connection Test',
    abstract='This is a deployment smoke test to verify the Cloudflare Workers AI connection.',
    markdown='# Connection Test\n\nThis is a deployment smoke test.',
)
verdict = result['verdict']
error = result.get('error')
if verdict == 'screening_disabled':
    print('Screening is disabled — skipping connection test.')
elif verdict in ('auto_approve', 'flag_for_review'):
    print(f'Screening connection OK (verdict={verdict}).')
elif verdict == 'screening_failed':
    print(f'WARNING: Screening connection failed: {error}')
    print('Submissions will fall back to manual review, but screening is not working.')
    import sys; sys.exit(2)
else:
    print(f'WARNING: Unexpected screening verdict: {verdict}')
    import sys; sys.exit(2)
\"" 2>&1
    SCREENING_EXIT=$?
    if [ $SCREENING_EXIT -eq 2 ]; then
        echo ""
        echo "=== TESTS PASSED, BUT SCREENING CONNECTION FAILED ==="
        echo "The site is functional, but automated screening is not working."
        echo "Submissions will go to the manual review queue until this is fixed."
        echo "Check: CF_API_TOKEN, CF_ACCOUNT_ID, and IP address filtering in the Cloudflare dashboard."
        exit 0
    elif [ $SCREENING_EXIT -ne 0 ]; then
        echo "WARNING: Screening smoke test errored (exit $SCREENING_EXIT)."
        echo "Submissions will fall back to manual review."
    fi
else
    echo "Screening is disabled — skipping connection test."
fi

echo ""
echo "=== ALL TESTS PASSED ==="
echo "The deployment is verified. You can safely:"
echo "  1. Disable maintenance mode: scripts/maintenance.sh off"
echo "  2. Verify the site at https://genrxiv.org"
exit 0
