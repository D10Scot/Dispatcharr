#!/usr/bin/env python3
"""Fail on log calls that can emit provider credentials.

Xtream provider URLs carry the password in the *path* (/live/<user>/<pass>/…),
in query parameters (get.php?username=…&password=…) and in HTTP userinfo, so
any log call naming a URL, a request path, a header dict or a credential is a
potential leak. This repo shipped five such calls at INFO level; they now go
through redact_url()/redact_headers() in dispatcharr/utils.py.

A logging call is reported when its source mentions one of the credential
expressions in CREDENTIAL_RE and does not call redact_url() or redact_headers().
That is the whole rule: routing the value through a redaction helper is what
clears the call.

WHOLE CALLS, NOT PHYSICAL LINES. The file is parsed with `ast`, so a call
wrapped across several lines — which is what Black produces by default — is
judged as one joined unit. An earlier revision of this check grepped physical
lines and was blind to exactly that shape:

    logger.info(
        f"[VOD-HEAD] Making request to provider: {final_stream_url}"
    )

the first line matched "is a logging call" and the second matched "mentions a
URL", but neither line matched both, so the call was never examined.

Usage:  scripts/check_credential_logging.py <file.py> [<file.py> ...]
Exit:   0 = no findings (or no Python files given)
        1 = at least one finding, printed as "file:line: content"

`content` is the call's source collapsed onto one line and truncated at 200
characters; `line` is the line the call starts on. Files that do not exist, or
that cannot be read or parsed, produce a warning on stderr and do not by
themselves change the exit status — a file this cannot read is a problem for
whatever produced it, not a credential finding.

The one escape hatch is a `# credential-logging: ignore - <reason>` comment on
any line the call spans, modelled on the repo's `# zizmor: ignore[...]`
convention. It exists for the calls that trip the pattern while logging no
value at all — a message that merely names a function like get_stream_url().
Rewording a log message to dodge the pattern is not an acceptable alternative;
take the marker and state why, so the exemption is reviewable.

KNOWN GAPS IN THE PATTERN. It is inherited verbatim from the advisory grep this
check replaced, and widening it is a deliberate change, not a drive-by — a
wider pattern would flag pre-existing calls across the whole tree and redden
unrelated pull requests. Two gaps are known and were found by reading:

  * `\bpassword\b` requires a word boundary, and `_` is a word character, so it
    misses `base_password`, `xc_password` and `transformed_password`. A call
    logging one of those variables is not reported.
  * `request.headers` is matched but `response.headers` is not, so logging a
    *provider's* response header dict — which can carry Set-Cookie — is not
    reported.

Closing them means working off the resulting backlog in one pass. Until then,
read a diff for these two shapes yourself; the check will not do it for you.
"""

import ast
import re
import sys

LOG_LEVELS = frozenset({"info", "debug", "warning", "error", "exception"})

# Expressions that can carry a provider credential. Inherited verbatim from the
# advisory grep in .claude/hooks/run-affected-tests.sh — see KNOWN GAPS above.
CREDENTIAL_RE = re.compile(
    r"request\.headers|request\.META|get_full_path|\bpassword\b"
    r"|api_key|\btoken\b|_url\b|url\}"
)

# Anchored to a real call, so a `# redact_url` comment or a string mentioning
# redact_url cannot clear a line.
REDACT_RE = re.compile(r"\bredact_(?:url|headers)\(")

IGNORE_MARKER = "credential-logging: ignore"

MAX_REPORTED_CHARS = 200


def _logger_owner(func):
    """Return the receiver name of a `<owner>.<attr>(...)` call, or None."""
    owner = func.value
    if isinstance(owner, ast.Name):
        return owner.id
    if isinstance(owner, ast.Attribute):
        return owner.attr
    return None


def _is_logging_call(node):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in LOG_LEVELS:
        return False
    owner = _logger_owner(node.func)
    # `logger`, `_logger`, `self.logger` — the grep this replaced matched any
    # identifier ending in "logger", and narrowing that would drop coverage.
    return owner is not None and owner.endswith("logger")


def _collapse(text):
    collapsed = " ".join(text.split())
    if len(collapsed) > MAX_REPORTED_CHARS:
        collapsed = collapsed[:MAX_REPORTED_CHARS] + " ..."
    return collapsed


def check_file(path, out=sys.stdout, err=sys.stderr):
    """Print every unredacted logging call in `path`. Return the finding count."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
    except FileNotFoundError:
        print(f"warning: {path}: no such file, not checked", file=err)
        return 0
    except OSError as exc:
        print(f"warning: {path}: could not read ({exc}), not checked", file=err)
        return 0

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        print(f"warning: {path}: could not parse ({exc}), not checked", file=err)
        return 0

    lines = source.splitlines()
    findings = []

    for node in ast.walk(tree):
        if not _is_logging_call(node):
            continue

        segment = ast.get_source_segment(source, node)
        if segment is None:
            # No position information (shouldn't happen for parsed source);
            # fall back to the call's first physical line.
            segment = lines[node.lineno - 1] if node.lineno <= len(lines) else ""

        if not CREDENTIAL_RE.search(segment):
            continue
        if REDACT_RE.search(segment):
            continue

        # The marker sits on any line the call spans, including a trailing
        # comment after the closing paren, which the source segment excludes.
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        spanned = "\n".join(lines[node.lineno - 1 : end])
        if IGNORE_MARKER in spanned:
            continue

        findings.append((node.lineno, _collapse(segment)))

    for lineno, content in sorted(findings):
        print(f"{path}:{lineno}: {content}", file=out)

    return len(findings)


def main(argv):
    total = 0
    for path in argv:
        if not path.endswith(".py"):
            continue
        total += check_file(path)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
