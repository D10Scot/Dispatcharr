"""An authenticated live tune reports the real user, not the anonymous fallback.

2b-2's surface split gives a live tune `decision.user is None`, so every
consumer that still reads the object falls back to "0"/"unknown" for a
fully authenticated viewer -- a plausible wrong value, not a crash, and
one every pre-existing test in this tree already expects. This file is
the pin that a converted consumer actually carries the identity through.

The user's id and name are chosen so they cannot arise by accident:
424242 is far above any sequence value and is not add_client's "0"
fallback, and the username is not "unknown".
"""

import requests
from django.contrib.auth import get_user_model

from apps.proxy.internal_auth import relay_trust_token
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until

VIEWER_ID = 424242
VIEWER_NAME = "2b2-authed-viewer"
CLIENT_ID = "client_2b2_authed"


class AuthenticatedTuneIdentityTests(RelayHarnessTestCase):
    def test_the_client_hash_and_the_event_carry_the_real_user(self):
        from core.models import SystemEvent

        User = get_user_model()
        viewer = User(id=VIEWER_ID, username=VIEWER_NAME)
        viewer.set_password("x")
        viewer.save()

        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            identifier = str(channel.uuid)

            # Pre-state that differs from the expected post-state, on
            # purpose: add_client writes with hset(mapping=...), which
            # MERGES. Starting from an empty hash cannot tell "wrote the
            # real id" from "dropped the key" -- both leave a hash with no
            # wrong value in it. Seeded with the exact fallback the bug
            # would produce, the two outcomes are distinguishable.
            redis = ProxyServer.get_instance().redis_client
            redis.hset(
                RedisKeys.client_metadata(identifier, CLIENT_ID),
                mapping={"user_id": "0", "username": "unknown"},
            )

            response = requests.get(
                f"{self.live_server_url}/proxy/ts/stream/{identifier}",
                headers={
                    "X-Dispatcharr-Authorized": relay_trust_token(),
                    "X-Relay-Channel": identifier,
                    "X-Relay-Client": CLIENT_ID,
                    "X-Relay-User": str(VIEWER_ID),
                    "X-Relay-Output": "",
                    # mpegts IS the default, and that is fine here: the
                    # format is not what this test pins, the identity is,
                    # and the TS generator is the one that emits
                    # client_connect (output/ts/generator.py:126-135).
                    "X-Relay-Output-Format": "mpegts",
                    "X-Relay-Client-IP": "203.0.113.9",
                },
                stream=True,
                timeout=20,
            )
            self.addCleanup(response.close)
            self.assertEqual(response.status_code, 200)
            next(response.iter_content(chunk_size=188))

            stored = redis.hgetall(RedisKeys.client_metadata(identifier, CLIENT_ID))
            self.assertEqual(
                stored.get("user_id"),
                str(VIEWER_ID),
                "the client hash kept the anonymous fallback for an "
                "authenticated viewer -- a consumer of decision.user was "
                "not converted (2b-2 task 3 step 6)",
            )

            # The username's real home: emit_event -> POST /api/relay/events
            # -> core/relay_events.py resolves it from user_id -> the row's
            # details JSON. Posted on its own greenlet, so wait for it.
            wait_until(
                lambda: SystemEvent.objects.filter(
                    event_type="client_connect",
                    details__username=VIEWER_NAME,
                ).exists(),
                timeout=15,
                what="the client_connect event to name the real user",
            )
