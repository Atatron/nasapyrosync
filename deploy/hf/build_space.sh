#!/usr/bin/env bash
# Assemble a folder ready to push to a Hugging Face Docker Space (git + git-lfs).
#   deploy/hf/build_space.sh /path/to/full/pyrosync.duckdb OUT_DIR
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC_DB="${1:?path to the full local pyrosync.duckdb}"
OUT="${2:?output folder}"
mkdir -p "$OUT/backend" "$OUT/frontend" "$OUT/data"
"$ROOT/.venv/bin/python" "$ROOT/deploy/build_demo_db.py" --from-db "$SRC_DB" --out "$OUT/data/pyrosync-full.duckdb"
rm -rf "$OUT/backend/pyrosync" && cp -r "$ROOT/backend/pyrosync" "$OUT/backend/" && find "$OUT/backend" -name __pycache__ -prune -exec rm -rf {} +
rm -rf "$OUT/frontend/dist" && cp -r "$ROOT/frontend/dist" "$OUT/frontend/"
cp "$ROOT/requirements.txt" "$OUT/requirements.txt"
cp "$ROOT/deploy/hf/Dockerfile" "$OUT/Dockerfile"
cp "$ROOT/deploy/hf/SPACE_README.md" "$OUT/README.md"
printf '*.duckdb filter=lfs diff=lfs merge=lfs -text\n' > "$OUT/.gitattributes"
echo "Ready: $OUT  (push it to the Space with git and git-lfs)"
