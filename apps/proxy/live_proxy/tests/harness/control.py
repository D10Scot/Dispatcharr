"""Drive the relay's CONTROL surfaces over real HTTP, as a real principal.

2a-2's harness drives the stream surface. This drives the other four routes an
operator uses -- /proxy/ts/status/<uuid>, /change_stream/, /stop/, /stop_client/
-- plus the one thing a tune sometimes needs that `tuned()` deliberately does
not offer: a chosen client id, and a non-200 answer.

Everything here goes through production mechanisms, not test seams:

  * The admin principal is a real User row with an api_key, authenticated by
    apps/accounts/authentication.py's ApiKeyAuthentication through the
    X-API-Key header -- one of the two DEFAULT_AUTHENTICATION_CLASSES
    (dispatcharr/settings.py:321-324).

  * A chosen client id is supplied the way nginx supplies one:
    X-Dispatcharr-Authorized carrying HMAC(SECRET_KEY, "relay-trust") plus
    X-Relay-Channel and X-Relay-Client. resolve_authorization() trusts those
    headers only when the marker matches (apps/proxy/authorize_views.py:103-136),
    and stream_ts then uses `decision.client_id` rather than minting one
    (apps/proxy/live_proxy/views.py:194). This is nginx's own contract, so a
    test written against it ports to the Go relay unchanged.

  * proxy_settings is written as a CoreSettings row and the process-local cache
    is cleared, which is exactly what saving the setting in the UI does.

A NEW FILE ON PURPOSE. 2a-3, 2a-4, 2a-5 and 2a-6 develop in parallel against
this harness; adding a parameter to relay.py's tuned() would put four PRs on one
line. open_tune() below reaches _TunedStream directly instead -- same package,
no edit.
"""

import json
import uuid as uuid_module

import requests

from apps.proxy.internal_auth import (
    HEADER_AUTHORIZED,
    HEADER_RELAY_CHANNEL,
    HEADER_RELAY_CLIENT,
    relay_trust_token,
)

from .relay import _TunedStream

# BaseConfig.get_proxy_settings()'s own fallback dict (apps/proxy/config.py:52-59),
# repeated here so set_proxy_setting() writes a WHOLE group rather than a partial
# one: CoreSettings holds one row per settings group, so a partial write is a
# partial group, and the next reader silently falls back for everything missing.
PROXY_SETTINGS_DEFAULTS = {
    "buffering_timeout": 15,
    "buffering_speed": 1.0,
    "redis_chunk_ttl": 60,
    "channel_shutdown_delay": 0,
    "channel_init_grace_period": 60,
    "channel_client_wait_period": 5,
    "new_client_behind_seconds": 5,
}


def nginx_headers(channel, client_id):
    """The three headers nginx sets on a relay-bound location for this tune."""
    return {
        HEADER_AUTHORIZED: relay_trust_token(),
        HEADER_RELAY_CHANNEL: str(channel.uuid),
        HEADER_RELAY_CLIENT: client_id,
    }


def open_tune(case, channel, *, headers=None, timeout=20.0, expect_status=200):
    """GET /proxy/ts/stream/<uuid>, left open; return (response, reader).

    Like RelayHarnessTestCase.tuned() but not a context manager, because a test
    that wants several clients at once needs them all open simultaneously, and
    because a test may expect a non-200. The response is closed by addCleanup.

    NEVER read `response.text` on a 200: the body of a live stream does not end,
    and `timeout` is a socket timeout rather than a wall-clock one, so a status
    message built eagerly hangs forever (harness/relay.py:215-221).
    """
    response = requests.get(
        f"{case.live_server_url}/proxy/ts/stream/{channel.uuid}",
        stream=True,
        timeout=timeout,
        headers=headers,
    )
    case.addCleanup(response.close)
    case.assertEqual(response.status_code, expect_status)
    return response, _TunedStream(response, timeout=timeout)


class ControlMixin:
    """Mixed into a RelayHarnessTestCase that drives the admin control routes."""

    def admin_headers(self):
        """An admin principal, created on first use.

        Created lazily and per test: TransactionTestCase flushes every table
        between tests, so a class-level or setUpTestData user would not survive
        (harness/README.md, Two traps).
        """
        if not hasattr(self, "_admin_headers"):
            from apps.accounts.models import User

            key = uuid_module.uuid4().hex
            User.objects.create_user(
                username=f"harness-admin-{key[:8]}",
                password="unused-password",
                user_level=User.UserLevel.ADMIN,
                api_key=key,
            )
            self._admin_headers = {"X-API-Key": key}
        return self._admin_headers

    def set_proxy_setting(self, **overrides):
        """Write the proxy_settings group and invalidate BOTH of its caches.

        There are two, and clearing only the process-local one leaves the
        override in place for the rest of the test process. TransactionTestCase
        flushes with TRUNCATE, which fires no post_delete, so CoreSettings'
        Redis group cache (core/models.py:220-222, 300-second TTL) keeps
        serving the value after the row it came from is gone -- and the
        process-local copy is then refilled from the poisoned Redis entry.
        Measured: the DB row was empty and the next test class still read the
        override.

        Both are cleared explicitly, and the second call is NOT redundant.
        invalidate_group_cache deletes the Redis entry and bumps the version
        key so an in-flight fill cannot re-poison it, and it does try to clear
        the process-local copy -- but it calls
        `BaseConfig.clear_proxy_settings_cache()` (core/models.py:356-363),
        which cannot reach the relay's copy. `get_proxy_settings` assigns
        `cls._proxy_settings_cache` on whichever class it was called through,
        and every proxy read goes through `TSConfig` (config_helper.py:5), so
        `TSConfig` holds its own attribute shadowing `BaseConfig`'s. Verified
        in a shell: after `BaseConfig.clear_proxy_settings_cache()`,
        `TSConfig._proxy_settings_cache` still held its value; after
        `TSConfig.clear_proxy_settings_cache()` it was None. That is a
        production defect, not a test-only quirk -- see the plan's Findings --
        and until it is fixed a test must clear the subclass itself.
        """
        from apps.proxy.config import TSConfig
        from core.models import PROXY_SETTINGS_KEY, CoreSettings

        def _invalidate():
            CoreSettings.invalidate_group_cache(PROXY_SETTINGS_KEY)
            TSConfig.clear_proxy_settings_cache()

        CoreSettings.objects.update_or_create(
            key=PROXY_SETTINGS_KEY,
            defaults={"value": {**PROXY_SETTINGS_DEFAULTS, **overrides}},
        )
        _invalidate()
        self.addCleanup(_invalidate)

    def status(self, channel):
        """GET /proxy/ts/status/<uuid> as an admin; return (status_code, body)."""
        response = requests.get(
            f"{self.live_server_url}/proxy/ts/status/{channel.uuid}",
            headers=self.admin_headers(),
            timeout=10,
        )
        return response.status_code, response.json()

    def change_stream(self, channel, url):
        """POST /proxy/ts/change_stream/<uuid> with an explicit url."""
        return requests.post(
            f"{self.live_server_url}/proxy/ts/change_stream/{channel.uuid}",
            headers={**self.admin_headers(), "Content-Type": "application/json"},
            data=json.dumps({"url": url}),
            timeout=30,
        )

    def stop_channel_over_http(self, channel):
        """POST /proxy/ts/stop/<uuid>.

        Named for the surface, not the action, because RelayHarnessTestCase
        already has stop_channel() -- the in-process teardown its cleanup uses.
        """
        return requests.post(
            f"{self.live_server_url}/proxy/ts/stop/{channel.uuid}",
            headers=self.admin_headers(),
            timeout=30,
        )

    def stop_client(self, channel, client_id):
        """POST /proxy/ts/stop_client/<uuid>."""
        return requests.post(
            f"{self.live_server_url}/proxy/ts/stop_client/{channel.uuid}",
            headers={**self.admin_headers(), "Content-Type": "application/json"},
            data=json.dumps({"client_id": client_id}),
            timeout=30,
        )
