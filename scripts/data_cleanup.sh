#!/usr/bin/env bash
# Delete archived session data from the output log.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DB="${1:-$PROJECT_DIR/state/output.db}"

if [ ! -f "$DB" ]; then
    echo "Database not found: $DB"
    exit 1
fi

sqlite3 "$DB" <<'SQL'
select archived, count(*) from chunks group by archived;

PRAGMA trusted_schema = ON;
DELETE FROM chunks WHERE archived = 1;
VACUUM;

select archived, count(*) from chunks group by archived;
SQL

echo "Cleanup complete: $DB"
