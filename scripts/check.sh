#!/usr/bin/env sh
# Convenience wrapper for the commands in CONSTRAINTS.md. That file is canonical: if this script and
# its "Checked by" column disagree, the file wins and this script is the bug.
#
#   scripts/check.sh fast   after an edit       (seconds)
#   scripts/check.sh task   before handing back (under 90 s)
#
# PYTHON selects the interpreter; it defaults to the one on PATH.
set -eu
PY="${PYTHON:-python}"
stage="${1:-task}"

"$PY" -m ruff check src tests
"$PY" -m mypy
node scripts/floor-guard.mjs
[ "$stage" = "fast" ] && exit 0

"$PY" -m pytest --cov --cov-report=term-missing:skip-covered
