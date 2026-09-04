# dispatcharr/utils.py
import ipaddress
import logging
import os
import re
from urllib.parse import unquote, urlsplit, urlunsplit

from django.core.exceptions import ValidationError
from django.http import JsonResponse

from core.models import CoreSettings

logger = logging.getLogger(__name__)

# Private / loopback ranges used as the default for M3U/EPG ACLs and
# first-time superuser setup (when DISPATCHARR_SETUP_ALLOWED_IP is unset).
LOCAL_NETWORK_CIDRS = [
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]

SETUP_ALLOWED_IP_ENV = "DISPATCHARR_SETUP_ALLOWED_IP"
TRUSTED_PROXIES_ENV = "DISPATCHARR_TRUSTED_PROXIES"

# Parsed trusted-proxy networks. Rebuilt when the config key changes.
# Config key is "__default_local__", "__none__", or the raw env string.
_trusted_proxies_key = None
_trusted_proxies_networks = ()

# Sentinel values for DISPATCHARR_TRUSTED_PROXIES when explicitly disabling
# header trust (env unset still means default local CIDRs).
_TRUSTED_PROXIES_NONE = frozenset({"", "none", "off", "false", "0"})


# --------------------------------------------------------------------------
# Credential redaction
#
# Provider URLs in this project carry credentials in three places at once:
# HTTP userinfo (``http://user:pass@host``), query parameters (the Xtream
# ``get.php?username=…&password=…`` shape), and *path segments* (the Xtream
# ``/live/<user>/<pass>/<id>`` family, which dispatcharr/urls.py mounts at the
# site root). Anything that logs a request path, a stream URL or a header dict
# therefore leaks working credentials unless it goes through these helpers.
#
# Both helpers are deliberately failure-tolerant: a logging call must never be
# the thing that raises. On any doubt they return the mask rather than the
# input.
# --------------------------------------------------------------------------

REDACTED = "***"

# Query parameter names whose *values* are masked (compared case-insensitively,
# after percent-decoding the name).
SENSITIVE_QUERY_KEYS = frozenset({"password", "username", "token", "api_key"})

# Header names whose values are masked. Compared case-insensitively after
# normalising ``_`` to ``-`` and dropping a leading ``http-``, so the same set
# covers Django ``HttpHeaders`` ("Authorization") and raw ``request.META``
# ("HTTP_AUTHORIZATION") spellings.
SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "x-api-key",
        "proxy-authorization",
        "set-cookie",
    }
)

# request.META keys whose values are whole URLs or query strings, and so carry
# the Xtream path/query credentials verbatim. Masked through redact_url rather
# than blanked, because the path itself is the useful part of a request log.
# Same normalisation as SENSITIVE_HEADERS ("_" to "-", lowercased).
URL_VALUED_META_KEYS = frozenset(
    {
        "path-info",
        "query-string",
        "raw-uri",
        "request-uri",
    }
)

# Path segments after which the next two segments are the Xtream username and
# password. Matched anywhere in the path, because a provider's server URL may
# carry a sub-path before /live/ (see apps/m3u/tasks.py).
XTREAM_PATH_PREFIXES = frozenset({"live", "movie", "series", "timeshift"})

# The XC root route is `/<username>/<password>/<channel_id>` with no prefix to
# key off (dispatcharr/urls.py `xc_stream_endpoint`). It is only recognised as
# credential-bearing when the path is exactly three segments and the last looks
# like a stream id — a number with an optional extension. That shape can also
# match a non-Xtream path, in which case two harmless segments get masked;
# over-masking a log line is the safe direction of that trade.
#
# Shared with dispatcharr/urls.py's XC URL patterns (xc_stream_endpoint /
# xc_live_stream_endpoint), so the URL resolver and this redaction path can
# never disagree about what counts as a real Xtream channel id. Anchors are
# the caller's job: this file wraps it in \A...\Z, urls.py in ^...$.
XC_STREAM_ID_PATTERN = r"\d+(?:\.[A-Za-z0-9]+)?"

_XC_STREAM_ID_RE = re.compile(rf"\A{XC_STREAM_ID_PATTERN}\Z")


def _redact_netloc(netloc):
    """Replace ``user:pass@`` userinfo with the mask, keeping host and port."""
    if "@" not in netloc:
        return netloc
    _userinfo, _at, host = netloc.rpartition("@")
    return f"{REDACTED}@{host}"


def _redact_path(path):
    """Mask the credential segments of the Xtream path shapes."""
    if "/" not in path:
        return path

    segments = path.split("/")
    # Indices of the non-empty segments, so leading/trailing slashes and any
    # empty segments survive the rebuild untouched.
    filled = [i for i, seg in enumerate(segments) if seg]
    if not filled:
        return path

    changed = False

    for n, i in enumerate(filled):
        if segments[i].lower() in XTREAM_PATH_PREFIXES and n + 2 < len(filled):
            for j in (filled[n + 1], filled[n + 2]):
                if segments[j] != REDACTED:
                    segments[j] = REDACTED
                    changed = True

    if (
        not changed
        and len(filled) == 3
        and segments[filled[0]].lower() not in XTREAM_PATH_PREFIXES
        and _XC_STREAM_ID_RE.match(segments[filled[2]])
    ):
        segments[filled[0]] = REDACTED
        segments[filled[1]] = REDACTED
        changed = True

    return "/".join(segments) if changed else path


def _redact_query(query):
    """Mask the values of the sensitive query parameters, order preserved."""
    if not query:
        return query

    parts = query.split("&")
    changed = False
    for i, part in enumerate(parts):
        name, sep, _value = part.partition("=")
        if not sep:
            continue
        if name.lower() in SENSITIVE_QUERY_KEYS or unquote(name).strip().lower() in SENSITIVE_QUERY_KEYS:
            parts[i] = f"{name}={REDACTED}"
            changed = True

    return "&".join(parts) if changed else query


def redact_url(url):
    """Return ``url`` with any embedded credentials replaced by ``***``.

    Masks four carriers: HTTP userinfo, the values of the query parameters
    named in ``SENSITIVE_QUERY_KEYS``, the Xtream credential path segments
    (``/live|movie|series|timeshift/<user>/<pass>/…`` plus the bare
    ``/<user>/<pass>/<id>`` root route), and those same parameter names inside
    the fragment when the fragment is shaped like a query string (contains an
    ``=``) — the shape a client-side player uses to carry stream parameters.

    A URL with no credentials in it is returned byte-identical — the parsed
    components are only reassembled when something was actually masked, so this
    never normalises an untouched URL. Accepts relative paths such as
    ``request.get_full_path()`` as well as absolute URLs.

    Never raises. Non-string input, or input urlsplit cannot parse, returns
    ``"***"`` rather than propagating.
    """
    if not isinstance(url, str):
        return REDACTED

    try:
        parts = urlsplit(url)
        netloc = _redact_netloc(parts.netloc)
        path = _redact_path(parts.path)
        query = _redact_query(parts.query)
        fragment = _redact_query(parts.fragment) if "=" in parts.fragment else parts.fragment
        if (
            netloc == parts.netloc
            and path == parts.path
            and query == parts.query
            and fragment == parts.fragment
        ):
            return url
        return urlunsplit((parts.scheme, netloc, path, query, fragment))
    except Exception:  # noqa: BLE001 - a log call must never raise
        return REDACTED


def redact_headers(headers):
    """Return a plain dict of ``headers`` with credential values masked.

    Accepts any mapping with ``.items()`` — a Django ``HttpHeaders``, a plain
    dict, or ``request.META``. Names in ``SENSITIVE_HEADERS`` get the ``***``
    mask; every other entry is copied through unchanged.

    ``request.META`` needs more than the header set. It also carries the
    request line in ``PATH_INFO``, ``QUERY_STRING``, ``RAW_URI`` and
    ``REQUEST_URI``, and on this project those hold the Xtream path and query
    credentials verbatim — so those four go through ``redact_url`` rather than
    being copied. Name matching is normalised (``_`` to ``-``, a leading
    ``http-`` dropped), which is also what makes ``HTTP_AUTHORIZATION`` and
    friends match their ``Authorization`` header spelling.

    Never raises. Anything that is not a mapping yields an empty dict.
    """
    try:
        items = list(headers.items())
    except Exception:  # noqa: BLE001 - a log call must never raise
        return {}

    redacted = {}
    for name, value in items:
        try:
            key = str(name).strip().lower().replace("_", "-")
            if key.startswith("http-"):
                key = key[len("http-"):]
        except Exception:  # noqa: BLE001 - unusable name, assume the worst
            redacted[name] = REDACTED
            continue

        if key in SENSITIVE_HEADERS:
            redacted[name] = REDACTED
        elif key == "query-string":
            if value:
                # A bare query string is not a URL; give redact_url the "?" it
                # needs to parse it as one, then take it back off. If redact_url
                # bailed to the bare mask, keep the mask rather than slicing it.
                masked = redact_url(f"?{value}")
                redacted[name] = masked[1:] if masked.startswith("?") else masked
            else:
                redacted[name] = value
        elif key in URL_VALUED_META_KEYS:
            redacted[name] = redact_url(value)
        else:
            redacted[name] = value
    return redacted


def json_error_response(message, status=400):
    """Return a standardized error JSON response."""
    return JsonResponse({"success": False, "error": message}, status=status)


def json_success_response(data=None, status=200):
    """Return a standardized success JSON response."""
    response = {"success": True}
    if data is not None:
        response.update(data)
    return JsonResponse(response, status=status)


def validate_logo_file(file):
    """Validate uploaded logo file size and MIME type."""
    valid_mime_types = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"]
    if file.content_type not in valid_mime_types:
        raise ValidationError("Unsupported file type. Allowed types: JPEG, PNG, GIF, WebP, SVG.")
    if file.size > 5 * 1024 * 1024:  # 5MB
        raise ValidationError("File too large. Max 5MB.")


def _normalize_ip(value):
    """Parse an IP string, returning the IPv4 form for IPv4-mapped IPv6."""
    try:
        ip = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None
    return ip.ipv4_mapped if getattr(ip, "ipv4_mapped", None) else ip


def _trusted_proxy_networks():
    """Return networks whose peers may set X-Real-IP / X-Forwarded-For.

    When DISPATCHARR_TRUSTED_PROXIES is unset, defaults to LOCAL_NETWORK_CIDRS
    so Docker/Traefik-style reverse proxies on private networks work without
    configuration. Set the env to a comma-separated IP/CIDR list to narrow
    trust, or to none / off / false / empty to trust no proxy headers.
    """
    global _trusted_proxies_key, _trusted_proxies_networks

    if TRUSTED_PROXIES_ENV not in os.environ:
        key = "__default_local__"
        source = LOCAL_NETWORK_CIDRS
    else:
        raw = os.environ.get(TRUSTED_PROXIES_ENV, "").strip()
        if raw.lower() in _TRUSTED_PROXIES_NONE:
            key = "__none__"
            source = []
        else:
            key = raw
            source = [p.strip() for p in raw.split(",") if p.strip()]

    if key == _trusted_proxies_key:
        return _trusted_proxies_networks

    networks = []
    for part in source:
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.warning("Invalid %s entry %r; ignoring", TRUSTED_PROXIES_ENV, part)
    _trusted_proxies_key = key
    _trusted_proxies_networks = tuple(networks)
    return _trusted_proxies_networks


def _ip_in_trusted(ip):
    if ip is None:
        return False
    return any(ip in network for network in _trusted_proxy_networks())


def get_client_ip(request):
    """Return the client IP for ACLs and logging.

    Proxy headers (X-Real-IP, X-Forwarded-For) are honored only when
    REMOTE_ADDR is a trusted proxy. By default that means private/loopback
    peers (LOCAL_NETWORK_CIDRS). Override with DISPATCHARR_TRUSTED_PROXIES.
    Public peers never get header trust unless explicitly listed.
    IPv4-mapped IPv6 addresses are returned in IPv4 form.
    """
    peer_str = request.META.get("REMOTE_ADDR") or ""
    peer = _normalize_ip(peer_str)
    if peer is None:
        return peer_str or None
    if not _ip_in_trusted(peer):
        return str(peer)

    real_ip = _normalize_ip(request.META.get("HTTP_X_REAL_IP"))
    if real_ip is not None:
        return str(real_ip)

    xff = request.META.get("HTTP_X_FORWARDED_FOR") or ""
    for hop in reversed([h.strip() for h in xff.split(",") if h.strip()]):
        hop_ip = _normalize_ip(hop)
        if hop_ip is None:
            continue
        if not _ip_in_trusted(hop_ip):
            return str(hop_ip)

    return str(peer)


def setup_ip_allowed(request):
    """Whether this client may POST to initialize-superuser.

    Default: private / loopback IPv4 and IPv6 only.
    If DISPATCHARR_SETUP_ALLOWED_IP is set, only that single IP is allowed
    (for remote / VPS first-time web setup).

    Returns:
        tuple[bool, str]: (allowed, client_ip_string)
    """
    client_ip_str = get_client_ip(request) or ""
    compare_ip = _normalize_ip(client_ip_str)
    if compare_ip is None:
        return False, client_ip_str

    override = os.environ.get(SETUP_ALLOWED_IP_ENV, "").strip()
    if override:
        override_ip = _normalize_ip(override)
        if override_ip is None:
            logger.warning(
                "Invalid %s=%r; denying initialize-superuser POST",
                SETUP_ALLOWED_IP_ENV,
                override,
            )
            return False, client_ip_str
        return compare_ip == override_ip, client_ip_str

    for cidr in LOCAL_NETWORK_CIDRS:
        if compare_ip in ipaddress.ip_network(cidr):
            return True, client_ip_str
    return False, client_ip_str


def network_access_allowed(request, settings_key, user=None):
    network_access = CoreSettings.get_network_access_settings()
    # Set defaults based on endpoint type
    if settings_key == "M3U_EPG":
        # M3U/EPG endpoints: local IPv4 and IPv6 only by default
        default_cidrs = LOCAL_NETWORK_CIDRS
    else:
        # Other endpoints: allow all by default
        default_cidrs = ["0.0.0.0/0", "::/0"]

    cidrs = (
        network_access[settings_key].split(",")
        if settings_key in network_access
        else default_cidrs
    )

    client_ip = _normalize_ip(get_client_ip(request))
    if client_ip is None:
        return False

    network_allowed = False
    for cidr in cidrs:
        network = ipaddress.ip_network(cidr)
        if client_ip in network:
            network_allowed = True
            break

    if not network_allowed:
        return False

    if user is not None:
        user_networks = (getattr(user, 'custom_properties', None) or {}).get('allowed_networks', {})
        raw = user_networks.get(settings_key, '')
        if raw:
            for cidr in (c.strip() for c in raw.split(',') if c.strip()):
                try:
                    if client_ip in ipaddress.ip_network(cidr, strict=False):
                        return True
                except ValueError:
                    continue
            return False

    return True
