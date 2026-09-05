"""relay_event is connection telemetry: admin sockets only.

dispatcharr/consumers.py already keeps channel_stats and friends off
Standard-user sockets because their payloads carry channel UUIDs, which
are usable against anonymous /proxy/ts/stream/<uuid>. relay_event carries
the same channel_id and is gated the same way (Phase 1 PR 6).
"""
from django.test import SimpleTestCase

from dispatcharr.consumers import ADMIN_ONLY_UPDATE_TYPES, user_may_receive_update


class _User:
    def __init__(self, level):
        self.is_authenticated = True
        self.user_level = level


class RelayEventVisibilityTests(SimpleTestCase):
    def test_relay_event_is_listed_admin_only(self):
        self.assertIn("relay_event", ADMIN_ONLY_UPDATE_TYPES)

    def test_a_standard_user_does_not_receive_it(self):
        self.assertFalse(
            user_may_receive_update(_User(1), {"type": "relay_event", "channel_id": "x"})
        )

    def test_an_admin_receives_it(self):
        self.assertTrue(
            user_may_receive_update(_User(10), {"type": "relay_event", "channel_id": "x"})
        )
