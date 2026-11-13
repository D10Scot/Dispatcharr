#!/usr/bin/env python3
"""Fail on log calls that can emit provider credentials.

Xtream provider URLs carry the password in the *path* (/live/<user>/<pass>/…),
in query parameters (get.php?username=…&password=…) and in HTTP userinfo, so
any log call naming a URL, a request path, a header dict or a credential is a
potential leak. This repo shipped five such calls at INFO level; they now go
through redact_url()/redact_headers() in dispatcharr/utils.py.

ONE ARGUMENT AT A TIME. A logging call is reported when any single argument
reaches the log unredacted: the argument's source, with every redact_url() /
redact_headers() call cut out of it, still matches CREDENTIAL_RE. Judging the
call as a whole would let one redacted argument clear its neighbours, so

    logger.info("%s from %s", redact_url(url), url)

is reported for its third argument. An f-string is one argument, so

    logger.info(f"{redact_url(url)} came from {url}")

is reported too, while `logger.info(f"{redact_url(url)}")` is clear.

LITERAL ARGUMENTS ARE SKIPPED: an argument with no runtime value in it — a
plain string, or an f-string with nothing interpolated — has no expression to
evaluate and so cannot carry a credential. Without that rule the check reports
message *text* that merely names something like get_stream_url(), and a guard
that flags message text trains people to reach for the ignore marker, which is
the one thing that would make the marker meaningless.

WHOLE CALLS, NOT PHYSICAL LINES. The file is parsed with `ast`, so a call
wrapped across several lines — which is what Black produces by default — is
judged as one unit. An earlier revision of this check grepped physical lines
and was blind to exactly that shape:

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
that cannot be read, decoded or parsed, produce a warning on stderr and do not
by themselves change the exit status — a file this cannot read is a problem for
whatever produced it, not a credential finding.

The one escape hatch is a `# credential-logging: ignore - <reason>` COMMENT (a
real comment token: the same words in a string or docstring clear nothing) on
any line the call spans, modelled on the repo's `# zizmor: ignore[...]`
convention. It exists for the calls that trip the pattern while logging no
credential — a presence check that names `password`, or a length taken from a
URL. Rewording a log message to dodge the pattern is not an acceptable
alternative; take the marker and state why, so the exemption is reviewable.

**The reason is required.** A bare `# credential-logging: ignore` does not
clear a call; it is reported like any other finding, with a line saying so. An
exemption nobody has to justify is not reviewable, which is the only thing that
makes this hatch safe to have.

KNOWN GAPS IN THE PATTERN. It began as the advisory grep this check replaced
(since widened with the OIDC credential names), and widening it is a deliberate change, not a drive-by — a
wider pattern would flag pre-existing calls across the whole tree and redden
unrelated pull requests. Three gaps are known and were found by reading:

  * `\bpassword\b` requires a word boundary, and `_` is a word character, so it
    misses `base_password`, `xc_password` and `transformed_password`. A call
    logging one of those variables is not reported.
  * `request.headers` is matched but `response.headers` is not, so logging a
    *provider's* response header dict — which can carry Set-Cookie — is not
    reported.
  * `_url\b` does not match `_uri`, so `request.build_absolute_uri()` — which
    returns the full request URL, credentials in the path and all — is not
    reported.

Closing them means working off the resulting backlog in one pass. Until then,
read a diff for these shapes yourself; the check will not do it for you.

BARE NAMES AND TRACE. A second pattern, NAME_RE, flags a bare `url` (`url`,
`repo.url`) and `pattern` / `*_pattern` (`search_pattern`, `flt.pattern`) in a
log argument, and `trace` is one of LOG_LEVELS beside the standard five.
NAME_RE is matched against the argument's *expressions* only, with every string
literal blanked and every redact_* call cut out, because "url" and "pattern"
are ordinary message words: `f"Generated stream url: {redact_url(u)}"` is
clear. The older CREDENTIAL_RE still reads message text, as before. M3U profile
search/replace patterns are the provider login in Xtream "simple" mode, which
is why `*_pattern` is flagged, and an M3U filter regex is no safer: it can
match a stream URL, so it can contain a login. Log a filter id, a count or a
fixed classification instead of a pattern, and reserve the marker for a call
whose arguments are visibly not a credential. The limits of this rule are the
gaps listed above, which are gaps and not claims. The whole backend source tree
is at zero findings, and tests/test_credential_logging_guard.py holds it there.

TELEMETRY CALLS (observability spec D9). The same one-argument-at-a-time rule
applies to a span, tracer, metric-instrument or meter call, because a span
attribute, an event or an instrument's attributes is an exporter sink just as
a log line is:

    span.set_attribute("url", stream_url)                  # reported
    span.set_attribute("url", redact_text(stream_url))     # clear

A call is a telemetry call when its method is one of TELEMETRY_METHODS and its
receiver's name ends in `span`, `tracer`, `counter`, `histogram`, `gauge` or
`meter` (any case: `current_span`, `self._task_histogram`). This is a lint at
the call site and nothing more. The exporter boundary
(dispatcharr/observability/redaction.py) does not depend on it, and it keeps the
blindness to `str(exception)` described below.

KNOWN LIMITS OF THE CHECK ITSELF, as opposed to its pattern:

  * It reads one call, never the statements around it. A URL redacted — or not
    redacted — into a variable on one line and logged on the next is invisible:

        message = f"fetching {server_url}"
        logger.info(message)

    Redact at the point of use rather than working around this.
  * It matches a receiver whose name ends in `logger` (`logger`, `_logger`,
    `self.logger`), which is the scope the grep it replaced had. A direct
    `logging.info(...)` on the module is not examined; the tree holds 50 of
    those today, 5 of which name a credential expression.
  * A leak reaching the log through `str(exception)` is a separate class it
    does not model at all: `requests` embeds the full URL in its exception
    text, so `logger.error(f"{e}")` around a provider fetch leaks while naming
    nothing the pattern looks for.
    core/xtream_codes.py logged `f"XC API Request failed: {str(e)}"` that way,
    and its callers logged response bodies and tracebacks, until a review (not
    this check) found them. The class now logs fixed events, counts and
    exception type names, and core/tests/test_credential_logging_url_sites.py
    pins that through its public methods; nothing mechanical stops the next
    `str(e)`. Exception-text detection is deliberately not attempted here.
  * A known CONSERVATIVE FALSE POSITIVE: a named .format field is flagged even
    when its keyword value is redacted,
    `"{search_pattern}".format(search_pattern=redact_text(p))`. The rule does
    not trace a field to its value. Pass the redacted value positionally
    (`"{}".format(redact_text(p))`) or log lazily, or use a reasoned marker.
    No call in the tree has this shape.
  * An ignore marker clears the WHOLE call, every argument in it, not only the
    one the reason names, and only when exactly one logging call spans the
    marker's line (two calls on a line, or one inside another, make it
    ambiguous and it clears neither). A marker justified by one redacted argument also
    covers an unredacted neighbour on that call; apps/timeshift/views.py has
    two such markers (a redacted URL beside a raw Content-Type and the first
    bytes of a response body; both reduced to facts since, but the hazard is the
    marker's). Read the arguments next to a marker, and keep the reason about
    the whole call.
  * NAME_RE judges a literal lookup only in these shapes: `"{0.url}".format(o)`,
    `"%(url)s" % o`, logging's lazy `logger.info("%(url)s", row)` (for an inline
    dict literal the values selected by the template keys are judged and a
    redact_* wrapper or a literal clears them; any other mapping is flagged;
    the template keys are judged by NAME_RE and CREDENTIAL_RE both, so
    `%(password)s` and `%(access_token)s` count),
    `getattr(o, "url")`, `d["url"]` and `d.get("url")`. Everything else is a
    gap, stated plainly: `format_map` (`"{url}".format_map(row)`), a starred
    lookup argument (`getattr(*(o, "url"))`), a nested format-spec field
    (`"{:{url}}".format(x, url=y)`), a template or attribute name held in a
    variable (`fmt.format(o)`, `getattr(o, name)`), `operator.attrgetter`,
    `vars(o)` and `o.__dict__` as a whole, a key-only `extra={"url": value}`
    (the key is literal text; a value that names a URL is still found), and
    logging a whole object whose `repr` carries the value
    (`logger.info("%s", profile)`).

All three are follow-ups, not gaps to work around with the ignore marker.
"""

import ast
import copy
import io
import re
import string
import sys
import tokenize

LOG_LEVELS = frozenset({"info", "debug", "warning", "error", "exception", "trace"})

# Expressions that can carry a provider credential. Began as the advisory grep in
# .claude/hooks/run-affected-tests.sh and has been widened since (the OIDC names
# below) — see KNOWN GAPS above.
CREDENTIAL_RE = re.compile(
    r"request\.headers|request\.META|get_full_path|\bpassword\b"
    r"|api_key|\btoken\b|_url\b|url\}"
    # OIDC (SSO spec 3.3): the client credential and key, every token, the PKCE verifier
    # and the nonce. \bnonce\b, not nonce: "nonces" and "nonce_hash" name no value.
    # id_token must not follow a letter or digit: "valid_token" and "invalid_token" contain
    # it and name no ID token, while "raw_id_token" does. (\b would miss that last one.)
    r"|client_secret|client_assertion|client_key|(?<![A-Za-z0-9])id_token|access_token|refresh_token"
    r"|code_verifier|\bnonce\b"
)

# Bare `url` and `pattern` / `*_pattern` names. Matched against the argument's
# expressions only, with every string literal blanked (see _expression_source):
# the words "url" and "pattern" are ordinary message text, and a rule that read
# message text would flag f"Generated stream url: {redact_url(u)}".
NAME_RE = re.compile(r"\burl\b|_pattern\b|\bpattern\b")

# redact_text and redact_exception are dispatcharr/observability/redaction.py's:
# the first scrubs a free-text body (best effort), the second reduces an
# exception to its qualified type name.
REDACT_FUNCTIONS = frozenset(
    {"redact_url", "redact_headers", "redact_text", "redact_exception"}
)

TELEMETRY_METHODS = frozenset(
    {
        "set_attribute",
        "set_attributes",
        "add_event",
        "record_exception",
        "start_as_current_span",
        "start_span",
        "set_status",
        "add",
        "record",
        "set",
    }
)

TELEMETRY_RECEIVER_SUFFIXES = ("span", "tracer", "counter", "histogram", "gauge", "meter")

IGNORE_MARKER = "credential-logging: ignore"

# What has to follow the marker for it to count: a dash (or colon) and some
# text. An exemption with no stated reason is not reviewable.
IGNORE_REASON_RE = re.compile(r"\s*[-:–—]\s*\S")

NEEDS_REASON = (
    "'# credential-logging: ignore' needs a reason "
    "('# credential-logging: ignore - <why>'); not cleared:"
)

AMBIGUOUS_MARKER = (
    "'# credential-logging: ignore' is ambiguous: more than one logging call "
    "spans its line, so it clears none of them; not cleared:"
)

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


def _is_telemetry_call(node):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in TELEMETRY_METHODS:
        return False
    owner = _logger_owner(node.func)
    return owner is not None and owner.lower().endswith(TELEMETRY_RECEIVER_SUFFIXES)


def _is_redact_call(node):
    """Whether `node` is a call to one of REDACT_FUNCTIONS (redact_url, redact_headers, redact_text, redact_exception)."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in REDACT_FUNCTIONS
    if isinstance(func, ast.Attribute):
        return func.attr in REDACT_FUNCTIONS
    return False


def _is_literal(node):
    """Whether the argument logs no runtime value.

    A plain string, or an f-string with nothing interpolated into it, cannot
    carry a credential: there is no expression in it to evaluate. That is what
    lets a message name `get_stream_url()` without tripping the check, while
    `f"{stream_url}"` still does.
    """
    return all(
        isinstance(inner, (ast.Constant, ast.JoinedStr)) for inner in ast.walk(node)
    )


def _residual_source(node):
    """The argument's source with every redact_url()/redact_headers() call cut out.

    Whatever is left is the part of the argument that reaches the log
    unredacted. Rendered with ast.unparse rather than sliced out of the file:
    the identifiers the pattern looks for survive unparsing, and expressions
    nested inside an f-string do not carry reliable source offsets on every
    Python version this runs on.
    """
    text = ast.unparse(node)
    for inner in ast.walk(node):
        if _is_redact_call(inner):
            text = text.replace(ast.unparse(inner), " ", 1)
    return text


# `%%` is an escaped percent: it consumes the percent a key would start with.
_PERCENT_KEY_RE = re.compile(r"%%|%\(([^)]*)\)")

# Calls whose first / second positional string argument names a key or
# attribute that is looked up at run time: `d.get("url")`, `getattr(o, "url")`.
_LOOKUP_METHODS = frozenset({"get", "pop", "getlist", "setdefault"})


def _format_fields(template):
    """The field names of a str.format template, e.g. ["0.search_pattern"]."""
    try:
        return [
            field
            for _, field, _, _ in string.Formatter().parse(template)
            if field
        ]
    except ValueError:
        return []


def _percent_keys(template):
    """The mapping keys of a %-template: `%(url)s` -> ["url"], `%%(url)s` -> []."""
    return [m.group(1) for m in _PERCENT_KEY_RE.finditer(template) if m.group(1)]


def _inline_mapping(node):
    """Whether `node` is a dict literal whose keys are all plain strings."""
    return isinstance(node, ast.Dict) and all(
        _is_str_constant(key) for key in node.keys
    )


def _key_flagged(key):
    """Whether a mapping key names a URL, a pattern or a credential (either rule)."""
    return bool(NAME_RE.search(key) or CREDENTIAL_RE.search(key))


def _safe_selected_entry(key, value, template_keys):
    """An inline-dict entry the template selects, by a flagged key, with a safe value."""
    return (
        key.value in template_keys
        and _key_flagged(key.value)
        and (_is_redact_call(value) or _is_literal(value))
    )


def _without_safe_entries(mapping, template_keys):
    """`mapping` (an inline dict) minus the entries `_safe_selected_entry` clears.

    Those entries carry a flagged key as literal text, which the credential rule
    would otherwise read as if it were logged; what is left is judged as usual.
    """
    kept = [
        (key, value)
        for key, value in zip(mapping.keys, mapping.values)
        if not _safe_selected_entry(key, value, template_keys)
    ]
    return ast.Dict(keys=[k for k, _ in kept], values=[v for _, v in kept])


def _unsafe_selected_keys(template_keys, mapping):
    """Template keys that name a URL, pattern or credential whose inline value is not safe.

    Only for an inline dict literal. A selected value is safe when it is a
    redact_* call or a literal; anything else keeps the conservative flag.
    Any other kind of mapping is never judged here: the caller flags it.
    """
    return [
        key.value
        for key, value in zip(mapping.keys, mapping.values)
        if key.value in template_keys
        and _key_flagged(key.value)
        and not (_is_redact_call(value) or _is_literal(value))
    ]


def _is_str_constant(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


class _Blank(ast.NodeTransformer):
    """Empty every string literal and cut out every redact_* call.

    Three literal shapes are not message text but lookups evaluated at run
    time, and keep what they name: the template of `"{0.url}".format(o)` and
    of `"%(url)s" % o` (as its field names), the attribute of `getattr(o,
    "url")` and the key of `d["url"]` / `d.get("url")`.
    """

    def __init__(self):
        self._keep = set()

    def visit_Call(self, node):
        if _is_redact_call(node):
            return ast.Constant(value="")
        func = node.func
        template_fields = None
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "format"
            and _is_str_constant(func.value)
        ):
            template_fields = " ".join(_format_fields(func.value.value))
        elif (
            isinstance(func, ast.Name) and func.id == "getattr" and len(node.args) >= 2
        ):
            self._keep.add(id(node.args[1]))
        elif (
            isinstance(func, ast.Attribute)
            and func.attr in _LOOKUP_METHODS
            and node.args
        ):
            self._keep.add(id(node.args[0]))
        self.generic_visit(node)
        if template_fields is not None:
            node.func.value = ast.Constant(value=template_fields)
        return node

    def visit_BinOp(self, node):
        fields = None
        if isinstance(node.op, ast.Mod) and _is_str_constant(node.left):
            keys = _percent_keys(node.left.value)
            if _inline_mapping(node.right):
                keys = _unsafe_selected_keys(keys, node.right)
            fields = " ".join(keys)
        self.generic_visit(node)
        if fields is not None:
            node.left = ast.Constant(value=fields)
        return node

    def visit_Subscript(self, node):
        if _is_str_constant(node.slice):
            self._keep.add(id(node.slice))
        return self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str) and id(node) not in self._keep:
            return ast.Constant(value="")
        return node


def _expression_source(node):
    """The argument's source with string literals and redact_* calls removed.

    What remains is the argument's identifiers, attributes and calls, so a
    name-based rule (NAME_RE) judges what is evaluated and not what is said.
    """
    blanked = _Blank().visit(copy.deepcopy(node))
    return ast.unparse(ast.fix_missing_locations(blanked))


def _unredacted_arguments(call):
    """Yield the arguments of `call` that reach the log unredacted."""
    arguments = list(call.args) + [keyword.value for keyword in call.keywords]
    # logging's lazy mapping form: logger.info("%(url)s", row) looks up row["url"].
    if len(call.args) > 1 and _is_str_constant(call.args[0]):
        keys = _percent_keys(call.args[0].value)
        mapping = call.args[1]
        if any(_key_flagged(key) for key in keys):
            if not _inline_mapping(mapping) or _unsafe_selected_keys(keys, mapping):
                yield mapping
            else:
                # Every flagged key is cleared by a safe value: judge the rest of the dict.
                arguments = [
                    _without_safe_entries(mapping, keys) if a is mapping else a
                    for a in arguments
                ]
    for argument in arguments:
        if _is_literal(argument):
            continue
        if CREDENTIAL_RE.search(_residual_source(argument)):
            yield argument
        elif NAME_RE.search(_expression_source(argument)):
            yield argument


def _comments_by_line(source):
    """{line number: [comment text, ...]} from the file's real COMMENT tokens.

    The marker is recognised only in a comment: the same words inside a string
    literal, a docstring or a log message clear nothing. A file that cannot be
    tokenized yields no comments, so nothing in it is cleared.
    """
    comments = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                comments.setdefault(token.start[0], []).append(token.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return {}
    return comments


def _ignore_marker(comments, first, last, spans):
    """Classify the markers on lines first..last: (marked, cleared, why_not).

    A marker clears a call only when it carries a reason AND exactly one
    logging/telemetry call (`spans`, a list of (first, last) line pairs)
    spans the marker's line. Two calls on one line, or one call inside
    another, make the comment ambiguous about which it justifies, so it clears
    neither.
    """
    marked = False
    why_not = ""
    for lineno in range(first, last + 1):
        for comment in comments.get(lineno, ()):
            index = comment.find(IGNORE_MARKER)
            if index == -1:
                continue
            marked = True
            rest = comment[index + len(IGNORE_MARKER) :]
            if not IGNORE_REASON_RE.match(rest):
                why_not = why_not or NEEDS_REASON
            elif sum(1 for lo, hi in spans if lo <= lineno <= hi) != 1:
                why_not = AMBIGUOUS_MARKER
            else:
                return True, True, ""
    return marked, False, why_not


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
    except (OSError, ValueError) as exc:
        # UnicodeDecodeError is a ValueError, not an OSError: a file that is not
        # UTF-8 must warn like any other unreadable file, not traceback.
        print(f"warning: {path}: could not read ({exc}), not checked", file=err)
        return 0

    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as exc:
        # ValueError as well as SyntaxError: ast.parse raises it for source
        # containing a null byte.
        print(f"warning: {path}: could not parse ({exc}), not checked", file=err)
        return 0

    lines = source.splitlines()
    comments = _comments_by_line(source)
    findings = []
    spans = [
        (node.lineno, getattr(node, "end_lineno", node.lineno) or node.lineno)
        for node in ast.walk(tree)
        if _is_logging_call(node) or _is_telemetry_call(node)
    ]

    for node in ast.walk(tree):
        if not (_is_logging_call(node) or _is_telemetry_call(node)):
            continue

        if not any(_unredacted_arguments(node)):
            continue

        # The marker sits on any line the call spans, including a trailing
        # comment after the closing paren, which the source segment excludes.
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        marked, cleared, why_not = _ignore_marker(comments, node.lineno, end, spans)
        if cleared:
            continue

        segment = ast.get_source_segment(source, node)
        if segment is None:
            # No position information (shouldn't happen for parsed source);
            # fall back to the call's first physical line.
            segment = lines[node.lineno - 1] if node.lineno <= len(lines) else ""

        content = _collapse(segment)
        if marked:
            content = f"{why_not} {content}"
        findings.append((node.lineno, content))

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
