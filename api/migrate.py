"""
GenRxiv migration runner.

Applies numbered SQL migration files from the migrations/ directory.
Tracks applied migrations in the schema_migrations table.

Usage:
    python -m api.migrate              # Apply all pending migrations
    python -m api.migrate --status     # Show migration status
    python -m api.migrate --rollback N # Roll back migration N (not implemented)

Migrations are forward-only. For rollbacks, write a new migration that
reverses the change (e.g., 003_rollback_002.sql).

Migration files must be named: NNN_description.sql (e.g., 001_init.sql).
They are applied in numeric order.
"""
import os
import re
import sys
from pathlib import Path

from db import get_conn, init_pool


MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MIGRATION_PATTERN = re.compile(r"^(\d+)_(.+)\.sql$")


def list_migrations():
    """List all migration files sorted by number."""
    migrations = []
    if not MIGRATIONS_DIR.exists():
        return migrations
    for path in MIGRATIONS_DIR.glob("*.sql"):
        match = MIGRATION_PATTERN.match(path.name)
        if match:
            num = int(match.group(1))
            name = match.group(2)
            migrations.append((num, name, path))
    migrations.sort(key=lambda m: m[0])
    return migrations


def applied_migrations():
    """Return set of applied migration IDs."""
    with get_conn().connection() as conn:
        # Check if schema_migrations table exists
        row = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'schema_migrations')"
        ).fetchone()
        if not row["exists"]:
            return set()
        rows = conn.execute("SELECT id FROM schema_migrations").fetchall()
        return {r["id"] for r in rows}


def apply_migration(num: int, name: str, path: Path):
    """Apply a single migration file."""
    sql = path.read_text(encoding="utf-8")
    with get_conn().connection() as conn:
        # Run the migration SQL and record it in a transaction
        conn.execute(sql)
        conn.execute(
            "INSERT INTO schema_migrations (id, name) VALUES (%s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            (num, name),
        )
        conn.commit()
    print(f"  Applied {num:03d}_{name}.sql")


def run_migrations():
    """Apply all pending migrations."""
    init_pool()
    migrations = list_migrations()
    if not migrations:
        print("No migration files found.")
        return 0

    applied = applied_migrations()
    pending = [(n, name, path) for n, name, path in migrations if n not in applied]

    if not pending:
        print(f"All {len(migrations)} migrations already applied.")
        return 0

    print(f"Applying {len(pending)} pending migration(s)...")
    for num, name, path in pending:
        apply_migration(num, name, path)

    print(f"Done. {len(pending)} migration(s) applied.")
    return 0


def migration_status():
    """Show migration status."""
    init_pool()
    migrations = list_migrations()
    applied = applied_migrations()

    if not migrations:
        print("No migration files found.")
        return 0

    print(f"{'ID':>4}  {'Name':<40}  Status")
    print(f"{'─' * 4}  {'─' * 40}  {'─' * 8}")
    for num, name, path in migrations:
        status = "applied" if num in applied else "pending"
        print(f"{num:4d}  {name:<40}  {status}")

    pending_count = sum(1 for n, _, _ in migrations if n not in applied)
    print(f"\n{len(migrations)} total, {len(applied)} applied, {pending_count} pending")
    return 0


def main():
    if "--status" in sys.argv:
        sys.exit(migration_status())
    sys.exit(run_migrations())


if __name__ == "__main__":
    main()
