#!/bin/bash
# GenRxiv scheduled downtime deployment workflow
#
# This script orchestrates a full scheduled downtime:
#   1. Enable maintenance mode (site shows maintenance page)
#   2. Backup the current database and article files
#   3. Apply code changes (git pull or copy new code)
#   4. Rebuild and restart the API container
#   5. Run database migrations
#   6. Run the full test suite against a test database
#   7. If tests pass, disable maintenance mode (site goes live)
#   8. If tests fail, leave maintenance mode on and alert
#
# Usage:
#   scripts/deploy-downtime.sh                    # Full workflow
#   scripts/deploy-downtime.sh --no-pull          # Skip git pull (code already updated)
#   scripts/deploy-downtime.sh --restore <date>   # Restore from backup before deploying
#   scripts/deploy-downtime.sh --dry-run          # Show what would happen
#
# Environment:
#   ADMIN_SESSION_TOKEN  Admin session cookie for maintenance API
#   DB_PASSWORD          PostgreSQL password
#
# For cloud hosting migration:
#   1. Run this script on the OLD server to create a final backup
#   2. Transfer deploy/backup/local/ to the NEW server
#   3. On the NEW server:
#      - Clone the repo
#      - Copy .env (update DB host, etc.)
#      - Run: scripts/restore.sh latest
#      - Run: scripts/test-after-restore.sh
#      - If tests pass, the site is live on the new server
set -eu

REPO_DIR="/home/curator/genrxiv"
cd "$REPO_DIR"

# Load env
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    . "$REPO_DIR/.env"
    set +a
fi

DRY_RUN=false
NO_PULL=false
RESTORE_DATE=""

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)   DRY_RUN=true; shift ;;
        --no-pull)   NO_PULL=true; shift ;;
        --restore)   RESTORE_DATE="$2"; shift 2 ;;
        *)           echo "Unknown option: $1"; exit 1 ;;
    esac
done

run() {
    if $DRY_RUN; then
        echo "[dry-run] $*"
    else
        echo "  $ $*"
        "$@"
    fi
}

echo "╔══════════════════════════════════════════════════════════╗"
echo "║         GenRxiv Scheduled Downtime Deployment           ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# --- 1. Enable maintenance mode ---
echo "─── Step 1/7: Enable maintenance mode ───"
if [ -n "${ADMIN_SESSION_TOKEN:-}" ]; then
    run scripts/maintenance.sh on "Scheduled maintenance — deploying updates"
else
    echo "  WARNING: ADMIN_SESSION_TOKEN not set."
    echo "  Set it in .env to enable maintenance mode via API."
    echo "  Alternatively, the site will be unavailable during rebuild anyway."
fi
echo ""

# --- 2. Backup ---
echo "─── Step 2/7: Backup current state ───"
if [ -x "$REPO_DIR/scripts/backup.sh" ]; then
    if $DRY_RUN; then
        echo "[dry-run] scripts/backup.sh --dry-run"
    else
        scripts/backup.sh || {
            echo "WARNING: Backup failed. Continuing anyway (Ctrl-C to abort)..."
            sleep 5
        }
    fi
else
    echo "  backup.sh not found, skipping"
fi
echo ""

# --- 3. Restore from backup (if requested) ---
if [ -n "$RESTORE_DATE" ]; then
    echo "─── Step 3/7: Restore from backup ($RESTORE_DATE) ───"
    run scripts/restore.sh "$RESTORE_DATE"
    echo ""
else
    echo "─── Step 3/7: Restore from backup (skipped) ───"
    echo ""
fi

# --- 4. Update code ---
echo "─── Step 4/7: Update code ───"
if $NO_PULL; then
    echo "  Skipping git pull (--no-pull)"
elif $DRY_RUN; then
    echo "[dry-run] git pull origin main"
else
    git pull origin main || {
        echo "WARNING: git pull failed. Using current code."
    }
fi
echo ""

# --- 5. Rebuild and restart ---
echo "─── Step 5/7: Rebuild and restart API ───"
if $DRY_RUN; then
    echo "[dry-run] docker compose up -d --build api"
else
    sg docker -c "docker compose -f deploy/docker-compose.yml --env-file .env up -d --build api" 2>&1 | tail -5
    echo "Waiting for API to start..."
    sleep 5
    # Health check
    for i in 1 2 3 4 5; do
        if sg docker -c "docker exec deploy-api-1 python -c 'import urllib.request; urllib.request.urlopen(\"http://localhost:8000/health\")'" 2>/dev/null; then
            echo "API is healthy."
            break
        fi
        echo "  Waiting for API... (attempt $i/5)"
        sleep 3
    done
fi
echo ""

# --- 6. Run migrations ---
echo "─── Step 6/7: Run database migrations ───"
if $DRY_RUN; then
    echo "[dry-run] docker exec deploy-api-1 python -m migrate"
else
    sg docker -c "docker cp api/migrations deploy-api-1:/app/migrations" 2>/dev/null || true
    sg docker -c "docker cp api/migrate.py deploy-api-1:/app/migrate.py" 2>/dev/null || true
    sg docker -c "docker exec -w /app deploy-api-1 python -m migrate" 2>&1 || {
        echo "WARNING: Migration runner failed. Falling back to init_schema()."
        sg docker -c "docker exec -w /app deploy-api-1 python -c 'from db import init_pool, init_schema; init_pool(); init_schema(); print(\"Schema initialized\")'" 2>&1
    }
fi
echo ""

# --- 7. Run tests ---
echo "─── Step 7/7: Run tests ───"
if $DRY_RUN; then
    echo "[dry-run] scripts/test-after-restore.sh"
else
    if scripts/test-after-restore.sh; then
        echo ""
        echo "╔══════════════════════════════════════════════════════════╗"
        echo "║  ✓ ALL TESTS PASSED — Disabling maintenance mode        ║"
        echo "╚══════════════════════════════════════════════════════════╝"
        if [ -n "${ADMIN_SESSION_TOKEN:-}" ]; then
            scripts/maintenance.sh off
        fi
        echo ""
        echo "Deployment complete. Site is live at https://genrxiv.org"
        exit 0
    else
        echo ""
        echo "╔══════════════════════════════════════════════════════════╗"
        echo "║  ✗ TESTS FAILED — Maintenance mode stays ON             ║"
        echo "╚══════════════════════════════════════════════════════════╝"
        echo ""
        echo "The site is still in maintenance mode. Investigate the"
        echo "test failures before disabling maintenance mode."
        echo ""
        echo "To disable manually after fixing: scripts/maintenance.sh off"
        echo "To rollback: scripts/restore.sh latest"
        exit 1
    fi
fi
