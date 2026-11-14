#!/usr/bin/env bash
# Assemble the folder that is uploaded to the Hugging Face Docker Space (used by .github/workflows/hf-space.yml).
#   deploy/hf/build_space.sh OUT_DIR
# To refresh the data first (after a new local import):
#   .venv/bin/python deploy/build_demo_db.py --from-db data/pyrosync.duckdb --out /tmp/full.duckdb
#   sha256sum /tmp/full.duckdb | cut -c1-64 > deploy/hf/db/pyrosync-full.duckdb.sha256
#   rm deploy/hf/db/*.part-*; xz -6 -T0 -c /tmp/full.duckdb | split -b 70m -d -a 2 - deploy/hf/db/pyrosync-full.duckdb.xz.part-
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:?output folder}"
rm -rf "$OUT"; mkdir -p "$OUT/backend" "$OUT/frontend" "$OUT/data"
cp -r "$ROOT/backend/pyrosync" "$OUT/backend/"
find "$OUT/backend" -name __pycache__ -prune -exec rm -rf {} +
cp -r "$ROOT/frontend/dist" "$OUT/frontend/"
cp "$ROOT/deploy/hf/db/"pyrosync-full.duckdb.* "$OUT/data/"
cp "$ROOT/requirements.txt" "$OUT/requirements.txt"
cp "$ROOT/deploy/hf/Dockerfile" "$OUT/Dockerfile"
cp "$ROOT/deploy/hf/SPACE_README.md" "$OUT/README.md"
echo "Ready: $OUT"
