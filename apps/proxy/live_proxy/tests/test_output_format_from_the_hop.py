"""The trusted output format comes from the hop, not from a User row.

Both of stream_ts's resolution sites are driven: views.py:605 (the client
that initializes the channel, reached only when am_i_owner is True) and
views.py:712 (every client that did not -- the second and subsequent
clients on a running channel). 2b-1 shipped a blocking regression because
only one branch of an owner/follower fork was walked; this file exists so
that cannot happen to this fork.

'fmp4' throughout, never 'mpegts': mpegts is what
CoreSettings.get_default_output_format() answers, so a test asserting it
would pass with the threading deleted.
"""

from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase


def _trusted_decision(output_format="fmp4", user_id="4242"):
    from apps.proxy.authorize import SURFACE_LIVE, AuthorizeResult

    return AuthorizeResult(
        surface=SURFACE_LIVE,
        channel_uuid="channel-uuid",
        client_id="client_test_1",
        user_id=user_id,
        relay_name="py",
        user=None,          # the whole point: no User row was fetched
        trusted=True,
        output_format=output_format,
        client_ip="203.0.113.9",
    )


class OutputFormatFromTheHopTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.channel_id = "channel-uuid"

    def test_the_trusted_decisions_format_is_used_with_no_user_row(self):
        from apps.proxy.live_proxy import views

        resolved = views._resolve_output_format(
            None, None, self.factory.get("/proxy/ts/stream/x"),
            decision=_trusted_decision(),
        )
        self.assertEqual(resolved, "fmp4")

    def test_a_forced_format_still_beats_the_trusted_decision(self):
        # stream_xc's .ts suffix must still win: the hop authorizes a URI
        # and knows nothing about the view's own override.
        from apps.proxy.live_proxy import views

        resolved = views._resolve_output_format(
            None, "mpegts", self.factory.get("/proxy/ts/stream/x"),
            decision=_trusted_decision(),
        )
        self.assertEqual(resolved, "mpegts")

    def test_an_untrusted_decision_falls_back_to_the_user_row(self):
        from apps.proxy.live_proxy import views
        from apps.proxy.authorize import SURFACE_LIVE, AuthorizeResult

        user = MagicMock()
        user.custom_properties = {"output_format": "fmp4"}
        untrusted = AuthorizeResult(
            surface=SURFACE_LIVE, relay_name="py", user=user, trusted=False
        )
        resolved = views._resolve_output_format(
            user, None, self.factory.get("/proxy/ts/stream/x"),
            decision=untrusted,
        )
        self.assertEqual(resolved, "fmp4")
