#!/usr/bin/env bash
# Run every backend test label under coverage, one process per label, then
# combine. Invoked through scripts/ci_bootstrap_backend.sh (CI_BACKEND_RUNNER)
# so Postgres/Redis are already up and PATH has /dispatcharrpy/bin.
#
# Per-label processes on purpose: CI runs each label in its own container and
# the full in-process run has a history of order-dependent failures
# (CLAUDE.md, Testing). Redis is flushed between labels for the same reason
# the local hook does it. A failed label is recorded, not fatal: the row
# still carries the combined coverage plus the list of labels that failed.
set -uo pipefail
OUT=/tmp/dispatcharr-coverage
rm -rf "$OUT"; mkdir -p "$OUT"

LABELS_JSON="$(FULL_SUITE=1 python scripts/ci_backend_test_labels.py < /dev/null)"
mapfile -t LABELS < <(python -c 'import json,sys; print("\n".join(json.load(sys.stdin)))' <<< "$LABELS_JSON")
echo "coverage over ${#LABELS[@]} labels"

FAILED=()
for L in "${LABELS[@]}"; do
  redis-cli -p "${REDIS_PORT:-6379}" flushall >/dev/null 2>&1 || true
  if ! python -m coverage run --rcfile=.coveragerc -p manage.py test --keepdb "$L" -v1; then
    echo "::warning::label $L failed under coverage"
    FAILED+=("$L")
  fi
done

python -m coverage combine --rcfile=.coveragerc || exit 1
python -m coverage json --rcfile=.coveragerc -o "$OUT/backend-coverage.json" || exit 1
python -m coverage report --rcfile=.coveragerc | tail -3

python - "$OUT/backend-status.json" "${LABELS[@]}" -- "${FAILED[@]}" <<'PY'
import json, sys
argv = sys.argv[1:]
out = argv[0]
split = argv.index("--")
labels, failed = argv[1:split], argv[split + 1:]
json.dump({"labels": labels, "failed_labels": failed}, open(out, "w"))
PY
echo "failed labels: ${FAILED[*]:-none}"
exit 0
