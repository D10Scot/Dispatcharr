"""Xtream credentials out of Django's own request log records.

Django writes ``Unauthorized: <request.path>`` (and ``Not Found``, ``Bad
Request``, ``Internal Server Error`` ...) for every 4xx/5xx response through
the ``django.request`` logger, ``Forbidden (<reason>): <path>`` through
``django.security.csrf``, a ``SuspiciousOperation``'s text and traceback
through ``django.security.<ExceptionName>``, and one line per request through
the development servers' loggers. On this project the Xtream routes carry a
user's login in the path (``/live|movie|series|timeshift/<user>/<pass>/...``
and the bare ``/<user>/<pass>/<id>``) or the query string (``player_api.php``,
``get.php``, ``xmltv.php``, ``streaming/timeshift.php``), so those lines leak
working credentials. ``scripts/check_credential_logging.py`` cannot see them:
the log calls are inside Django.

``RequestLogCredentialFilter`` hands its handler a *copy* of each record from
``REDACTED_LOGGER_TREES`` with the credentials masked in the message template,
every string argument and the formatted traceback, and with the attached
``request`` object dropped. Two passes do the masking: by pattern (the Xtream
path shapes and sensitive query keys, wherever they appear) and by value (the
username, password and sensitive query values the attached request itself
names, in their decoded, percent-encoded and unicode-escaped spellings, at
least ``MIN_SCRUBBED_VALUE_LENGTH`` characters long), so a credential in a
form or position the patterns miss is still removed. Both passes read the
text as it is, never decoded and never another pass's output: each mask is a
range of that text, and the union of the ranges is applied once
(``_render``). The one exception is a message and its string arguments:
the arguments are masked first, then the rendered message (``_redact_message``). A
path the pattern pass cannot read plainly (one holding ``%`` or a
backslash) is logged as ``/***``. The original record is never mutated (a
filter returning a record replaces it for that handler only, Python 3.12+). Records
outside the trees pass through as themselves, and no record is suppressed: an
operator still sees that a 401 happened and on which route
(``/movie/***/***/1.mp4``).

The path shapes are not defined here. Every string goes through the project
package's ``utils.redact_url``, whose ``XTREAM_PATH_PREFIXES`` and
``XC_STREAM_ID_PATTERN`` (the latter shared with the urlconf) are the single
definition; ``tests/test_request_log_redaction.py`` fails if a urlconf pattern
capturing a username and a password is one that definition does not cover.

``with_request_log_redaction(LOGGING)`` puts the filter on EVERY handler a
record from these trees can reach, so there is no route around it:

* ``console`` and ``otel`` on the root, which every propagating record reaches,
  including the per-exception ``django.security.<Name>`` loggers that cannot
  be enumerated in advance;
* the ``django`` and ``django.server`` loggers' handlers, re-declared exactly
  as Django's ``DEFAULT_LOGGING`` declares them (same classes, filters, levels,
  formatter) plus this filter. Without that, ``django``'s ``console`` (which
  writes when ``settings.DEBUG`` is true) and the ``django.server`` handler
  would be handlers this configuration never names and so cannot filter. The
  re-declared names are prefixed ``django.`` because ``console`` is taken.

``tests/test_request_log_redaction.py`` walks the configured logger tree and
fails if any handler reachable from these loggers lacks the filter.

This module is imported while settings load, so it imports nothing from
``apps.*`` or ``core.models`` at module level.
"""
import copy
import logging
import re
from urllib.parse import quote, unquote, urlsplit

# Loggers whose records are redacted, matched as the name itself or a dotted
# descendant. ``django.channels.server`` is the request line of the
# ``runserver`` this project actually runs (Daphne's, since ``daphne`` is in
# INSTALLED_APPS); ``django.server`` is Django's own.
REDACTED_LOGGER_TREES = (
    "django.request",
    "django.security",
    "django.server",
    "django.channels.server",
)

FILTER_NAME = "request_log_credentials"

# Characters stripped from either end of a whitespace-delimited token before
# it is treated as a URL: quoting and bracketing from reprs and tracebacks.
_TOKEN_PUNCTUATION = "'\"<>()[]{},;"
_TOKEN_RE = re.compile(r"\S+")
# Sentence punctuation stripped from the end of a token only.
_TRAILING_PUNCTUATION = ".:"
# ``path=/user/pass/1.ts``, ``"path":"/user/pass/1.ts"``, ``url=http://h/...``:
# a key, then a separator, then a path or a URL. ``=`` (quoted or not) is
# always a separator. ``:`` is one only when it cannot be a URL scheme's own
# colon: after a quoted key (``"path"://...``), before a quote, before a single
# ``/`` (``key:/u/p/1``), or before another scheme (``url:http://...``). An
# unquoted ``word:`` followed by ``//`` is the scheme of an absolute URL
# (``http://h/u/p/1``), which goes to ``redact_url`` whole, so its host stays a
# host and its userinfo is masked. A bare path that starts ``//`` has no key
# and is not affected.
_KEY_PREFIX_RE = re.compile(
    r"""[A-Za-z_][\w.-]*"""
    r"""(?:["']?=["']?|["']:["']?|:["']|:(?!//))"""
    r"""(?=/|[A-Za-z][A-Za-z0-9+.-]*://)"""
)
_QUERY_OR_FRAGMENT_RE = re.compile(r"[?#]")
# A URL scheme, and where an authority ends.
_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_AUTHORITY_END_RE = re.compile(r"[/?#]")
_PATH_START_RE = re.compile(r"[/\\?#]")
# A path holding either of these is not read at all (see _slash_ranges).
_OPAQUE_PATH_RE = re.compile(r"[%\\]")
_SPACE_RE = re.compile(r"\s")

# A credential shorter than this is not scrubbed by value: replacing every
# occurrence of a one- to three-character string would shred unrelated text
# (a one-letter password would mask that letter everywhere). Its path and
# query positions are still masked by pattern.
MIN_SCRUBBED_VALUE_LENGTH = 4


def _in_scope(name):
    return any(name == tree or name.startswith(tree + ".") for tree in REDACTED_LOGGER_TREES)


def _utils():
    # Lazy: the project package's utils imports core.models, which cannot
    # load while settings are still being read.
    from dispatcharr import utils

    return utils


# A mask is a range of the text it was computed from: (start, end, opaque).
# Every structural decision (where a token, a path, an authority, a query or a
# fragment starts and ends, which segments exist) is taken from the text as
# it is, and every mask is a range of that same text. No step reads another
# step's output, so masks only ever add: _render applies their union once.


def _render(text, ranges):
    """``text`` with the union of ``ranges`` masked.

    Overlapping or touching ranges become one ``***``; a group holding an
    opaque range (a path that is not read) becomes ``/***``. A range may be
    empty (an empty query value), which inserts the mask.
    """
    if not ranges:
        return text
    redacted = _utils().REDACTED
    groups = []
    for start, end, opaque in sorted(ranges):
        if groups and start <= groups[-1][1]:
            groups[-1][1] = max(groups[-1][1], end)
            groups[-1][2] = groups[-1][2] or opaque
        else:
            groups.append([start, end, opaque])
    out, pos = [], 0
    for start, end, opaque in groups:
        out += [text[pos:start], "/" + redacted if opaque else redacted]
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _segment_spans(text):
    """(start, end) of each item of ``text.split("/")``."""
    spans, start = [], 0
    for segment in text.split("/"):
        spans.append((start, start + len(segment)))
        start += len(segment) + 1
    return spans


def _masked_segments(text, start):
    """Indices of ``text.split("/")`` that ``_redact_path`` masks reading from segment ``start``."""
    utils = _utils()
    read = [""] + text.split("/")[start + 1:]
    masked = utils._redact_path("/".join(read)).split("/")
    return {start + i for i, (was, now) in enumerate(zip(read, masked)) if was != now}


def _path_ranges(text, start, end, base):
    """The segments of ``text[start:end]`` (a URL's path) that ``redact_url`` masks."""
    path = text[start:end]
    masked = _utils()._redact_path(path).split("/")
    return [
        (base + start + a, base + start + b, False)
        for (a, b), was, now in zip(_segment_spans(path), path.split("/"), masked)
        if was != now
    ]


def _query_ranges(text, start, end, base):
    """The values of the sensitive pairs in ``text[start:end]``, as ``redact_url`` masks them."""
    redact_query = _utils()._redact_query
    ranges = []
    while True:
        amp = text.find("&", start, end)
        stop = end if amp < 0 else amp
        part = text[start:stop]
        if redact_query(part) != part:
            ranges.append((base + start + part.index("=") + 1, base + stop, False))
        if amp < 0:
            return ranges
        start = amp + 1


def _tail_ranges(text, start, base):
    """``text[start:]`` starts ``?`` or ``#``: its query and query-shaped fragment."""
    ranges = []
    fragment = start
    if text[start] == "?":
        fragment = text.find("#", start + 1)
        fragment = len(text) if fragment < 0 else fragment
        ranges += _query_ranges(text, start + 1, fragment, base)
    # As redact_url does: a fragment shaped like a query string is masked too.
    if fragment < len(text) and "=" in text[fragment + 1:]:
        ranges += _query_ranges(text, fragment + 1, len(text), base)
    return ranges


def _slash_ranges(text, base=0):
    """The masks of ``text``, which starts with ``/`` (or ``\\``): a path, its query and fragment.

    Nothing is decoded and no reading is chosen over another:

    1. after a leading ``//``, userinfo (an ``@`` before the next ``/``,
       ``?`` or ``#``, with no whitespace) is masked up to the last ``@``;
    2. text holding a ``%`` or a backslash anywhere, query and fragment
       included, is not interpreted: all of it becomes ``/***``, because what
       the server routes is its decoded form, and ``request.path`` is decoded,
       so a ``?`` or ``#`` in it can belong to a credential and what follows
       can be the rest of the route;
    3. otherwise every segment the raw Xtream masks hit is masked, reading the
       whole text and the path alone (``request.path`` is decoded, so a ``?``
       in it can belong to a credential), each from the first segment and,
       after a leading ``//`` in text with no whitespace, also from the
       segment after the host, as ``redact_url`` reads it;
    4. the sensitive keys after the first ``?`` or ``#`` of the text are
       masked, and also after the first one outside the segments step 3
       masks (a ``?`` or ``#`` in a decoded credential is not where the
       query starts). Both are located in the text itself, and both are kept.
    """
    ranges = []
    read = text
    if text.startswith("//") and not text.startswith("///"):
        stop = _AUTHORITY_END_RE.search(text, 2)
        authority = text[2:stop.start() if stop else len(text)]
        if "@" in authority and not _SPACE_RE.search(authority):
            ranges.append((base + 2, base + 2 + authority.rindex("@"), False))
            # The host alone is read in step 3 (a userinfo-free authority has
            # no "/", so the segment indices are the text's own).
            read = "//" + authority.rpartition("@")[2] + text[2 + len(authority):]
    if _OPAQUE_PATH_RE.search(read):
        return [(base, base + len(text), True)]
    end = _QUERY_OR_FRAGMENT_RE.search(read)
    head = read[:end.start()] if end else read
    starts = (0, 2) if read.startswith("//") and not _SPACE_RE.search(read) else (0,)
    masked = set()
    for reading in (read, head):
        for start in starts:
            masked |= _masked_segments(reading, start)
    spans = _segment_spans(text)
    ranges += [(base + spans[i][0], base + spans[i][1], False) for i in masked]
    tails, segment, counted = [], 0, 0
    for found in _QUERY_OR_FRAGMENT_RE.finditer(text):
        if not tails:
            tails.append(found.start())
        segment += text.count("/", counted, found.start())
        counted = found.start()
        if segment not in masked:
            if found.start() != tails[0]:
                tails.append(found.start())
            break
    for start in tails:
        ranges += _tail_ranges(text, start, base)
    return ranges


# What urlsplit strips from the start of a URL before reading it.
_URL_LEADING_JUNK = "".join(chr(code) for code in range(0x21))


def _url_ranges(core, base):
    """The masks of a token that is not a bare path: ``redact_url``'s, then ``_slash_ranges``'s.

    ``redact_url``'s masks (userinfo, the Xtream path, the sensitive query and
    fragment keys) are located in the token itself through ``urlsplit``. A
    token ``urlsplit`` refuses is masked whole, as ``redact_url`` masks it.
    When the token has a scheme, its own path from the first ``/`` (or, after
    ``//``, ``\\``) is also read as a bare path.
    """
    whole = [(base, base + len(core), False)]
    try:
        parts = urlsplit(core)
    except Exception:  # noqa: BLE001 - redact_url answers "***" here
        return whole
    at = len(core) - len(core.lstrip(_URL_LEADING_JUNK))
    if parts.scheme:
        at += len(parts.scheme) + 1
    netloc = None
    if core.startswith("//", at):
        netloc, at = at + 2, at + 2 + len(parts.netloc)
    path = at
    at += len(parts.path)
    query = fragment = None
    if core.startswith("?", at):
        query, at = at + 1, at + 1 + len(parts.query)
    if core.startswith("#", at):
        fragment, at = at + 1, at + 1 + len(parts.fragment)
    if at != len(core) or core[path:path + len(parts.path)] != parts.path:
        return whole  # urlsplit read the token in a way it cannot be located in
    ranges = []
    if netloc is not None and "@" in parts.netloc:
        ranges.append((base + netloc, base + netloc + parts.netloc.rindex("@"), False))
    ranges += _path_ranges(core, path, path + len(parts.path), base)
    if query is not None:
        ranges += _query_ranges(core, query, query + len(parts.query), base)
    if fragment is not None and "=" in parts.fragment:
        ranges += _query_ranges(core, fragment, len(core), base)
    scheme = _SCHEME_RE.match(core)
    if scheme:
        at, leads = scheme.end(), "/"
        if core.startswith("//", at):
            found = _PATH_START_RE.search(core, at + 2)
            at, leads = (found.start() if found else len(core)), "/\\"
        if core[at:at + 1] and core[at] in leads:
            ranges += _slash_ranges(core[at:], base + at)
    return ranges


def _token_ranges(text):
    """The masks of every whitespace-delimited token of ``text``, each read on its own."""
    ranges = []
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0)
        start = len(token) - len(token.lstrip(_TOKEN_PUNCTUATION))
        core = token[start:].rstrip(_TOKEN_PUNCTUATION + _TRAILING_PUNCTUATION)
        if not core:
            continue
        base = match.start() + start
        keyed = _KEY_PREFIX_RE.match(core)
        if keyed:
            base, core = base + keyed.end(), core[keyed.end():]
        if core.startswith("/"):
            ranges += _slash_ranges(core, base)
        else:
            ranges += _url_ranges(core, base)
    return ranges


def _pattern_ranges(text):
    """The masks of ``text``: whole, when it is a path, and token by token."""
    ranges = []
    if text.startswith("/"):
        ranges = _slash_ranges(text)
        if ranges and ranges[0][2]:
            return ranges  # all of it is "/***"
    return ranges + _token_ranges(text)


def redact_text(text):
    """Mask the Xtream credentials in every URL or path inside ``text``.

    A string that is itself a path (it starts with ``/``: ``request.path`` in
    Django's own arguments) is read whole, so a credential containing a space,
    ``?`` or ``#`` is still one segment. Every whitespace-delimited token is
    also read on its own, which catches a URL or a path inside a request line
    or a traceback. Both readings are of ``text`` itself, and the union of
    their masks is applied. Non-strings are returned as they are.
    """
    if not isinstance(text, str) or not text:
        return text
    return _render(text, _pattern_ranges(text))


def _spellings(value):
    """The value as decoded, percent-encoded (two ways) and unicode-escaped.

    Django unicode-escapes the string arguments of django.request records;
    a raw request line carries the percent-encoded form.
    """
    forms = {
        value,
        unquote(value),
        quote(value, safe=""),
        quote(value),
        value.encode("unicode_escape").decode("ascii"),
    }
    return {form for form in forms if len(form) >= MIN_SCRUBBED_VALUE_LENGTH}


def _request_credentials(request):
    """The credential values the request itself names: route kwargs and query."""
    values = set()
    match = getattr(request, "resolver_match", None)
    kwargs = getattr(match, "kwargs", None) or {}
    for key in ("username", "password"):
        if isinstance(kwargs.get(key), str):
            values.add(kwargs[key])
    try:
        # Parsing the query string can raise (TooManyFieldsSent on a request
        # with more fields than DATA_UPLOAD_MAX_NUMBER_FIELDS, the very event
        # django.security logs): the record must still be emitted, redacted by
        # pattern, so a failure here only costs the by-value pass for the query.
        query = getattr(request, "GET", None)
        if query is not None:
            for key in query:
                if key.lower() in _utils().SENSITIVE_QUERY_KEYS:
                    values.update(v for v in query.getlist(key) if isinstance(v, str))
    except Exception:  # noqa: BLE001
        pass
    spelled = set()
    for value in values:
        if len(value) >= MIN_SCRUBBED_VALUE_LENGTH:
            spelled |= _spellings(value)
    return sorted(spelled, key=len, reverse=True)


def _value_ranges(text, values):
    """Every occurrence of every listed value in ``text``, as found in ``text`` itself."""
    ranges = []
    for value in values:
        at = text.find(value)
        while at >= 0:
            ranges.append((at, at + len(value), False))
            at = text.find(value, at + len(value))
    return ranges


def _redact(text, values):
    """``text`` with the union of the pattern masks and the value masks applied."""
    if not isinstance(text, str) or not text:
        return text
    return _render(text, _pattern_ranges(text) + _value_ranges(text, values))


def _redact_message(record, values):
    """The rendered message with its masks applied: (original, redacted).

    Each string argument is masked first, read whole and token by token on
    its own (a path whose credential holds a space is one segment only
    there), and the message rendered from the masked arguments is masked
    again as a whole, which adds the masks of text a template glues to an
    argument. This is the one place one pass reads another's output. It can
    only add masks: every credential inside an argument is masked from the
    argument's own text before the message is read, and a mask (``***``)
    holds no character the message pass keys on.
    """
    original = record.getMessage()
    probe = copy.copy(record)
    if isinstance(record.args, dict):
        probe.args = {key: _redact(value, values) for key, value in record.args.items()}
    elif isinstance(record.args, tuple):
        probe.args = tuple(_redact(value, values) for value in record.args)
    return original, _redact(probe.getMessage(), values)


def redact_record(record):
    """A redacted copy of ``record``, or ``record`` itself when out of scope."""
    if not _in_scope(record.name):
        return record
    # django.request and django.security attach the HttpRequest, whose repr
    # (and path, GET and META) carry the credentials. No configured handler
    # needs it; AdminEmailHandler, the one Django handler that reads it,
    # tolerates its absence. django.server's ``request`` is the socket.
    from django.http import HttpRequest

    request = getattr(record, "request", None)
    http_request = request if isinstance(request, HttpRequest) else None

    # The values the request itself names as credentials (route kwargs and
    # sensitive query keys), in every spelling: scrubbed from the message,
    # the arguments and the traceback in addition to the pattern pass, so a
    # credential in a form or position the patterns miss is still removed.
    values = _request_credentials(http_request) if http_request is not None else []

    clone = copy.copy(record)
    # Render the message, then mask the rendered text: a template can carry a
    # credential at a %s position, an argument need not be a string, and a
    # value can straddle the template and an argument. A message that cannot
    # render raises here and is withheld by the filter. When nothing changes
    # the template and the arguments are kept as they are; otherwise the
    # masked text is stored with no arguments, which every formatter renders
    # unchanged.
    original, redacted = _redact_message(record, values)
    if redacted != original:
        clone.msg = redacted
        clone.args = ()
    if record.exc_info and record.exc_info[0] is not None:
        text = record.exc_text or logging.Formatter().formatException(record.exc_info)
        clone.exc_text = _redact(text, values)
    elif record.exc_text:
        clone.exc_text = _redact(record.exc_text, values)
    if record.stack_info:
        clone.stack_info = _redact(record.stack_info, values)
    if http_request is not None:
        del clone.request
    return clone


class RequestLogCredentialFilter(logging.Filter):
    """Pass every record on; in-scope ones as a redacted copy."""

    def filter(self, record):
        try:
            return redact_record(record)
        except Exception:  # noqa: BLE001 - a log call must never raise
            # Fail closed on the content, open on the record: the operator
            # still learns that something was logged, and from where. A
            # message whose % formatting fails when it is rendered for the
            # value scrub lands here too, which keeps logging's own
            # "--- Logging error ---" dump of the raw arguments off stderr.
            return _withheld(record)


_WITHHELD = "[request log record withheld: redaction failed]"


def _withheld(record):
    try:
        clone = copy.copy(record)
        clone.msg = _WITHHELD
        clone.args = ()
        clone.exc_info = None
        clone.exc_text = None
        clone.stack_info = None
        if "request" in vars(clone):
            del clone.request
        return clone
    except Exception:  # noqa: BLE001 - not even the copy may raise here
        return logging.LogRecord(
            str(getattr(record, "name", "django")),
            getattr(record, "levelno", logging.ERROR),
            "",
            0,
            _WITHHELD,
            (),
            None,
        )


def _attach(handler_config):
    attached = handler_config.setdefault("filters", [])
    if FILTER_NAME not in attached:
        attached.append(FILTER_NAME)


def with_request_log_redaction(logging_config):
    """Return ``logging_config`` with the filter wired in (see module docstring)."""
    from django.utils.log import DEFAULT_LOGGING

    cfg = copy.deepcopy(logging_config)
    filters = cfg.setdefault("filters", {})
    filters[FILTER_NAME] = {"()": f"{__name__}.RequestLogCredentialFilter"}
    formatters = cfg.setdefault("formatters", {})
    handlers = cfg.setdefault("handlers", {})
    loggers = cfg.setdefault("loggers", {})

    for name in ("console", "otel"):
        if name in handlers:
            _attach(handlers[name])

    # Re-declare DEFAULT_LOGGING's two request-path loggers and their handlers.
    for logger_name in ("django", "django.server"):
        if logger_name in loggers:
            continue  # the configuration already declares it; leave it alone
        declared = copy.deepcopy(DEFAULT_LOGGING["loggers"][logger_name])
        renamed = []
        for handler_name in declared.get("handlers", []):
            own = f"django.{handler_name}" if not handler_name.startswith("django.") else handler_name
            handler = copy.deepcopy(DEFAULT_LOGGING["handlers"][handler_name])
            for filter_name in handler.get("filters", []):
                filters.setdefault(filter_name, copy.deepcopy(DEFAULT_LOGGING["filters"][filter_name]))
            formatter = handler.get("formatter")
            if formatter:
                formatters.setdefault(formatter, copy.deepcopy(DEFAULT_LOGGING["formatters"][formatter]))
            _attach(handler)
            handlers[own] = handler
            renamed.append(own)
        declared["handlers"] = renamed
        loggers[logger_name] = declared
    return cfg
