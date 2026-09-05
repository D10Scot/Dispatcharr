"""The nginx-facing view, and the trust marker the relay checks."""

import uuid
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from apps.accounts.models import User
from apps.channels.models import Channel
from apps.proxy import authorize, authorize_views, internal_auth


class AuthorizeViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.channel = Channel.objects.create(name="pr5-view", channel_number=9101)
        cls.hidden = Channel.objects.create(
            name="pr5-view-hidden", channel_number=9102, hidden_from_output=True
        )
        # stream_limit > 0 is what makes check_user_stream_limits run at
        # all (apps/proxy/utils.py:306), so the 429 test needs a user with
        # one rather than the default 0.
        cls.limited = User.objects.create_user(
            username="pr5-view-limited", password="x", user_level=1, stream_limit=1
        )
        cls.admin = User.objects.create_user(
            username="pr5-view-admin", password="x", user_level=User.UserLevel.ADMIN
        )
        cls.token_user = User.objects.create_user(
            username="pr5-view-token", password="x"
        )
        # A username/password pair with characters that must be
        # percent-encoded on a request line ('@', '#') — the fixture for
        # the X-Original-URI decode fix.
        cls.xc_user = User.objects.create_user(username="u@x", password="unused")
        cls.xc_user.custom_properties = {"xc_password": "p#w"}
        cls.xc_user.save()

    def setUp(self):
        self.client = Client()

    def _get(self, original_uri, **extra):
        return self.client.get(
            "/_dispatcharr/authorize",
            HTTP_X_ORIGINAL_URI=original_uri,
            **extra,
        )

    def test_a_live_tune_is_200_with_every_relay_header(self):
        response = self._get(f"/proxy/ts/stream/{self.channel.uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Relay-Channel"], str(self.channel.uuid))
        self.assertEqual(response["X-Relay-Name"], "py")
        self.assertTrue(response["X-Relay-Client"].startswith("client_"))
        # Empty, not absent: auth_request_set assigns whatever the header
        # holds, and an absent header leaves the nginx variable unset,
        # which uwsgi_param would then send as the literal string "".
        self.assertEqual(response["X-Relay-User"], "")
        self.assertEqual(response["X-Relay-Output"], "")

    def test_a_hidden_channel_is_403_with_no_status_override(self):
        response = self._get(f"/proxy/ts/stream/{self.hidden.uuid}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["X-Authorize-Status"], "403")

    def test_an_unknown_channel_is_403_carrying_404(self):
        # nginx's auth_request module denies only on 401 and 403 and calls
        # every other status an error, answering the client 500. So a 404
        # decision travels as 403 + X-Authorize-Status, and the
        # relay-bound location's error_page turns it back into a 404.
        response = self._get("/proxy/ts/stream/6f1b0b64-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["X-Authorize-Status"], "404")

    def test_a_stream_limit_denial_is_403_carrying_429(self):
        with patch.object(authorize, "_drf_user", return_value=self.limited), \
             patch.object(authorize, "check_user_stream_limits", return_value=False):
            response = self._get(f"/proxy/ts/stream/{self.channel.uuid}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["X-Authorize-Status"], "429")

    def test_a_401_stays_401(self):
        # The one status nginx passes through as itself, so it must not be
        # collapsed: an XC client with bad credentials has to see 401.
        response = self._get("/live/nobody/wrongpass/1")
        self.assertEqual(response.status_code, 401)

    def test_a_uri_that_resolves_to_a_non_stream_view_is_403(self):
        # Fail closed. Nothing should point auth_request at /api/, but a
        # location-table mistake must not authorize a stream.
        response = self._get("/api/channels/channels/")
        self.assertEqual(response.status_code, 403)

    def test_an_uncatalogued_uri_is_403(self):
        # Not 404: dispatcharr/urls.py's `path("<path:unused_path>", …)`
        # SPA catch-all resolves every path, so resolve() does not raise
        # here — the TemplateView is simply not a stream view, which is the
        # fail-closed 403 above. The Resolver404 branch in the view stays
        # as a guard for a path the converters reject outright.
        response = self._get("/nothing/here/at/all/really")
        self.assertEqual(response.status_code, 403)

    def test_a_missing_original_uri_is_403(self):
        response = self.client.get("/_dispatcharr/authorize")
        self.assertEqual(response.status_code, 403)

    def test_the_query_string_comes_from_the_original_uri(self):
        from core.models import OutputProfile

        profile = OutputProfile.objects.create(name="pr5-view-out", is_active=True)
        response = self._get(
            f"/proxy/ts/stream/{self.channel.uuid}?output_profile={profile.id}"
        )
        self.assertEqual(response["X-Relay-Output"], str(profile.id))

    def test_a_client_supplied_relay_header_never_reaches_the_decision(self):
        # nginx blanks these on every non-relay location, but the view must
        # not read them regardless: it is reachable in dev without nginx.
        response = self._get(
            f"/proxy/ts/stream/{self.channel.uuid}",
            HTTP_X_RELAY_CHANNEL=str(self.hidden.uuid),
            HTTP_X_RELAY_USER="1",
        )
        self.assertEqual(response["X-Relay-Channel"], str(self.channel.uuid))
        self.assertEqual(response["X-Relay-User"], "")

    def test_the_view_appears_in_the_openapi_schema(self):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        self.assertIn("/_dispatcharr/authorize", schema["paths"])

    def test_a_percent_encoded_xc_credential_decodes_before_resolving(self):
        # X-Original-URI is nginx's $request_uri — the raw, percent-encoded
        # request line — unlike the inline path's already-decoded path_info.
        # A username/password carrying a reserved character must still
        # resolve to the right user, not 401 on the encoded literal.
        response = self._get(f"/live/u%40x/p%23w/{self.channel.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Relay-User"], str(self.xc_user.id))

    def test_a_session_principal_reaches_authorize_stream_through_the_view(self):
        # @authentication_classes([]) means DRF's own perform_authentication
        # clobbers request.user to AnonymousUser before authorize_stream
        # runs; _session_user must re-resolve from the session directly
        # (apps/proxy/authorize.py) rather than trust request.user.
        self.client.force_login(self.admin)
        response = self._get(f"/proxy/ts/stream/{self.hidden.uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Relay-User"], str(self.admin.id))

    def test_a_query_param_jwt_authorizes_through_the_view(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        token = str(RefreshToken.for_user(self.token_user).access_token)
        response = self._get(f"/proxy/ts/stream/{self.channel.uuid}?token={token}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Relay-User"], str(self.token_user.id))

    def test_a_malformed_bearer_token_is_401_not_anonymous(self):
        response = self._get(
            f"/proxy/ts/stream/{self.channel.uuid}",
            HTTP_AUTHORIZATION="Bearer garbage",
        )
        self.assertEqual(response.status_code, 401)

    def test_every_untested_surface_shape_resolves_through_the_view(self):
        # _surface_for has eight branches; the tests above exercise
        # stream_ts and stream_xc (via /live/). One table for the rest, so
        # this parser — the piece of the hop most likely to drift when a
        # urlconf changes — is pinned rather than merely hand-verified.
        vod_id_a = uuid.uuid4()
        vod_id_b = uuid.uuid4()
        cases = [
            # Bad XC creds 401s before any channel/content lookup, so none
            # of these need a real channel/content record to test the
            # surface resolution itself.
            (f"/nobody/wrongpass/{self.channel.id}", 401),  # bare 3-segment XC form
            (f"/timeshift/nobody/wrongpass/0/0/{self.channel.id}.ts", 401),
            (
                f"/streaming/timeshift.php?username=nobody&password=wrongpass&stream={self.channel.id}.ts",
                401,
            ),  # query-identity block: no path kwargs at all
            (f"/proxy/catchup/{self.channel.uuid}", 401),  # no principal, no session_id
            (f"/proxy/catchup/{self.channel.uuid}?session_id=bogus", 401),
            (f"/movie/nobody/wrongpass/1.mp4", 401),
            (f"/series/nobody/wrongpass/1.mp4", 401),
            # VOD: anonymous is allowed (not in _PRINCIPAL_REQUIRED, not a
            # channel surface), so both layouts should authorize.
            (f"/proxy/vod/movie/{vod_id_a}/sess1", 200),
            (f"/proxy/vod/movie/{vod_id_b}/sess1/{self.channel.id}/", 200),
        ]
        for uri, expected_status in cases:
            with self.subTest(uri=uri):
                response = self._get(uri)
                self.assertEqual(response.status_code, expected_status)


class ResolveAuthorizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.channel = Channel.objects.create(name="pr5-trust", channel_number=9103)
        cls.user = User.objects.create_user(username="pr5-trust-user", password="x")

    def setUp(self):
        from django.test import RequestFactory

        self.factory = RequestFactory()

    def test_a_valid_marker_is_trusted_and_skips_authorize_stream(self):
        request = self.factory.get(
            "/proxy/ts/stream/x",
            HTTP_X_DISPATCHARR_AUTHORIZED=internal_auth.relay_trust_token(),
            HTTP_X_RELAY_CHANNEL=str(self.channel.uuid),
            HTTP_X_RELAY_CLIENT="client_1_2",
            HTTP_X_RELAY_USER=str(self.user.id),
            HTTP_X_RELAY_OUTPUT="",
        )
        with patch.object(authorize_views, "authorize_stream") as inline:
            result = authorize_views.resolve_authorization(
                request, authorize.SURFACE_LIVE, identifier="x"
            )
        inline.assert_not_called()
        self.assertTrue(result.trusted)
        self.assertEqual(result.channel_uuid, str(self.channel.uuid))
        self.assertEqual(result.client_id, "client_1_2")
        self.assertEqual(result.user.id, self.user.id)

    def test_a_forged_marker_falls_through_to_the_inline_decision(self):
        request = self.factory.get(
            "/proxy/ts/stream/x",
            HTTP_X_DISPATCHARR_AUTHORIZED="1",
            HTTP_X_RELAY_CHANNEL=str(self.channel.uuid),
        )
        with patch.object(authorize_views, "authorize_stream") as inline:
            authorize_views.resolve_authorization(
                request, authorize.SURFACE_LIVE, identifier="x"
            )
        inline.assert_called_once()

    def test_a_blank_marker_falls_through(self):
        # What every non-relay nginx location sends.
        request = self.factory.get(
            "/proxy/ts/stream/x", HTTP_X_DISPATCHARR_AUTHORIZED=""
        )
        with patch.object(authorize_views, "authorize_stream") as inline:
            authorize_views.resolve_authorization(
                request, authorize.SURFACE_LIVE, identifier="x"
            )
        inline.assert_called_once()

    def test_a_trusted_user_id_naming_nobody_yields_no_user(self):
        request = self.factory.get(
            "/proxy/ts/stream/x",
            HTTP_X_DISPATCHARR_AUTHORIZED=internal_auth.relay_trust_token(),
            HTTP_X_RELAY_USER="99999999",
        )
        result = authorize_views.resolve_authorization(
            request, authorize.SURFACE_LIVE, identifier="x"
        )
        self.assertIsNone(result.user)

    def test_the_error_response_carries_the_status_and_a_json_body(self):
        response = authorize_views.authorize_error_response(
            authorize.AuthorizeDenied(429, "Stream limit exceeded (2 …)")
        )
        self.assertEqual(response.status_code, 429)
        self.assertIn(b"Stream limit exceeded", response.content)
