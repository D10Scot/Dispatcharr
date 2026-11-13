"""Central log scrubber for provider-supplied text.

Spec: docs/superpowers/specs/2026-11-12-log-scrubber-design.md (owner ruling R15).

``scrub_text`` masks credential carriers in free text with a deliberately blunt
per-token rule: URL userinfo is masked in place, and from the first credential
position (a sensitive key's value, an Xtream path prefix, the path of an XC root
route) to the END of the token everything is masked. It may over-mask; it must
never leave a carrier ``redact_url`` would mask, and it restores nothing it
masked. Every scan is linear, and the scan and the output are capped.

It runs at record creation, from a chained ``logging`` record factory that
the project package's ``__init__.py`` installs before anything else in the package.

This module is a stdlib-only leaf: it is imported before Django settings exist.
The only logging call in it is the constant-message WARNING in
``ensure_installed``, which is outside the factory's call graph; nothing the
factory reaches may log (``tests/test_url_redaction_leaf.py``).
"""
import io
import logging
import re
import traceback
from urllib.parse import unquote

from dispatcharr import url_redaction

MASK = url_redaction.REDACTED  # "***"
SENSITIVE_QUERY_KEYS = frozenset(url_redaction.SENSITIVE_QUERY_KEYS)
# THE KEY RULE, stated once (spec 4.3 step 2 "key", as amended after the SSO work widened
# SENSITIVE_QUERY_KEYS):
#   * CONTAINMENT, anywhere after an "=": a name containing one of exactly these four. Because
#     it is containment, id_token, access_token and refresh_token are covered by "token".
#   * EQUALITY, for every other member of SENSITIVE_QUERY_KEYS (derived here, never a second
#     hand-typed list, so a key added to the set is masked automatically): the name must equal
#     the key under redact_url's normalisation (raw lower-case, or percent-decoded, stripped,
#     lower-case) AND start immediately after "?", "&" or "#" in the raw token. Those are the
#     positions where redact_url itself masks them; containment on "code" or "state" would
#     mask status_code=, codec= and a bare state=running in ordinary lines.
# On a match the blunt rule is unchanged: mask from the value to the end of the token.
_CONTAINED_KEYS = ("username", "password", "token", "api_key")
_EQUALITY_KEYS = frozenset(
    k for k in SENSITIVE_QUERY_KEYS if not any(c in k for c in _CONTAINED_KEYS)
)
CAP = 16384
TAIL_CAP = 65536
RESERVE = 64

_TOKEN_RE = re.compile(r"\S+")
_PREFIX_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:" + "|".join(sorted(url_redaction.XTREAM_PATH_PREFIXES)) + r")/"
)
_DIGIT_RE = re.compile(r"\d")
_NAME_DELIMS = "&?#=/"
_EQUALITY_BEFORE = "?&#"
_PATHISH = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~%-/")


def _sensitive_name(name, before):
    """True when ``name`` (the text since the previous delimiter) names a credential key."""
    low = name.lower()
    dec = unquote(name).lower() if "%" in name else low
    for key in _CONTAINED_KEYS:
        if key in low or key in dec:
            return True
    if before and before in _EQUALITY_BEFORE:
        if low in _EQUALITY_KEYS or unquote(name).strip().lower() in _EQUALITY_KEYS:
            return True
    return False


def _key_tail(tok):
    """Index after the first '=' whose name names a sensitive key, or -1."""
    start = 0
    n = len(tok)
    i = 0
    while i < n:
        c = tok[i]
        if c == "=":
            name = tok[start:i]
            if name and _sensitive_name(name, tok[start - 1] if start else ""):
                return i + 1 if i + 1 < n else -1
            start = i + 1
        elif c in _NAME_DELIMS:
            start = i + 1
        i += 1
    return -1


def _prefix_tail(tok):
    for m in _PREFIX_RE.finditer(tok):
        if m.end() < len(tok):
            return m.end()
    return -1


def _root_ok(tok, p):
    """tok[p] == '/'; True when two non-empty segments then one starting with a digit follow."""
    n = len(tok)
    i = p
    segs = 0
    while i < n:
        while i < n and tok[i] == "/":
            i += 1
        if i >= n or tok[i] in "?#":
            return False
        if segs == 2:
            return bool(_DIGIT_RE.match(tok, i))
        j = i
        while j < n and tok[j] != "/" and tok[j] not in "?#":
            j += 1
        if j >= n or tok[j] in "?#":
            return False
        segs += 1
        i = j
    return False


def _authority_spans(tok):
    """Userinfo spans [a, b) after each '//' and the path start after each authority."""
    spans, path_starts = [], []
    n = len(tok)
    k = tok.find("//")
    while k != -1:
        a = k + 2
        j = a
        while j < n and tok[j] not in "/?#":
            j += 1
        at = tok.rfind("@", a, j)
        if at > a:
            spans.append((a, at))
        if j < n and tok[j] == "/":
            path_starts.append(j)
        k = tok.find("//", j if j > k + 1 else k + 1)
    return spans, path_starts


def _root_tail(tok, authority_starts):
    """authority_starts is ascending (one per '//', in order); boundary starts are found
    ascending by the scan below. The two are merged, deduplicated, without sorting."""
    n = len(tok)
    auth = iter(authority_starts)
    next_auth = next(auth, n)
    examined = 0  # starts inside an already examined run of slashes give the same answer
    i = 0
    while i < n:
        boundary = (
            tok[i] == "/" and (i == 0 or tok[i - 1] not in _PATHISH) and tok[i + 1 : i + 2] != "/"
        )
        if i == next_auth or boundary:
            if i == next_auth:
                next_auth = next(auth, n)
            if i >= examined:
                if _root_ok(tok, i):
                    return i + 1
                examined = i
                while examined < n and tok[examined] == "/":
                    examined += 1
        i += 1
    return -1


def scrub_token(tok):
    spans, path_starts = _authority_spans(tok)
    tails = [t for t in (_key_tail(tok), _prefix_tail(tok), _root_tail(tok, path_starts)) if t != -1]
    tail = min(tails) if tails else len(tok)
    kept = []
    for a, b in spans:
        if a >= tail:
            continue
        if b >= tail:
            tail = a
            continue
        kept.append((a, b))
    if not kept and tail == len(tok):
        return tok
    out, pos = [], 0
    for a, b in kept:
        if a < pos:  # overlapping spans cannot occur (authorities are disjoint), defensive
            continue
        out.append(tok[pos:a])
        out.append(MASK)
        pos = b
    out.append(tok[pos:tail])
    if tail < len(tok):
        out.append(MASK)
    return "".join(out)


def _scan(text):
    if "/" not in text and "=" not in text:
        return text
    out, last = [], 0
    for m in _TOKEN_RE.finditer(text):
        tok = m.group()
        if "/" in tok or "=" in tok:
            s = scrub_token(tok)
            if s != tok:
                out.append(text[last : m.start()])
                out.append(s)
                last = m.end()
    if not out:
        return text
    out.append(text[last:])
    return "".join(out)


_SPACE_RE = re.compile(r"\s")  # the same predicate as _TOKEN_RE's \S


def _cut_head(text, n_original):
    limit = CAP - RESERVE
    cut = -1
    for m in _SPACE_RE.finditer(text, 0, limit + 1):
        cut = m.start()
    kept = text[:cut] if cut > 0 else ""
    return kept + f" [log scrubber: truncated from {n_original} characters]"


def scrub_text(text):
    n = len(text)
    src = _cut_head(text, n) if n > CAP else text
    out = _scan(src)
    if len(out) > CAP:
        out = _cut_head(out, n)
    return out


def _cut_tail(text, n_original):
    m = _SPACE_RE.search(text, len(text) - (TAIL_CAP - RESERVE))
    kept = text[m.start() :] if m else ""
    return f"[log scrubber: truncated from {n_original} characters]" + kept


def scrub_tail(text):
    n = len(text)
    src = _cut_tail(text, n) if n > TAIL_CAP else text
    out = _scan(src)
    if len(out) > TAIL_CAP:
        out = _cut_tail(out, n)
    return out


# ---------------------------------------------------------------------------
# The record step. Nothing below logs, and nothing below raises into the caller.


def _message_placeholder(reason, exc):
    return f"<log message withheld: {reason} ({type(exc).__qualname__})>"


def _traceback_placeholder(exc):
    return f"<traceback withheld: scrubber failed ({type(exc).__qualname__})>"


def _stack_placeholder(exc):
    return f"<stack withheld: scrubber failed ({type(exc).__qualname__})>"


def _format_exception(exc_info):
    """What ``logging.Formatter.formatException`` produces."""
    sio = io.StringIO()
    traceback.print_exception(exc_info[0], exc_info[1], exc_info[2], None, sio)
    text = sio.getvalue()
    if text[-1:] == "\n":
        text = text[:-1]
    return text


def _scrub_message(record):
    try:
        message = record.getMessage()
    except Exception as exc:  # noqa: BLE001 - withhold; never let logging's own error dump print the raw arguments
        record.msg = _message_placeholder("formatting failed", exc)
        record.args = ()
        return
    try:
        scrubbed = scrub_text(message)
    except Exception as exc:  # noqa: BLE001
        record.msg = _message_placeholder("scrubber failed", exc)
        record.args = ()
        return
    if scrubbed != message:
        # args=() so a scrubbed message containing "%" is never re-formatted.
        record.msg = scrubbed
        record.args = ()


def _scrub_traceback(record):
    try:
        cached = getattr(record, "exc_text", None)
        if cached:
            record.exc_text = scrub_tail(cached)
            return
        exc_info = getattr(record, "exc_info", None)
        if isinstance(exc_info, tuple) and len(exc_info) == 3 and exc_info[0] is not None:
            record.exc_text = scrub_tail(_format_exception(exc_info))
    except Exception as exc:  # noqa: BLE001
        record.exc_text = _traceback_placeholder(exc)


def _scrub_stack(record):
    try:
        stack = getattr(record, "stack_info", None)
        if stack:
            record.stack_info = scrub_tail(stack)
    except Exception as exc:  # noqa: BLE001
        record.stack_info = _stack_placeholder(exc)


def _withhold_everything(record, exc):
    """Plain assignment of constant-shaped strings, which cannot itself fail."""
    record.msg = _message_placeholder("scrubber failed", exc)
    record.args = ()
    if getattr(record, "exc_info", None) or getattr(record, "exc_text", None):
        record.exc_text = _traceback_placeholder(exc)
    if getattr(record, "stack_info", None):
        record.stack_info = _stack_placeholder(exc)


def _scrub_record(record):
    try:
        _scrub_message(record)
        _scrub_traceback(record)
        _scrub_stack(record)
    except Exception as exc:  # noqa: BLE001 - the scrubber adds no raise path
        try:
            _withhold_everything(record, exc)
        except Exception:  # noqa: BLE001, S110 - last resort, nothing left to do
            pass


# ---------------------------------------------------------------------------
# Installation


def install():
    """Wrap the current record factory in a scrubbing closure. False if already outermost."""
    current = logging.getLogRecordFactory()
    if getattr(current, "__mino_log_scrubber__", False):
        return False
    # TEST-ONLY. tests/log_scrub_rig.py's unscrubbed_logging() installs a pass-through factory
    # carrying this attribute so that discover_plugins' ensure_installed() cannot re-arm the
    # scrubber inside a block that deliberately runs without it. Nothing outside tests/ may
    # set it (tests/test_log_scrub_install.py enforces that).
    if getattr(current, "__mino_log_scrubber_test_bypass__", False):
        return False

    def factory(*args, _previous=current, **kwargs):
        record = _previous(*args, **kwargs)  # a raise here propagates, as it does without the scrubber
        _scrub_record(record)  # never raises
        return record

    factory.__mino_log_scrubber__ = True
    factory.__mino_log_scrubber_previous__ = current  # read only by the test rig
    logging.setLogRecordFactory(factory)
    return True


def ensure_installed():
    """``install()`` plus one constant-message WARNING when a foreign factory had replaced ours."""
    if install():
        logging.getLogger(__name__).warning(
            "the log record factory was replaced; the log scrubber has been re-installed around it"
        )
        return True
    return False
