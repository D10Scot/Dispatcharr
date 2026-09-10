"""The authorize matrix, decided over real HTTP (rows 19, 20, 23, plus the
live-root test row 21's Notes ask 2a-5 for -- row 21's own line is already
pinned and is not edited by this PR).

Driven at GET /_dispatcharr/authorize -- the subrequest nginx makes once per
tune, whose five X-Relay-* response headers 2c's Go relay consumes verbatim.
That surface makes the whole decision and tunes nothing, which is why three
rows fit in this file for the cost of no spawns at all.

apps/proxy/tests/test_authorize.py already covers these principals by calling
authorize_stream() directly with a RequestFactory and patching
network_access_allowed, _drf_user and check_user_stream_limits. Those tests
stay and are worth having; they are not what pins a parity row, because an
assertion about one Python function calling another does not port to Go.
Every assertion here is a status code or a response header.

A denial from this view is 401 or 403 ONLY -- subrequest_error_response
(authorize_views.py:95-99) maps every other status to 403 and puts the real
one in X-Authorize-Status, because ngx_http_auth_request_module can carry
nothing else. Assert both halves.
"""

import requests

from apps.accounts.models import User
from apps.channels.models import Channel
from apps.proxy.internal_auth import HEADER_INTERNAL, internal_principal_token
from core.models import CoreSettings, NETWORK_ACCESS_KEY

from .harness.relay import RelayHarnessTestCase


class AuthorizeMatrixOverHttpTests(RelayHarnessTestCase):
    """Every row that no e2e spec pins, asserted on the hop's own wire.

    TransactionTestCase flushes every table after each test, so each test
    creates the rows it needs; setUp, not setUpTestData.
    """

    def setUp(self):
        super().setUp()
        self.plain = Channel.objects.create(name="row-plain", channel_number=9701)
        self.hidden = Channel.objects.create(
            name="row-hidden", channel_number=9702, hidden_from_output=True
        )
        self.adult = Channel.objects.create(
            name="row-adult", channel_number=9703, is_adult=True
        )

    def hop(self, uri, *, headers=None, cookies=None):
        """One auth_request subrequest, exactly as nginx makes it."""
        return requests.get(
            f"{self.live_server_url}/_dispatcharr/authorize",
            headers={"X-Original-URI": uri, **(headers or {})},
            cookies=cookies or {},
            timeout=10,
        )

    def assertDenied(self, response, real_status):
        # 403 on the wire, the real code in the header nginx's error_page
        # reads back. Asserting only the 403 would pass for the wrong reason.
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(response.headers.get("X-Authorize-Status"), str(real_status))

    # -- row 19: the Internal principal ---------------------------------

    def internal(self):
        """The STATIC header only, and the reason is the row.

        authorize_stream's is_internal is request_is_internal() alone
        (authorize.py:418, feeding _resolve_principal:309-310). The bound
        X-Dispatcharr-Internal-Request gates the five /proxy/relay/... and
        two /api/relay/... routes through IsInternalRelay
        (permissions.py:21-27) -- it is NOT part of this decision.

        WHY the streaming surface deliberately takes the weaker credential,
        from internal_auth.py:44-49: the DVR's stream fetch sends only the
        static header, because ffmpeg re-sends its -headers line on every
        reconnect for the life of a recording, and a 120-second windowed
        token would 403 that reconnect. A recording that survives an
        upstream blip is the behaviour being bought.

        This is exactly the kind of deliberate asymmetry a Go implementer
        would "fix" while porting -- requiring both headers everywhere
        looks strictly safer and silently breaks every long recording. The
        matrix exists to stop that, so adding the bound header to this test
        because it seems more correct would defeat the row.
        """
        return {HEADER_INTERNAL: internal_principal_token()}

    def test_the_internal_principal_streams_a_channel_hidden_from_output(self):
        response = self.hop(
            f"/proxy/ts/stream/{self.hidden.uuid}", headers=self.internal()
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-Channel"], str(self.hidden.uuid))
        # No user resolved: the DVR has no account, so no user_level,
        # membership or stream_limit is in the path of a recording.
        self.assertEqual(response.headers["X-Relay-User"], "")

    def test_the_internal_principal_streams_an_adult_channel(self):
        response = self.hop(
            f"/proxy/ts/stream/{self.adult.uuid}", headers=self.internal()
        )
        self.assertEqual(response.status_code, 200)

    def test_the_internal_principal_is_still_subject_to_the_streams_acl(self):
        # The one check it does NOT bypass (authorize.py:425-426). The ACL
        # is instance-wide state -- CoreSettings is one row per settings
        # GROUP -- so this test writes the group and the flush removes it.
        CoreSettings.objects.update_or_create(
            key=NETWORK_ACCESS_KEY, defaults={"value": {"STREAMS": "10.255.255.0/32"}}
        )
        # CoreSettings has no save() override, so the write alone leaves the
        # Redis-backed group cache stale -- and that cache outlives the
        # Postgres flush, poisoning every later test in this process.
        CoreSettings.invalidate_group_cache(NETWORK_ACCESS_KEY)
        self.addCleanup(CoreSettings.invalidate_group_cache, NETWORK_ACCESS_KEY)

        response = self.hop(
            f"/proxy/ts/stream/{self.plain.uuid}", headers=self.internal()
        )
        self.assertDenied(response, 403)

    def test_a_forged_internal_token_is_not_an_internal_principal(self):
        # The header is an HMAC of SECRET_KEY, not a flag: a caller who
        # merely sends the header name is anonymous, and anonymous is
        # refused a hidden channel.
        response = self.hop(
            f"/proxy/ts/stream/{self.hidden.uuid}",
            headers={HEADER_INTERNAL: "not-the-token"},
        )
        self.assertDenied(response, 403)

    # -- row 20: Admin ---------------------------------------------------

    def test_an_admin_streams_a_channel_hidden_from_output(self):
        admin = User.objects.create_user(
            username="row20-admin", password="x", user_level=User.UserLevel.ADMIN
        )
        self.client.force_login(admin)
        response = self.hop(
            f"/proxy/ts/stream/{self.hidden.uuid}",
            cookies={"sessionid": self.client.cookies["sessionid"].value},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-User"], str(admin.id))

    def test_an_admin_streams_an_adult_channel_despite_hide_adult_content(self):
        # _apply_channel_checks returns at authorize.py:379-385, BEFORE the
        # adult check at :393 -- so an admin who set the preference for
        # themselves still previews the channel.
        admin = User.objects.create_user(
            username="row20-admin-adult",
            password="x",
            user_level=User.UserLevel.ADMIN,
            custom_properties={"hide_adult_content": True},
        )
        self.client.force_login(admin)
        response = self.hop(
            f"/proxy/ts/stream/{self.adult.uuid}",
            cookies={"sessionid": self.client.cookies["sessionid"].value},
        )
        self.assertEqual(response.status_code, 200)

    # -- row 23: Session, non-admin --------------------------------------

    def test_a_session_principal_streams_an_ordinary_channel(self):
        """The identity assertion is the test. The 200 is not.

        DO NOT TRIM THE X-Relay-User ASSERTION AS REDUNDANT. A 200 here
        proves nothing, because an ORDINARY channel streams to an
        ANONYMOUS request too (matrix row 24) -- so if the session
        principal were lost entirely, this request would still answer 200
        with bytes and this test would still pass. What would have
        silently stopped applying is every user-scoped check: user_level,
        Channel Profile membership, adult filtering and the stream limit.
        The one visible symptom would be a hidden_from_output channel
        still 403ing (it 403s for anonymous as well), so the working half
        keeps working while the invisible half is gone -- the worst
        failure signature an auth change can have.

        Only X-Relay-User carrying this user's id proves the principal
        survived. It survives because _session_user (authorize.py:268-287)
        re-reads the session with django.contrib.auth.get_user(request)
        instead of trusting http_request.user: @api_view's dispatch() runs
        perform_authentication even under @authentication_classes([]) and
        sets request.user to AnonymousUser BEFORE authorize_stream runs.
        _drf_user restores it on a miss for the same reason (:227-265).

        This is the assertion that catches the failure mode 2b's dev
        fallback could introduce -- POST /_dispatcharr/authorize-internal
        forwards a session cookie, and a receiving view that resolves the
        principal from request.user rather than from the session store
        would downgrade every session viewer to anonymous with no error
        anywhere.
        """
        user = User.objects.create_user(
            username="row23-standard", password="x", user_level=1
        )
        self.client.force_login(user)
        response = self.hop(
            f"/proxy/ts/stream/{self.plain.uuid}",
            cookies={"sessionid": self.client.cookies["sessionid"].value},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-User"], str(user.id))

    def test_a_session_principal_is_refused_a_hidden_channel(self):
        user = User.objects.create_user(
            username="row23-hidden", password="x", user_level=1
        )
        self.client.force_login(user)
        response = self.hop(
            f"/proxy/ts/stream/{self.hidden.uuid}",
            cookies={"sessionid": self.client.cookies["sessionid"].value},
        )
        self.assertDenied(response, 403)

    def test_a_session_principal_is_refused_an_adult_channel_when_hiding_adult(self):
        user = User.objects.create_user(
            username="row23-adult",
            password="x",
            user_level=1,
            custom_properties={"hide_adult_content": True},
        )
        self.client.force_login(user)
        response = self.hop(
            f"/proxy/ts/stream/{self.adult.uuid}",
            cookies={"sessionid": self.client.cookies["sessionid"].value},
        )
        self.assertDenied(response, 403)

    def test_a_session_principal_below_the_channels_user_level_is_refused(self):
        gated = Channel.objects.create(
            name="row23-gated", channel_number=9704, user_level=10
        )
        user = User.objects.create_user(
            username="row23-gated-user", password="x", user_level=1
        )
        self.client.force_login(user)
        response = self.hop(
            f"/proxy/ts/stream/{gated.uuid}",
            cookies={"sessionid": self.client.cookies["sessionid"].value},
        )
        self.assertDenied(response, 403)

    # -- no row: a rejected credential is not an anonymous tune ----------

    def test_a_rejected_credential_is_401_and_never_an_anonymous_tune(self):
        """_drf_user's two meanings of "no user", asserted on the wire.

        authorize.py:227-265 RAISES AuthorizeDenied(401) for a credential
        an authenticator explicitly rejected (a malformed Bearer token, an
        unknown API key) and RETURNS None for one merely declined (nothing
        presented). A port that maps both to "anonymous" turns a rejected
        credential into a successful anonymous tune of any ordinary
        channel -- the same silent-downgrade shape as the session case
        above.

        PINS NO MATRIX ROW, deliberately: no row states this, and adding
        one would bump HIGHEST_ROW_ID against three sibling PRs in flight.
        Recommended for 2a-7 in this PR's description instead.
        """
        rejected = self.hop(
            f"/proxy/ts/stream/{self.plain.uuid}",
            headers={"Authorization": "Bearer not-a-token"},
        )
        self.assertDenied(rejected, 401)

        # The other meaning of "no user": nothing presented at all, which
        # is a legitimate anonymous tune of an ordinary channel (row 24).
        declined = self.hop(f"/proxy/ts/stream/{self.plain.uuid}")
        self.assertEqual(declined.status_code, 200)
        self.assertEqual(declined.headers["X-Relay-User"], "")

    # -- row 21's outstanding live-root cell -----------------------------

    def test_an_xc_user_with_hide_adult_content_is_refused_on_the_live_root(self):
        # Row 21's Notes: the adult-filter half for the XC principal was
        # proven only by a catch-up-root test, which is off this matrix's
        # live-path scope and can never carry a 2d cutover obligation.
        # This is the live-root equivalent that row owed 2a-5.
        User.objects.create_user(
            username="row21-xc",
            password="x",
            user_level=1,
            custom_properties={
                "xc_password": "xc-secret",
                "hide_adult_content": True,
            },
        )
        response = self.hop(f"/live/row21-xc/xc-secret/{self.adult.id}")
        self.assertDenied(response, 403)
