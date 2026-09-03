#!/usr/bin/env bash
# Fail on log calls that can emit provider credentials.
#
# Xtream provider URLs carry the password in the *path* (/live/<user>/<pass>/…),
# in query parameters (get.php?username=…&password=…) and in HTTP userinfo, so
# any log call naming a URL, a request path, a header dict or a credential is a
# potential leak. This repo shipped five such calls at INFO level; they now go
# through redact_url()/redact_headers() in dispatcharr/utils.py.
#
# A line is reported when it BOTH looks like a logging call and mentions one of
# the credential-bearing expressions, AND does not mention `redact_`. That is
# the whole rule: routing the value through a redaction helper on the same line
# is what clears it.
#
# The one escape hatch is a `# credential-logging: ignore - <reason>` comment,
# modelled on the repo's `# zizmor: ignore[...]` convention. It exists for the
# lines that trip the pattern while logging no value at all — a message that
# merely names a function like get_stream_url(). Rewording a log message to
# dodge the pattern is not an acceptable alternative; take the marker and state
# why, so the exemption is reviewable.
#
# Usage:  scripts/check_credential_logging.sh <file.py> [<file.py> ...]
# Exit:   0 = no findings (or no Python files given)
#         1 = at least one finding, printed as "file:line: content"
#
# LIMITATION — physical lines only. The check greps one line at a time, so a
# logging call split across several lines is judged by the line the credential
# expression appears on. In practice that is the right granularity: a wrapped
# call has the value and its redact_url() wrapper on the same continuation
# line, so it clears; and a wrapped call that leaks has the raw expression on a
# line with no `redact_`, so it is still caught. What it cannot see is a value
# redacted several lines above and interpolated later. Rewrite such a call to
# redact at the point of use rather than working around this script.

set -uo pipefail

# Matches a logging call. Kept identical to the pattern the PostToolUse hook
# used when this check was advisory (.claude/hooks/run-affected-tests.sh).
LOG_CALL_RE='logger\.(info|debug|warning|error|exception)\('

# Expressions that can carry a provider credential. Also unchanged from the
# advisory version — widening it is a deliberate change, not a drive-by.
CREDENTIAL_RE='request\.headers|request\.META|get_full_path|\bpassword\b|api_key|\btoken\b|_url\b|url\}'

status=0

for file in "$@"; do
  case "$file" in
    *.py) ;;
    *) continue ;;
  esac
  [ -f "$file" ] || continue

  hits="$(grep -nE "$LOG_CALL_RE" "$file" 2>/dev/null \
          | grep -E "$CREDENTIAL_RE" \
          | grep -v 'redact_' \
          | grep -v 'credential-logging: ignore')" || true

  [ -n "$hits" ] || continue

  while IFS= read -r hit; do
    [ -n "$hit" ] || continue
    printf '%s:%s: %s\n' "$file" "${hit%%:*}" "${hit#*:}"
  done <<<"$hits"
  status=1
done

exit "$status"
