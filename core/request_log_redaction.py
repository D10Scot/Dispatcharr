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
form or position the patterns miss is still removed. The original record is never mutated (a filter
returning a record replaces it for that handler only, Python 3.12+). Records
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
# A URL scheme and the end of an authority, as urlsplit reads them.
_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_AUTHORITY_END_RE = re.compile(r"[/?#]")

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


def _redact_url(value):
    return _utils().redact_url(value)


def _mask_path(path):
    """Mask the credential segments of a string that is wholly a path.

    Segments are masked directly, never through ``urlsplit``: a path that
    starts ``//`` would be read as a host and its first segment lost, and a
    decoded ``?`` or ``#`` inside a credential would end the path early. A
    path with percent-escapes is also tried decoded, because the server
    decodes ``/%6dovie/...`` and ``/movie%2Fu%2Fp%2F1`` before routing; the
    decoded form is returned only when it is the one that carried a match.
    """
    redact_path = _utils()._redact_path
    masked = redact_path(path)
    if masked != path:
        return masked
    if "%" in path:
        decoded = "/".join(unquote(part) for part in path.split("/"))
        masked = redact_path(decoded)
        if masked != decoded:
            return masked
    return path


def _redact_tail(rest):
    """``rest`` empty or starting ``?`` or ``#``: masked as ``redact_url`` masks them."""
    redact_query = _utils()._redact_query
    if rest.startswith("?"):
        query, hash_, fragment = rest[1:].partition("#")
        rest = "?" + redact_query(query)
    else:
        hash_, fragment, rest = rest[:1], rest[1:], ""
    # As redact_url does: a fragment shaped like a query string is masked too.
    if "=" in fragment:
        fragment = redact_query(fragment)
    return rest + hash_ + fragment


def _redact_absolute(core):
    """A token that does not start with ``/``: ``redact_url``, and one more path reading.

    ``redact_url`` is the baseline and its masks are never given up. When it
    leaves a URL's path unmasked, the path is read again, and only the path
    text of the result changes; the userinfo, query and fragment are masked
    exactly as ``redact_url`` masks them and the parts are joined as strings,
    so nothing decoded is parsed again (a decoded ``?`` stays in the path).
    The second reading is ``_mask_path``, which also tries the path decoded
    (``http://h/%6dovie/<user>/<pass>/1``). When that finds nothing and the
    host (after any userinfo) cannot be a host, it is tried once more over the
    host and the path together: the host is an Xtream prefix
    (``error://live/<user>/<pass>/abc``), or decodes to one or to text with a
    ``/`` in it (``word://movie%2F<user>%2F<pass>%2F1``). Only then: reading
    every host as a path would mask the host of ``http://h/a/5``, and
    ``path://<user>/<pass>/1.ts`` is spelled exactly like that URL, so it
    stays as it is. The readings are tried in that fixed order and the first
    that masks anything is used; results are never compared with each other.
    """
    baseline = _redact_url(core)
    utils = _utils()
    scheme = _SCHEME_RE.match(core)
    if not scheme:
        return baseline
    rest = core[scheme.end():]
    authority = None
    if rest.startswith("//"):
        stop = _AUTHORITY_END_RE.search(rest, 2)
        stop = stop.start() if stop else len(rest)
        authority, rest = rest[2:stop], rest[stop:]
    end = _QUERY_OR_FRAGMENT_RE.search(rest)
    path, tail = (rest[:end.start()], rest[end.start():]) if end else (rest, "")
    try:
        parts = urlsplit(core)
    except ValueError:
        return baseline
    # The split above must be the one redact_url made, or the masks it
    # applied could land on different text.
    query, _, fragment = tail[1:].partition("#") if tail.startswith("?") else ("", "", tail[1:])
    if (parts.netloc, parts.path, parts.query, parts.fragment) != (authority or "", path, query, fragment):
        return baseline
    if utils._redact_path(path) != path:
        return baseline
    _userinfo, at, host = (authority or "").rpartition("@")
    decoded_host = unquote(host)
    host_can_be_path = bool(host) and (
        decoded_host.lower() in utils.XTREAM_PATH_PREFIXES or "/" in decoded_host
    )
    read_host = False
    masked = _mask_path(path)
    if masked == path and host_can_be_path:
        read_host = True
        masked = _mask_path("//" + host + path)[2:]
        if masked == host + path:
            return baseline
    elif masked == path:
        return baseline
    out = core[:scheme.end()]
    if authority is not None:
        # The userinfo is masked whenever there is one, as redact_url masks it.
        out += "//" + (utils.REDACTED + "@" if at else "")
        out += masked if read_host else host + masked
    else:
        out += masked
    return out + _redact_tail(tail)


def _redact_core(core):
    """One token with its quoting stripped: a path, a ``key=path`` or a URL."""
    prefix = ""
    keyed = _KEY_PREFIX_RE.match(core)
    if keyed:
        prefix, core = core[:keyed.end()], core[keyed.end():]
    if not core.startswith("/"):
        return prefix + _redact_absolute(core)
    end = _QUERY_OR_FRAGMENT_RE.search(core)
    head, rest = (core[:end.start()], core[end.start():]) if end else (core, "")
    return prefix + _mask_path(head) + _redact_tail(rest)


def _redact_token(match):
    token = match.group(0)
    start = len(token) - len(token.lstrip(_TOKEN_PUNCTUATION))
    core = token[start:].rstrip(_TOKEN_PUNCTUATION + _TRAILING_PUNCTUATION)
    if not core:
        return token
    redacted = _redact_core(core)
    if redacted == core:
        return token
    return token[:start] + redacted + token[start + len(core):]


def redact_text(text):
    """Mask the Xtream credentials in every URL or path inside ``text``.

    A string that is itself a path (it starts with ``/``: ``request.path`` in
    Django's own arguments) is masked whole first, so a credential containing
    a space, ``?`` or ``#`` is still one segment. Every whitespace-delimited
    token is then masked on its own, which catches a URL or a path inside a
    request line or a traceback. Non-strings are returned as they are.
    """
    if not isinstance(text, str) or not text:
        return text
    if text.startswith("/"):
        text = _mask_path(text)
    return _TOKEN_RE.sub(_redact_token, text)


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


def _scrub_values(text, values):
    """Replace every listed value in ``text``; longest first, so no fragment survives."""
    if not isinstance(text, str):
        return text
    for value in values:
        text = text.replace(value, _utils().REDACTED)
    return text


def _redact_traceback(text, values):
    return _scrub_values(redact_text(text), values)


def _redact_args(args):
    if isinstance(args, dict):
        return {key: redact_text(value) for key, value in args.items()}
    if isinstance(args, tuple):
        return tuple(redact_text(value) for value in args)
    return args


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
    # value can straddle the template and an argument. String arguments are
    # masked first, as the whole paths they usually are, so the escaping a
    # credential needs survives. A message that cannot render raises here and
    # is withheld by the filter. When nothing changes the template and the
    # arguments are kept as they are; otherwise the masked text is stored with
    # no arguments, which every formatter renders unchanged.
    probe = copy.copy(record)
    probe.args = _redact_args(record.args)
    original = record.getMessage()
    redacted = _scrub_values(redact_text(probe.getMessage()), values)
    if redacted != original:
        clone.msg = redacted
        clone.args = ()
    if record.exc_info and record.exc_info[0] is not None:
        text = record.exc_text or logging.Formatter().formatException(record.exc_info)
        clone.exc_text = _redact_traceback(text, values)
    elif record.exc_text:
        clone.exc_text = _redact_traceback(record.exc_text, values)
    if record.stack_info:
        clone.stack_info = _redact_traceback(record.stack_info, values)
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
