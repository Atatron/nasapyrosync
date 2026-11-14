#!/usr/bin/env bash
# Import FIRMS CSV files, ZIP archives or folders from the command line (macOS/Linux).
# Examples:
#   ./scripts/import.sh ~/Downloads/indonesia.zip
#   ./scripts/import.sh --dry-run new_data/            # inspect only
#   ./scripts/import.sh data.csv --declare 2025-01-01 2025-03-31   # declare the requested interval
# Run ./scripts/start.sh once first (it creates .venv). Stop the server first or import while it runs
# via the browser (Data & Methods → Import): the database allows one writer process at a time.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGS=()
for a in "$@"; do
  if [ -e "$a" ]; then ARGS+=("$(cd "$(dirname "$a")" && pwd)/$(basename "$a")"); else ARGS+=("$a"); fi
done
cd "$ROOT/backend"
exec "$ROOT/.venv/bin/python" -m pyrosync.cli import "${ARGS[@]}"
