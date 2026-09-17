#!/bin/bash
# Copies the canonical shared/session_parser.py byte-for-byte into every Cloud
# Function deployment directory that depends on it, then verifies (sha256) all
# copies are identical to the canonical file. Wired into the Makefile as a hard
# prerequisite of every deploy target (Rune review, 2026-09-17) -- this is no
# longer a manual step someone has to remember; `make deploy-*` cannot reach
# `gcloud functions deploy` unless this script exits 0.
#
# If a deployed copy differs from canonical BEFORE this script runs (e.g.
# someone hand-edited cloud_function/session_parser.py directly, thinking
# that was the source of truth), this is silently self-healing by design --
# whatever gets deployed is always the canonical content, never a stale copy
# -- but that drift is NOT swallowed silently: it's diffed and reported loudly
# before being corrected, so the person who made the edit finds out their
# change didn't survive rather than discovering it later via mismatched
# behavior between the two functions.
set -euo pipefail
cd "$(dirname "$0")/.."

CANONICAL="shared/session_parser.py"
TARGETS=("cloud_function/session_parser.py" "cloud_function_sync/session_parser.py")

if [ ! -f "$CANONICAL" ]; then
    echo "FATAL: canonical file $CANONICAL not found" >&2
    exit 1
fi

CANON_SHA=$(shasum -a 256 "$CANONICAL" | awk '{print $1}')
echo "canonical sha256: $CANON_SHA"

for t in "${TARGETS[@]}"; do
    mkdir -p "$(dirname "$t")"
    if [ -f "$t" ]; then
        PRE_SHA=$(shasum -a 256 "$t" | awk '{print $1}')
        if [ "$PRE_SHA" != "$CANON_SHA" ]; then
            MSG="$(date -u +%Y-%m-%dT%H:%M:%SZ) DRIFT: $t differed from canonical (sha256 $PRE_SHA, canonical $CANON_SHA) -- overwritten. Edit shared/session_parser.py instead."
            echo "WARNING: $MSG" >&2
            # [Rune re-check MINOR] a terminal-only warning is only ever seen
            # by whoever happens to be watching when this runs. Durable trace
            # so a drift event is discoverable later, not just in that one
            # terminal's scrollback.
            echo "$MSG" >> "$(dirname "$0")/.parser_drift_log.txt"
        fi
    fi
    cp "$CANONICAL" "$t"
done

FAIL=0
for t in "${TARGETS[@]}"; do
    SHA=$(shasum -a 256 "$t" | awk '{print $1}')
    if [ "$SHA" != "$CANON_SHA" ]; then
        echo "MISMATCH: $t ($SHA) -- copy failed" >&2
        FAIL=1
    else
        echo "OK: $t"
    fi
done

if [ "$FAIL" -ne 0 ]; then
    echo "FATAL: one or more copies could not be synced to the canonical file" >&2
    exit 1
fi
echo "All copies verified identical to canonical."
