"""The stream-by-hash authorization shape (rows 16 and 25), and the one cell
of row 20 that needs a live client to observe (the admin's stream limit).

/proxy/ts/stream/<stream_hash> is the admin UI's single-stream preview. It
resolves a Stream, not a Channel (next_source.py:69-79), so
authorize_stream's channel checks never run (authorize.py:431) while the
ACL (:425-426) and the stream limit (:436-442) still do.

The channel that owns the stream is marked hidden_from_output here on
purpose: if any channel check leaked into the hash path, the tune would 403
instead of streaming.
"""

import requests

from apps.accounts.models import User
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer
from core.models import CoreSettings, USER_LIMITS_SETTINGS_KEY

from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until


class StreamByHashAuthorizationTests(RelayHarnessTestCase):
    def setUp(self):
        super().setUp()
        self.profile = stand_in_stream_profile()
        self.channel = self.make_channel(
            upstream_url=self.upstream.url, profile=self.profile
        )
        # The owning channel is hidden: a leaked channel check would 403
        # the hash tune below, so this is the assertion's teeth.
        self.channel.hidden_from_output = True
        self.channel.save(update_fields=["hidden_from_output"])
        self.stream = self.channel.streams.first()
        self.assertIsNotNone(self.stream, "make_channel attaches exactly one Stream")
        self.addCleanup(self._drop_hash_keys)

    def _drop_hash_keys(self):
        # self.stop_channel(self.channel) stops the CHANNEL, keyed by its
        # uuid; the hash tune below runs under the stream_hash as its own
        # identifier, so RelayHarnessTestCase's own channel cleanup never
        # reaches live:channel:{stream_hash}:*. Without this, the next test
        # in the process could see a stale channel under this identifier.
        server = ProxyServer.get_instance()
        try:
            server.stop_channel(self.stream.stream_hash)
        except Exception:
            pass
        client = server.redis_client
        if client is not None:
            for key in client.scan_iter(
                match=f"live:channel:{self.stream.stream_hash}:*", count=500
            ):
                client.delete(key)

    def hop(self, uri, **headers):
        return requests.get(
            f"{self.live_server_url}/_dispatcharr/authorize",
            headers={"X-Original-URI": uri, **headers},
            timeout=10,
        )

    def assertDenied(self, response, real_status):
        # Repeated from the Task 3 module rather than shared: these are two
        # independent test modules and nothing crosses between them.
        # subrequest_error_response (authorize_views.py:95-99) maps every
        # non-401 status to 403 and puts the real one in the header, so
        # asserting only the 403 would pass for the wrong reason.
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(response.headers.get("X-Authorize-Status"), str(real_status))

    def a_client_stop_was_requested(self, identifier):
        """True once the relay has been asked to stop ANY client on `identifier`.

        Deliberately a scan rather than a named client id: the held client's
        id is minted inside the hop and never reaches this test, and inventing
        a way to learn it would be more machinery than the assertion is worth.
        RedisKeys.client_stop(channel, client) is
        live:channel:{channel}:client:{client}:stop, so the prefix is the
        question "was anyone stopped here".
        """
        client = ProxyServer.get_instance().redis_client
        pattern = f"live:channel:{identifier}:client:*:stop"
        return any(True for _ in client.scan_iter(match=pattern, count=500))

    def test_a_stream_hash_tune_applies_no_channel_check(self):
        # Row 16. The hop resolves a Stream, so X-Relay-Channel is empty --
        # there is no channel uuid to name -- and the request is allowed
        # even though the channel carrying this stream is hidden.
        response = self.hop(f"/proxy/ts/stream/{self.stream.stream_hash}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-Channel"], "")
        self.assertTrue(response.headers["X-Relay-Client"].startswith("client_"))

        # And it really streams: the byte path takes the same identifier
        # straight through, keyed on the hash rather than a channel uuid.
        with self.stand_in():
            body = requests.get(
                f"{self.live_server_url}/proxy/ts/stream/{self.stream.stream_hash}",
                stream=True,
                timeout=20,
            )
            self.addCleanup(body.close)
            self.assertEqual(body.status_code, 200)
            received = b""
            for chunk in body.iter_content(chunk_size=4096):
                received += chunk
                if len(received) >= 20 * 188:
                    break
            self.assertGreaterEqual(len(received), 20 * 188)
            self.assertEqual(received[0], 0x47, "the first byte is a TS sync byte")

    def test_the_stream_limit_terminates_the_held_client_and_admits_the_new_tune(self):
        """The production default, which is NOT "the new tune is refused".

        check_user_stream_limits (apps/proxy/utils.py:463-476) reads
        terminate_on_limit_exceeded, whose default is True
        (core/models.py:762-768). At the limit it therefore calls
        attempt_stream_termination, which stops the held client and returns
        True -- so the hop ADMITS the new tune and the old one is dropped.
        "The stream limit is enforced" means "a slot is freed", not "you are
        turned away", and rows 20 and 25 are held to the default.

        Pinning only the refusal path would pin the branch operators do not
        run.
        """
        admin = User.objects.create_user(
            username="hash-admin",
            password="x",
            user_level=User.UserLevel.ADMIN,
            stream_limit=1,
        )
        self.client.force_login(admin)
        session = self.client.cookies["sessionid"].value

        with self.stand_in():
            held = requests.get(
                f"{self.live_server_url}/proxy/ts/stream/{self.stream.stream_hash}",
                cookies={"sessionid": session},
                stream=True,
                timeout=20,
            )
            self.addCleanup(held.close)
            self.assertEqual(held.status_code, 200)
            next(held.iter_content(chunk_size=188))

            # The whole D4 loop runs for real: authorize_stream ->
            # check_user_stream_limits -> relay_client.live_connections ->
            # relay_client.list_channels() -> a signed HTTP call to this same
            # process's GET /proxy/relay/channels?clients=all.
            second = self.hop(
                f"/proxy/ts/stream/{self.channel.uuid}",
                **{"Cookie": f"sessionid={session}"},
            )
            self.assertEqual(
                second.status_code, 200,
                "the default frees a slot rather than refusing the tune",
            )

            # And the slot really was freed at the held client's expense:
            # the relay has been asked to stop a client on that channel.
            wait_until(
                lambda: self.a_client_stop_was_requested(self.stream.stream_hash),
                timeout=10,
                what="the held client to be stopped to free the slot",
            )

        self.stop_channel(self.channel)

    def test_the_stream_limit_refuses_when_termination_is_disabled(self):
        """The other branch, which an operator selects deliberately.

        With terminate_on_limit_exceeded False, check_user_stream_limits
        returns False at :464-465 without terminating anything, and
        authorize_stream raises AuthorizeDenied(429) -- which the nginx-facing
        view can only carry as 403 plus X-Authorize-Status: 429.

        user_limit_settings is a CoreSettings GROUP, so this write is
        instance-wide and the flush does not undo the Redis cache (see
        Global Constraints); addCleanup does.
        """
        CoreSettings.objects.update_or_create(
            key=USER_LIMITS_SETTINGS_KEY,
            defaults={"value": {"terminate_on_limit_exceeded": False}},
        )
        CoreSettings.invalidate_group_cache(USER_LIMITS_SETTINGS_KEY)
        self.addCleanup(
            CoreSettings.invalidate_group_cache, USER_LIMITS_SETTINGS_KEY
        )

        admin = User.objects.create_user(
            username="hash-admin-strict",
            password="x",
            user_level=User.UserLevel.ADMIN,
            stream_limit=1,
        )
        self.client.force_login(admin)
        session = self.client.cookies["sessionid"].value

        with self.stand_in():
            held = requests.get(
                f"{self.live_server_url}/proxy/ts/stream/{self.stream.stream_hash}",
                cookies={"sessionid": session},
                stream=True,
                timeout=20,
            )
            self.addCleanup(held.close)
            self.assertEqual(held.status_code, 200)
            next(held.iter_content(chunk_size=188))

            # Row 25: enforced for a principal on the by-hash surface.
            second = self.hop(
                f"/proxy/ts/stream/{self.stream.stream_hash}",
                **{"Cookie": f"sessionid={session}"},
            )
            self.assertDenied(second, 429)

            # Row 20: an admin's bypasses do not reach the stream limit. Same
            # held client, a different identifier, so this is the limit and
            # not a same-channel exemption.
            channel_attempt = self.hop(
                f"/proxy/ts/stream/{self.channel.uuid}",
                **{"Cookie": f"sessionid={session}"},
            )
            self.assertDenied(channel_attempt, 429)

        self.stop_channel(self.channel)
