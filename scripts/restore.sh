#!/bin/bash
# GenRxiv restore-from-archive script
#
# Restores the database and article files from a backup archive.
# Used during scheduled downtime to restore from backup after
# migration or hosting changes.
#
# Usage:
#   scripts/restore.sh <backup-dir-or-date>
#
# Examples:
#   scripts/restore.sh 20250115-030000        # restore specific backup
#   scripts/restore.sh latest                 # restore most recent backup
#
# Prerequisites:
#   - Docker compose stack running (db container must be up)
#   - Backup files in deploy/backup/local/
#
# This script:
#   1. Finds the backup (by date or "latest")
#   2. Restores the PostgreSQL database from the gzipped SQL dump
#   3. Restores the article files volume from the tar archive
#   4. Runs pending database migrations
#   5. Verifies the restore by checking table counts
set -eu

REPO_DIR="/home/curator/genrxiv"
BACKUP_DIR="$REPO_DIR/deploy/backup/local"
DB_CONTAINER="deploy-db-1"
DB_PASSWORD="${DB_PASSWORD:-}"

# Load env
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    . "$REPO_DIR/.env"
    set +a
fi

if [ -z "$DB_PASSWORD" ]; then
    echo "ERROR: DB_PASSWORD not set"
    exit 1
fi

# --- Find backup ---
BACKUP_DATE="${1:-latest}"

if [ "$BACKUP_DATE" = "latest" ]; then
    DB_FILE=$(ls -t "$BACKUP_DIR"/genrxiv-db-*.sql.gz 2>/dev/null | head -1)
    FILES_FILE=$(ls -t "$BACKUP_DIR"/article-files-*.tar.gz 2>/dev/null | head -1)
else
    DB_FILE="$BACKUP_DIR/genrxiv-db-$BACKUP_DATE.sql.gz"
    FILES_FILE="$BACKUP_DIR/article-files-$BACKUP_DATE.tar.gz"
fi

if [ -z "$DB_FILE" ] || [ ! -f "$DB_FILE" ]; then
    echo "ERROR: Database backup not found in $BACKUP_DIR"
    echo "Available backups:"
    ls -1 "$BACKUP_DIR"/genrxiv-db-*.sql.gz 2>/dev/null || echo "  (none)"
    exit 1
fi

echo "=== GenRxiv Restore ==="
echo "Database backup: $DB_FILE"
echo "Files backup:    ${FILES_FILE:-none}"

# --- 1. Restore PostgreSQL ---
echo ""
echo "[1/4] Restoring PostgreSQL database..."

# Drop and recreate the database to ensure clean restore
sg docker -c "docker exec -e PGPASSWORD='$DB_PASSWORD' $DB_CONTAINER psql -U genrxiv -d postgres -c 'DROP DATABASE IF EXISTS genrxiv WITH (FORCE);'" 2>&1 || true
sg docker -c "docker exec -e PGPASSWORD='$DB_PASSWORD' $DB_CONTAINER psql -U genrxiv -d postgres -c 'CREATE DATABASE genrxiv OWNER genrxiv;'" 2>&1

# Restore from the gzipped dump
gunzip -c "$DB_FILE" | sg docker -c "docker exec -i -e PGPASSWORD='$DB_PASSWORD' $DB_CONTAINER psql -U genrxiv -d genrxiv" 2>&1

echo "Database restored."

# --- 2. Restore article files ---
if [ -n "$FILES_FILE" ] && [ -f "$FILES_FILE" ]; then
    echo ""
    echo "[2/4] Restoring article files volume..."
    # Clear existing files and restore from archive
    sg docker -c "docker run --rm -v genrxiv_article_files:/data alpine sh -c 'rm -rf /data/*'" 2>/dev/null || true
    sg docker -c "docker run --rm -i -v genrxiv_article_files:/data alpine tar xzf - -C /data" < "$FILES_FILE"
    echo "Article files restored."
else
    echo ""
    echo "[2/4] Skipping article files (no backup found)"
fi

# --- 3. Run migrations ---
echo ""
echo "[3/4] Running database migrations..."
cd "$REPO_DIR"
sg docker -c "docker cp api/migrations deploy-api-1:/app/migrations" 2>/dev/null || true
sg docker -c "docker cp api/migrate.py deploy-api-1:/app/migrate.py" 2>/dev/null || true
sg docker -c "docker exec -w /app deploy-api-1 python -m migrate" 2>&1 || {
    echo "WARNING: Migration runner failed. Falling back to init_schema()."
    sg docker -c "docker exec -w /app deploy-api-1 python -c 'from db import init_pool, init_schema; init_pool(); init_schema(); print(\"Schema initialized\")'" 2>&1
}

# --- 4. Verify ---
echo ""
echo "[4/4] Verifying restore..."
TABLE_COUNT=$(sg docker -c "docker exec -e PGPASSWORD='$DB_PASSWORD' $DB_CONTAINER psql -U genrxiv -d genrxiv -t -c 'SELECT count(*) FROM articles;'" 2>&1 | xargs)
AUTHOR_COUNT=$(sg docker -c "docker exec -e PGPASSWORD='$DB_PASSWORD' $DB_CONTAINER psql -U genrxiv -d genrxiv -t -c 'SELECT count(*) FROM authors;'" 2>&1 | xargs)
PUBLISHED_COUNT=$(sg docker -c "docker exec -e PGPASSWORD='$DB_PASSWORD' $DB_CONTAINER psql -U genrxiv -d genrxiv -t -c \"SELECT count(*) FROM articles WHERE status='published';\"" 2>&1 | xargs)

echo "  Articles:  $TABLE_COUNT"
echo "  Authors:   $AUTHOR_COUNT"
echo "  Published: $PUBLISHED_COUNT"

echo ""
echo "=== Restore complete ==="
echo "Next steps:"
echo "  1. Run tests: scripts/test-after-restore.sh"
echo "  2. If tests pass, disable maintenance mode:"
echo "     scripts/maintenance.sh off"
echo "  3. Verify the site at https://genrxiv.org"
