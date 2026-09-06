"""One address resolver and one host check, shared by both internal directions.

Phase 1 D9: "two thin wrappers over one function". PR 6 shipped the
function inside apps/proxy/control_plane.py, which is the relay's side
of the boundary; PR 7 needs the same formula on Django's side, and a
private name imported across that boundary would be a worse coupling
than a shared module.

Both wrappers resolve to an address served by **nginx**, never to a raw
application port:

  relay -> Django   apps/proxy/control_plane.get_control_plane_base_url()
                    DISPATCHARR_INTERNAL_API_BASE_URL, else the api
                    role's nginx.
  Django -> relay   apps/proxy/relay_client.get_relay_control_base_url()
                    DISPATCHARR_RELAY_BASE_URL, else the SAME nginx,
                    which routes ^~ /proxy/relay/ to the relay_py
                    upstream (docker/nginx.conf).

The second one is why the modular branch reads DISPATCHARR_WEB_HOST for
both directions rather than DISPATCHARR_RELAY_HOST as D9's text says.
docker/uwsgi.relay.ini gives the relay exactly one listener,
`socket = 0.0.0.0:$(DISPATCHARR_RELAY_PORT)`, which speaks the uwsgi
protocol -- requests cannot dial it -- and D14 gives the relay role no
nginx of its own, so nothing answers HTTP in that container at all.
D5 states the resolution: "D9 routes Django's control calls through
nginx as well, so nothing ever dials a raw HTTP port on the relay."
DISPATCHARR_RELAY_HOST keeps its one job, the RELAY_UPSTREAM sed in
docker/init/03-init-dispatcharr.sh; DISPATCHARR_RELAY_BASE_URL is the
escape hatch for a deployment that does front the relay directly.
"""

import logging
import os
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from django.http.request import split_domain_port

from dispatcharr.utils import redact_url

logger = logging.getLogger(__name__)

# Set once we have logged the ImproperlyConfigured message for this
# process, so a misconfigured deployment writes one explanation rather
# than one per call. Callers still see the exception every time.
_host_validation_warned = False


def _var_only_subject(var_name):
    # Used where the value itself must not be echoed at all -- a
    # scheme-less or unparseable string can't be redacted reliably, so
    # naming only the responsible variable is the safe option. dev/aio
    # have no user-supplied hostname to blame.
    return var_name if var_name else "the control-plane URL"


def _subject_with_value(var_name, url):
    # Only call this once the scheme is confirmed http/https: redact_url
    # needs a parseable netloc to mask userinfo, and a scheme-less string
    # can misparse (e.g. "user:pw@host" takes "user" as the scheme and
    # never exposes a netloc at all, so redact_url would return it
    # unchanged, password included). dev/aio's url is always the literal
    # 127.0.0.1 form and never carries a caller-supplied credential.
    return f"{var_name}={redact_url(url)}" if var_name else f"the control-plane URL {url!r}"


def _raise_and_warn_once(message, var_name):
    # var_name travels on the exception (not just baked into the message)
    # so a catcher that must not repeat the message -- release_source(),
    # which logs its own ERROR without the URL -- can still name which
    # variable is responsible.
    global _host_validation_warned
    if not _host_validation_warned:
        logger.error(message)
        _host_validation_warned = True
    exc = ImproperlyConfigured(message)
    exc.var_name = var_name
    raise exc


def validated_base_url(url, var_name=None):
    """Reject a URL requests would turn into a Host header Django refuses.

    Three checks, in order:

    1. url must actually parse as a URL. urlsplit() raises a bare
       ValueError (not caught anywhere else on this path) on malformed
       input such as an unbalanced IPv6 bracket ("http://[::1:9191") --
       caught here and re-raised as ImproperlyConfigured, naming only the
       variable, so every entry point (release_source(), post_events(),
       the tune path) sees one exception type instead of two.
    2. The scheme must be http or https. get_control_plane_base_url()
       only ever builds http:// URLs, so a scheme-less or malformed
       explicit value (e.g. "web:9191", urlsplit scheme "web") has no
       real host at all -- rejecting it with the host-shape message below
       would blame underscores for a problem that has nothing to do with
       them. The value is NOT echoed here, even redacted: a scheme-less
       string can misparse in a way that defeats redact_url (see
       _subject_with_value), so naming the variable is the only safe
       option.
    3. What requests actually puts on the wire as the Host header is the
       netloc MINUS userinfo: requests turns "user:pw@host:9191" into
       HTTP Basic auth and sends "Host: host:9191", never forwarding the
       userinfo as part of the host. Validating the raw netloc (including
       userinfo) would reject a URL Django would happily accept, and
       validating it with Django's own split_domain_port -- exactly what
       HttpRequest.get_host() calls -- means the client and the server can
       never disagree about what counts as a valid Host header once
       userinfo is out of the way. It returns ('', '') for anything
       host_validation_re rejects (notably: an underscore anywhere in the
       host), and get_host() raises DisallowedHost for that BEFORE
       ALLOWED_HOSTS is even consulted. A relay that sent such a URL as an
       HTTP request would just get an opaque 400 with no indication why;
       failing here, at the source of the value, points at the actual
       variable responsible. By this point the scheme is confirmed, so
       the message echoes redact_url(url) -- the netloc parses reliably
       and any userinfo is masked.

    No network access -- this is string parsing on a value already in
    hand, safe to run on every call.
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        _raise_and_warn_once(
            f"{_var_only_subject(var_name)} could not be parsed as a URL.",
            var_name,
        )
    if parsed.scheme not in ("http", "https"):
        _raise_and_warn_once(
            f"{_var_only_subject(var_name)} is not an http(s) URL: "
            "get_control_plane_base_url() only builds http:// URLs, and a "
            "scheme-less or malformed value has no host requests can send.",
            var_name,
        )
    host_for_wire = parsed.netloc.rpartition("@")[2]
    domain, _port = split_domain_port(host_for_wire)
    if domain:
        return url
    _raise_and_warn_once(
        f"{_subject_with_value(var_name, url)} must be an http(s) URL "
        "whose host is letters, digits, dots and hyphens.",
        var_name,
    )


def resolve_base_url(*, override_var, modular_host_var, modular_host_default):
    """The D9 four-branch formula, once, for whichever direction asks.

    Same shape as get_dvr_stream_base_url() (apps/channels/tasks.py),
    which D9 names as the formula it borrows: explicit override, then
    modular by service name, then dev, then AIO through nginx on
    DISPATCHARR_PORT. Every branch validates before returning, so a
    misconfigured host fails loudly here instead of as an opaque 400.

    The dev branch has no nginx to go through, so it names the
    application port directly. What answers there depends on how dev
    was started: a bare `manage.py runserver 5656` is one process
    serving both sides, while docker/supervisord/all-dev.conf runs
    api-uwsgi AND relay-uwsgi with no nginx, so :5656 is the API
    uWSGI and /proxy/relay/... is served by the API process. Both
    work -- one Redis, and ChannelService reaches a channel's owner
    over live:events: pub/sub either way -- but the second cannot
    clear a StreamManager it does not hold (see reset_tried).
    """
    explicit = os.environ.get(override_var)
    if explicit:
        return validated_base_url(explicit.rstrip("/"), override_var)
    env = os.environ.get("DISPATCHARR_ENV", "aio").lower()
    if env == "modular":
        host = os.environ.get(modular_host_var, modular_host_default)
        port = os.environ.get("DISPATCHARR_PORT", "9191")
        return validated_base_url(f"http://{host}:{port}", modular_host_var)
    if env == "dev":
        # Hardcoded, not read from DISPATCHARR_PORT: in dev the port
        # that answers is uWSGI's / runserver's own, not nginx's, and
        # DISPATCHARR_PORT names vite's (CLAUDE.md section Commands).
        return validated_base_url("http://127.0.0.1:5656")
    port = os.environ.get("DISPATCHARR_PORT", "9191")
    return validated_base_url(f"http://127.0.0.1:{port}")
