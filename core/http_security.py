"""Shared helpers for safer outbound HTTP fetches (SSRF prevention)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import idna
import requests
from urllib3.util import parse_url


def validate_outbound_http_url(
    url: str,
    *,
    allow_private: bool = False,
    allow_loopback: bool = False,
) -> None:
    """Raise ValueError if *url* must not be fetched.

    Only ``http`` and ``https`` are allowed. After DNS resolution, addresses
    that are link-local, reserved, unspecified, or multicast are always
    rejected. Loopback and RFC1918-style private addresses are rejected
    unless explicitly allowed via *allow_loopback* / *allow_private*.

    Image proxies typically set ``allow_private=True`` so LAN-hosted artwork
    still works, while plugin installs keep the stricter default.
    """
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        # A netloc containing a character that NFKC-normalises to '@', ':',
        # '/', '?' or '#' (e.g. fullwidth U+FF20) makes urlparse itself
        # raise, and its message echoes the whole netloc verbatim --
        # userinfo included. This is the one refusal path the rest of this
        # function's "name only a bare hostname" discipline doesn't reach,
        # because it fires before there is a parsed URL to take a hostname
        # from.
        raise ValueError("URL could not be parsed and is refused.") from exc
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"URL scheme '{parsed.scheme}' is not allowed; only http and https are permitted."
        )
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname.")

    # requests (via urllib3) does not parse a URL's authority the same way
    # urlparse does, and encodes an internationalised hostname before
    # dialling it. `http://127.0.0.1:8765\@public.example/` is read by
    # urlparse as host 'public.example' (everything after the last '@' in
    # the netloc), but requests' own URL preparation treats the backslash as
    # ending the authority, and urllib3 -- what requests actually uses to
    # open the connection -- resolves host '127.0.0.1'. Validating urlparse's
    # host alone would pass a URL that dials somewhere else entirely, on any
    # hop: refuse outright on a literal backslash in the authority, and cross
    # check against the host urllib3 will actually dial.
    #
    # Messages below name only the two hostnames involved -- never the full
    # URL, netloc, userinfo, query string or a caught exception's text, all
    # of which can carry a credential and none of which
    # scripts/check_credential_logging.py can see inside a raised
    # ValueError's message once it reaches a response body or a log line.
    if "\\" in parsed.netloc:
        raise ValueError("URL authority contains a backslash and is refused.")

    # A non-ASCII host is IDNA-encoded before it is dialled -- not by
    # requests itself, but by urllib3.util.url._normalize_host inside
    # parse_url (urllib3 2.7's _idna_encode, strict std3 rules per label),
    # which runs before requests' own prepare_url() ever sees the host.
    # Mirror that with the same `idna` package (uts46=True), so an
    # internationalised domain compares equal against the encoded form
    # instead of being falsely refused as "a different host"; where uts46
    # mapping and urllib3's stricter per-label rules would disagree (e.g. a
    # fullwidth letter), urllib3 refuses first and the prepare()/parse_url
    # call below turns that into the same ValueError.
    if hostname.isascii():
        urlparse_dial_host = hostname.lower()
    else:
        try:
            urlparse_dial_host = idna.encode(hostname, uts46=True).decode("ascii").lower()
        except idna.IDNAError as exc:
            raise ValueError("URL host contains an invalid label and is refused.") from exc

    try:
        prepared_url = requests.Request("GET", url).prepare().url
        dialled_host = (parse_url(prepared_url).host or "").strip("[]").lower()
    except Exception as exc:
        # Both requests' own prepare_url() and this second, independent
        # parse_url(prepared_url) call can raise (urllib3's LocationParseError
        # carries the whole URL it was given, userinfo included, as its
        # message -- int(port) raising on an out-of-range port is one way
        # in). Whichever of the two raises, the same fixed message applies;
        # neither the URL nor the caught exception's text is safe to surface.
        raise ValueError("URL could not be prepared for a request and is refused.") from exc
    if dialled_host != urlparse_dial_host:
        raise ValueError(
            f"URL host '{urlparse_dial_host}' would dial a different host "
            f"('{dialled_host}'); refused."
        )
    hostname = dialled_host

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname '{hostname}': {exc}") from exc

    if not infos:
        raise ValueError(f"Could not resolve hostname '{hostname}'.")

    saw_ip = False
    for _family, _type, _proto, _canon, sockaddr in infos:
        addr_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        saw_ip = True

        # Classify loopback/private carefully:
        # link-local (including cloud metadata 169.254.0.0/16) must stay blocked
        # even when allow_private is set, because Python marks it is_private too.
        if ip.is_loopback:
            if not allow_loopback:
                raise ValueError(
                    f"URL resolves to a non-routable address ({addr_str}) and cannot be fetched."
                )
            continue
        if ip.is_unspecified or ip.is_multicast or ip.is_link_local:
            raise ValueError(
                f"URL resolves to a non-routable address ({addr_str}) and cannot be fetched."
            )
        if ip.is_private:
            if not allow_private:
                raise ValueError(
                    f"URL resolves to a non-routable address ({addr_str}) and cannot be fetched."
                )
            continue
        if ip.is_reserved:
            raise ValueError(
                f"URL resolves to a non-routable address ({addr_str}) and cannot be fetched."
            )

    if not saw_ip:
        raise ValueError(f"Could not resolve hostname '{hostname}' to an IP address.")


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# Stripped from a hop's kwargs the moment a redirect crosses an origin
# boundary (see _crosses_origin below) -- at least as strict as requests'
# own Session.should_strip_auth for its built-in redirect handling, and
# identical for `auth`/Authorization. For Cookie and Proxy-Authorization
# requests is stricter still: resolve_redirects() pops Cookie on every hop
# and re-derives it from the cookie jar, and rebuild_proxies() re-derives
# Proxy-Authorization from the proxy URL, so requests never carries either
# forward even within the same origin. This helper only drops them on an
# origin change, which is safe (same host, scheme and port keep the same
# trust boundary) but is not the same promise -- a future caller passing a
# Cookie header should not read this as "requests-equivalent" for that
# header. No current caller passes auth/cookies/these headers, but a future
# one might, and a credential aimed at the first origin must not be
# replayed against wherever a redirect points next.
_CROSS_ORIGIN_STRIPPED_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})
_CROSS_ORIGIN_STRIPPED_KWARGS = ("auth", "cookies")
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _crosses_origin(previous_url, current_url):
    """Whether *current_url* is a different-enough origin from
    *previous_url* that a credential aimed at the first must not be
    replayed against it. Matches requests.Session.should_strip_auth's own
    host/scheme/port rule exactly: a host change always strips; an
    http-to-https upgrade on the two schemes' default ports does not; any
    other scheme or port change does. (Only the auth/Authorization rule is
    matched exactly; see the module-level comment above
    _CROSS_ORIGIN_STRIPPED_HEADERS for where Cookie and Proxy-Authorization
    diverge from what requests itself does.)
    """
    old = urlparse(previous_url)
    new = urlparse(current_url)
    if old.hostname != new.hostname:
        return True
    if (
        old.scheme == "http"
        and old.port in (80, None)
        and new.scheme == "https"
        and new.port in (443, None)
    ):
        return False
    changed_port = old.port != new.port
    changed_scheme = old.scheme != new.scheme
    default_port = (_DEFAULT_PORTS.get(old.scheme), None)
    if not changed_scheme and old.port in default_port and new.port in default_port:
        return False
    return changed_port or changed_scheme


def fetch_outbound_http(url, *, allow_private=False, allow_loopback=False,
                        max_redirects=5, **kwargs):
    """requests.get that validates every hop, not just the first.

    requests follows redirects by default, and validate_outbound_http_url
    only ever sees the URL it is handed, so a public URL answering 302 to
    169.254.169.254 used to be followed (#103-#105). Each hop here is fetched
    with allow_redirects=False and its Location validated before it is
    followed. DNS can still change between a hop's check and its connect;
    that residual is accepted for this module's callers. `auth`, `cookies`
    and any Authorization/Cookie/Proxy-Authorization header are dropped the
    moment a hop crosses an origin boundary (host, scheme or port -- see
    _crosses_origin), so a credential is never replayed against a different
    origin. This is at least as strict as what requests' own built-in
    redirect handling does (identical for auth/Authorization; requests is
    stricter still for Cookie and Proxy-Authorization, which it re-derives
    on every hop rather than only dropping on an origin change). `params`
    is applied to hop 0's URL only and then dropped, matching requests: a
    later Location is followed literally, never with the same query string
    appended again.
    """
    kwargs.pop("allow_redirects", None)
    current = url
    previous_url = None
    for _hop in range(max_redirects + 1):
        validate_outbound_http_url(
            current, allow_private=allow_private, allow_loopback=allow_loopback
        )
        if previous_url is not None and _crosses_origin(previous_url, current):
            for kw in _CROSS_ORIGIN_STRIPPED_KWARGS:
                kwargs.pop(kw, None)
            headers = kwargs.get("headers")
            if headers:
                kwargs["headers"] = {
                    k: v for k, v in headers.items()
                    if k.lower() not in _CROSS_ORIGIN_STRIPPED_HEADERS
                }
        resp = requests.get(current, allow_redirects=False, **kwargs)
        # requests' own redirect handling applies params to the first
        # request's URL only and then follows Location literally -- it
        # never re-appends them to a later hop. Match that: drop params
        # once hop 0 has used them, or each Location gets the same query
        # string appended again.
        kwargs.pop("params", None)
        previous_url = current
        if resp.status_code not in _REDIRECT_STATUSES:
            return resp
        location = resp.headers.get("Location")
        resp.close()
        if not location:
            raise ValueError("Redirect without a Location header.")
        current = urljoin(current, location)
    raise ValueError(f"More than {max_redirects} redirects.")
