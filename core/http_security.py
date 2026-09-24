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
    parsed = urlparse(url)
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

    # requests only IDNA-encodes a host containing non-ASCII characters
    # (PreparedRequest.prepare_url's own unicode_is_ascii() gate, using the
    # same `idna` package requests itself depends on); mirror that so an
    # internationalised domain compares equal against requests' encoded
    # form instead of being falsely refused as "a different host".
    if hostname.isascii():
        urlparse_dial_host = hostname.lower()
    else:
        try:
            urlparse_dial_host = idna.encode(hostname, uts46=True).decode("ascii").lower()
        except idna.IDNAError as exc:
            raise ValueError("URL host contains an invalid label and is refused.") from exc

    try:
        prepared_url = requests.Request("GET", url).prepare().url
    except Exception as exc:
        raise ValueError("URL could not be prepared for a request and is refused.") from exc
    dialled_host = (parse_url(prepared_url).host or "").strip("[]").lower()
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
# boundary (see _crosses_origin below), same as requests' own
# Session.should_strip_auth does for its built-in redirect handling. No
# current caller passes auth/cookies/these headers, but a future one might,
# and a credential aimed at the first origin must not be replayed against
# wherever a redirect points next.
_CROSS_ORIGIN_STRIPPED_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})
_CROSS_ORIGIN_STRIPPED_KWARGS = ("auth", "cookies")
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _crosses_origin(previous_url, current_url):
    """Whether *current_url* is a different-enough origin from
    *previous_url* that a credential aimed at the first must not be
    replayed against it. Mirrors requests.Session.should_strip_auth
    exactly, so switching a caller from requests' own unbounded redirect
    handling to this helper keeps the same auth-stripping behaviour: a host
    change always strips; an http-to-https upgrade on the two schemes'
    default ports does not; any other scheme or port change does.
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
    origin.
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
        previous_url = current
        if resp.status_code not in _REDIRECT_STATUSES:
            return resp
        location = resp.headers.get("Location")
        resp.close()
        if not location:
            raise ValueError("Redirect without a Location header.")
        current = urljoin(current, location)
    raise ValueError(f"More than {max_redirects} redirects.")
