#!/bin/bash
# Copies the canonical shared/session_parser.py byte-for-byte into every Cloud
# Function deployment directory that depends on it, then verifies (sha256) all
# copies are identical to the canonical file. Run this before every deploy of
# cloud_function/ or cloud_function_sync/ -- never hand-edit the copies.
set -euo pipefail
cd "$(dirname "$0")/.."

CANONICAL="shared/session_parser.py"
TARGETS=("cloud_function/session_parser.py" "cloud_function_sync/session_parser.py")

if [ ! -f "$CANONICAL" ]; then
    echo "FATAL: canonical file $CANONICAL not found" >&2
    exit 1
fi

for t in "${TARGETS[@]}"; do
    mkdir -p "$(dirname "$t")"
    cp "$CANONICAL" "$t"
done

CANON_SHA=$(shasum -a 256 "$CANONICAL" | awk '{print $1}')
echo "canonical sha256: $CANON_SHA"
FAIL=0
for t in "${TARGETS[@]}"; do
    SHA=$(shasum -a 256 "$t" | awk '{print $1}')
    if [ "$SHA" != "$CANON_SHA" ]; then
        echo "MISMATCH: $t ($SHA)" >&2
        FAIL=1
    else
        echo "OK: $t"
    fi
done

if [ "$FAIL" -ne 0 ]; then
    echo "FATAL: one or more copies do not match the canonical file" >&2
    exit 1
fi
echo "All copies verified identical to canonical."
