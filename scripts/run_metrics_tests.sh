#!/usr/bin/env bash
# Run the metrics unit tests: the collector suite (scripts/metrics/tests) and
# the build-step suite (metrics/build/tests). Both are plain unittest and need
# neither Django nor a database. Used by the PostToolUse hook, the commit
# gate and lint.yml, so the three can never disagree about what "passing" is.
#
# Interpreter: the project venv when present (it carries PyYAML), else python3.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
WHICH="${1:-all}"
status=0

run_suite() {
  local start="$1" top="$2"
  if [ ! -d "$start" ]; then
    echo "missing metrics test suite: $start" >&2
    return 1
  fi
  "$PY" -m unittest discover -s "$start" -t "$top" -v 2>&1 | tail -25
  return "${PIPESTATUS[0]}"
}

case "$WHICH" in
  collectors|build|all) ;;
  *) echo "usage: $0 [collectors|build|all]" >&2; exit 2 ;;
esac

# Both suites now exist and are non-empty, so a missing directory or an empty
# collection (unittest's own rc 5, "NO TESTS RAN", Python 3.12+) are both
# failures rather than a not-yet-populated-package pass.
if [ "$WHICH" = collectors ] || [ "$WHICH" = all ]; then
  run_suite scripts/metrics/tests scripts/metrics; rc=$?
  [ $rc -eq 0 ] || status=1
fi

if [ "$WHICH" = build ] || [ "$WHICH" = all ]; then
  run_suite metrics/build/tests metrics/build; rc=$?
  [ $rc -eq 0 ] || status=1
fi

exit $status
