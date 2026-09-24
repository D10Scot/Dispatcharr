"""Shared helpers for safer outbound HTTP fetches (SSRF prevention)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

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
    # urlparse does. `http://127.0.0.1:8765\@public.example/` is read by
    # urlparse as host 'public.example' (everything after the last '@' in
    # the netloc), but requests' own URL preparation treats the backslash as
    # ending the authority, and urllib3 -- what requests actually uses to
    # open the connection -- resolves host '127.0.0.1'. Validating urlparse's
    # host alone would pass a URL that dials somewhere else entirely, on any
    # hop: refuse outright on a literal backslash in the authority, and cross
    # check against the host urllib3 will actually dial.
    if "\\" in parsed.netloc:
        raise ValueError(
            f"URL authority '{parsed.netloc}' contains a backslash and is refused."
        )
    try:
        prepared_url = requests.Request("GET", url).prepare().url
    except Exception as exc:
        raise ValueError(f"URL '{url}' could not be prepared for a request: {exc}") from exc
    dialled_host = (parse_url(prepared_url).host or "").strip("[]").lower()
    if dialled_host != hostname.lower():
        raise ValueError(
            f"URL '{url}' parses to host '{hostname}' but would dial "
            f"'{dialled_host}'; refused."
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

# Stripped from a hop's kwargs the moment a redirect changes host, same as
# requests' own resolve_redirects() does for its built-in redirect handling.
# No current caller passes auth/these headers, but a future one might, and a
# credential aimed at the first host must not be replayed against wherever a
# redirect points next.
_CROSS_HOST_STRIPPED_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})


def fetch_outbound_http(url, *, allow_private=False, allow_loopback=False,
                        max_redirects=5, **kwargs):
    """requests.get that validates every hop, not just the first.

    requests follows redirects by default, and validate_outbound_http_url
    only ever sees the URL it is handed, so a public URL answering 302 to
    169.254.169.254 used to be followed (#103-#105). Each hop here is fetched
    with allow_redirects=False and its Location validated before it is
    followed. DNS can still change between a hop's check and its connect;
    that residual is accepted for this module's callers. `auth` and any
    Authorization/Cookie/Proxy-Authorization header are dropped the moment a
    hop's host differs from the previous hop's, so a credential is never
    replayed against a different host.
    """
    kwargs.pop("allow_redirects", None)
    current = url
    previous_host = None
    for _hop in range(max_redirects + 1):
        validate_outbound_http_url(
            current, allow_private=allow_private, allow_loopback=allow_loopback
        )
        # validate_outbound_http_url already refused any URL whose urlparse
        # host disagrees with the host requests/urllib3 would actually dial,
        # so urlparse's hostname is safe to use as "the host this hop dials".
        current_host = (urlparse(current).hostname or "").lower()
        if previous_host is not None and current_host != previous_host:
            kwargs.pop("auth", None)
            headers = kwargs.get("headers")
            if headers:
                kwargs["headers"] = {
                    k: v for k, v in headers.items()
                    if k.lower() not in _CROSS_HOST_STRIPPED_HEADERS
                }
        resp = requests.get(current, allow_redirects=False, **kwargs)
        previous_host = current_host
        if resp.status_code not in _REDIRECT_STATUSES:
            return resp
        location = resp.headers.get("Location")
        resp.close()
        if not location:
            raise ValueError("Redirect without a Location header.")
        current = urljoin(current, location)
    raise ValueError(f"More than {max_redirects} redirects.")
