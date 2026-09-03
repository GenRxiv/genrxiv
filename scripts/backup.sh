#!/bin/sh
# GenRxiv backup script
#
# Backs up:
#   - PostgreSQL database (pg_dump, gzipped)
#   - Article files volume (tar, gzipped)
#   - SQLite signups database
#
# Uploads to Backblaze B2 via rclone, with 30-day retention.
#
# Usage:
#   scripts/backup.sh          # run backup
#   scripts/backup.sh --dry-run # show what would be uploaded
#
# Cron (nightly at 3am):
#   0 3 * * * /home/curator/genrxiv/scripts/backup.sh >> /home/curator/genrxiv/deploy/backup/backup.log 2>&1

set -eu

# --- Configuration ---
REPO_DIR="/home/curator/genrxiv"
RCLONE="${RCLONE:-$HOME/.local/bin/rclone}"
ENV_FILE="$REPO_DIR/.env"
BACKUP_DIR="$REPO_DIR/deploy/backup/local"
RETENTION_DAYS=30
DATE=$(date +%Y%m%d-%H%M%S)
HOST=$(hostname -s)

# --- Load env ---
if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
fi

B2_BUCKET="${B2_BUCKET:-genrxiv-backups}"
B2_KEY_ID="${B2_KEY_ID:-}"
B2_KEY="${B2_KEY:-}"

if [ -z "$B2_KEY_ID" ] || [ -z "$B2_KEY" ]; then
    echo "[$DATE] ERROR: B2_KEY_ID and B2_KEY must be set in .env"
    exit 1
fi

if [ ! -x "$RCLONE" ]; then
    echo "[$DATE] ERROR: rclone not found at $RCLONE"
    exit 1
fi

# --- rclone config (generated at runtime, not stored) ---
export RCLONE_CONFIG=/tmp/rclone-genrxiv.conf
cat > "$RCLONE_CONFIG" <<EOF
[b2]
type = b2
account = $B2_KEY_ID
key = $B2_KEY
EOF

mkdir -p "$BACKUP_DIR"

echo "[$DATE] Starting GenRxiv backup"

# --- 1. PostgreSQL dump ---
echo "[$DATE] Dumping PostgreSQL..."
DB_PASSWORD="${DB_PASSWORD:-}"
DB_CONTAINER="deploy-db-1"

sg docker -c "docker exec -e PGPASSWORD='$DB_PASSWORD' $DB_CONTAINER pg_dump -U genrxiv -d genrxiv --no-owner --clean --if-exists" | gzip > "$BACKUP_DIR/genrxiv-db-$DATE.sql.gz"

DB_SIZE=$(du -h "$BACKUP_DIR/genrxiv-db-$DATE.sql.gz" | cut -f1)
echo "[$DATE] PostgreSQL dump: $DB_SIZE"

# --- 2. Article files volume ---
echo "[$DATE] Archiving article files volume..."
sg docker -c "docker run --rm -v genrxiv_article_files:/data:ro alpine tar czf - -C /data ." > "$BACKUP_DIR/article-files-$DATE.tar.gz" 2>/dev/null || echo "[$DATE] WARNING: Could not archive article files volume"

FILES_SIZE=$(du -h "$BACKUP_DIR/article-files-$DATE.tar.gz" | cut -f1)
echo "[$DATE] Article files archive: $FILES_SIZE"

# --- 3. SQLite signups ---
echo "[$DATE] Copying SQLite signups..."
sg docker -c "docker cp deploy-convert-1:/data/signups.db $BACKUP_DIR/signups-$DATE.db" 2>/dev/null || echo "[$DATE] WARNING: Could not copy signups.db"

# --- 4. Upload to B2 ---
REMOTE_PATH="b2:$B2_BUCKET/$HOST/$DATE"

if [ "${1:-}" = "--dry-run" ]; then
    echo "[$DATE] Dry run — would upload to $REMOTE_PATH"
    "$RCLONE" copy "$BACKUP_DIR" "$REMOTE_PATH" --dry-run 2>&1
else
    echo "[$DATE] Uploading to $REMOTE_PATH..."
    "$RCLONE" copy "$BACKUP_DIR" "$REMOTE_PATH" --progress 2>&1
    echo "[$DATE] Upload complete"
fi

# --- 5. Prune old local backups ---
echo "[$DATE] Pruning local backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -type f -mtime +$RETENTION_DAYS -delete
echo "[$DATE] Local cleanup done"

# --- 6. Prune old remote backups ---
echo "[$DATE] Pruning remote backups older than $RETENTION_DAYS days..."
if [ "${1:-}" = "--dry-run" ]; then
    "$RCLONE" delete "b2:$B2_BUCKET/$HOST" --min-age ${RETENTION_DAYS}d --dry-run 2>&1
else
    "$RCLONE" delete "b2:$B2_BUCKET/$HOST" --min-age ${RETENTION_DAYS}d 2>&1
fi
echo "[$DATE] Remote cleanup done"

# --- Cleanup rclone config ---
rm -f "$RCLONE_CONFIG"

echo "[$DATE] Backup complete"
