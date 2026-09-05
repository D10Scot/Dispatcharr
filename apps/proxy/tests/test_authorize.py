"""The authorize matrix (Phase 1 PR 5), one test per cell that differs.

Rows are principals; columns are the checks. The four rows that carry the
behaviour change each have their own class below, and each names why it is
what it is rather than restating the table.
"""

from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings

from apps.accounts.models import User
from apps.channels.models import Channel, ChannelProfile, ChannelProfileMembership
from apps.proxy import authorize, internal_auth
from apps.proxy.authorize import (
    AuthorizeDenied,
    SURFACE_CATCHUP,
    SURFACE_CATCHUP_XC,
    SURFACE_LIVE,
    SURFACE_LIVE_XC,
    SURFACE_VOD,
    SURFACE_VOD_XC,
    authorize_stream,
)


class AuthorizeBase(TestCase):
    """Real rows, not mocks: every check here reads a model field, and a
    MagicMock channel would pass every one of them for the wrong reason."""

    @classmethod
    def setUpTestData(cls):
        cls.channel = Channel.objects.create(name="pr5-plain", channel_number=9001)
        cls.hidden = Channel.objects.create(
            name="pr5-hidden", channel_number=9002, hidden_from_output=True
        )
        cls.adult = Channel.objects.create(
            name="pr5-adult", channel_number=9003, is_adult=True
        )
        cls.gated = Channel.objects.create(
            name="pr5-gated", channel_number=9004, user_level=10
        )
        cls.admin = User.objects.create_user(
            username="pr5-admin", password="x", user_level=User.UserLevel.ADMIN
        )
        cls.standard = User.objects.create_user(
            username="pr5-standard", password="x", user_level=1
        )
        cls.filtered = User.objects.create_user(
            username="pr5-filtered",
            password="x",
            user_level=1,
            custom_properties={"hide_adult_content": True},
        )

    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, path="/proxy/ts/stream/x", **meta):
        return self.factory.get(path, **meta)

    def _allow(self, surface, **kwargs):
        """authorize_stream with the network ACL forced open.

        network_access_allowed reads CoreSettings and the client IP; its
        own behaviour is covered by tests/seeded/network-acl.spec.ts and
        by the ACL class below, and leaving it live in every other test
        would make each one a two-variable experiment.
        """
        with patch.object(authorize, "network_access_allowed", return_value=True):
            return authorize_stream(self._request(), surface, **kwargs)


class AnonymousRowTests(AuthorizeBase):
    """The row that keeps every cached tuner URL working, and the one flag
    that now applies without a principal."""

    def test_anonymous_streams_an_ordinary_channel_by_uuid(self):
        result = self._allow(SURFACE_LIVE, identifier=str(self.channel.uuid))
        self.assertEqual(result.channel_uuid, str(self.channel.uuid))
        self.assertEqual(result.user_id, "")
        self.assertTrue(result.client_id.startswith("client_"))
        self.assertEqual(result.relay_name, "py")

    def test_anonymous_is_refused_a_hidden_channel(self):
        with self.assertRaises(AuthorizeDenied) as caught:
            self._allow(SURFACE_LIVE, identifier=str(self.hidden.uuid))
        self.assertEqual(caught.exception.status, 403)

    def test_anonymous_still_streams_an_adult_channel(self):
        # hide_adult_content is a per-user preference; there is no user
        # here, so it is not applicable rather than skipped.
        result = self._allow(SURFACE_LIVE, identifier=str(self.adult.uuid))
        self.assertEqual(result.channel_uuid, str(self.adult.uuid))

    def test_an_unresolvable_identifier_is_404(self):
        with self.assertRaises(AuthorizeDenied) as caught:
            self._allow(SURFACE_LIVE, identifier="not-a-channel-or-a-hash")
        self.assertEqual(caught.exception.status, 404)


class AdminRowTests(AuthorizeBase):
    def _as(self, user, surface, **kwargs):
        request = self._request()
        with patch.object(authorize, "network_access_allowed", return_value=True), \
             patch.object(authorize, "_drf_user", return_value=user):
            return authorize_stream(request, surface, **kwargs)

    def test_admin_streams_a_hidden_channel(self):
        result = self._as(self.admin, SURFACE_LIVE, identifier=str(self.hidden.uuid))
        self.assertEqual(result.user_id, str(self.admin.id))

    def test_admin_streams_an_adult_channel(self):
        self._as(self.admin, SURFACE_LIVE, identifier=str(self.adult.uuid))

    def test_admin_streams_a_user_level_gated_channel(self):
        self._as(self.admin, SURFACE_LIVE, identifier=str(self.gated.uuid))

    def test_admin_still_hits_the_stream_limit(self):
        # The one check an admin does not bypass: a slot they hold is the
        # same provider slot.
        with patch.object(authorize, "check_user_stream_limits", return_value=False):
            with self.assertRaises(AuthorizeDenied) as caught:
                self._as(self.admin, SURFACE_LIVE, identifier=str(self.channel.uuid))
        self.assertEqual(caught.exception.status, 429)


class NonAdminRowTests(AuthorizeBase):
    def _as(self, user, surface, **kwargs):
        with patch.object(authorize, "network_access_allowed", return_value=True), \
             patch.object(authorize, "_drf_user", return_value=user):
            return authorize_stream(self._request(), surface, **kwargs)

    def test_standard_user_is_refused_a_hidden_channel(self):
        with self.assertRaises(AuthorizeDenied) as caught:
            self._as(self.standard, SURFACE_LIVE, identifier=str(self.hidden.uuid))
        self.assertEqual(caught.exception.status, 403)

    def test_hide_adult_content_user_is_refused_an_adult_channel(self):
        # Issue #87, at the one place every surface goes through.
        with self.assertRaises(AuthorizeDenied) as caught:
            self._as(self.filtered, SURFACE_LIVE, identifier=str(self.adult.uuid))
        self.assertEqual(caught.exception.status, 403)

    def test_standard_user_still_streams_an_adult_channel_without_the_preference(self):
        self._as(self.standard, SURFACE_LIVE, identifier=str(self.adult.uuid))

    def test_user_level_below_the_channel_is_refused(self):
        with self.assertRaises(AuthorizeDenied) as caught:
            self._as(self.standard, SURFACE_LIVE, identifier=str(self.gated.uuid))
        self.assertEqual(caught.exception.status, 403)

    def test_membership_filter_applies_when_the_user_has_profiles(self):
        profile = ChannelProfile.objects.create(name="pr5-profile")
        self.standard.channel_profiles.add(profile)
        self.addCleanup(self.standard.channel_profiles.clear)
        ChannelProfileMembership.objects.filter(
            channel_profile=profile, channel=self.channel
        ).update(enabled=False)
        with self.assertRaises(AuthorizeDenied) as caught:
            self._as(self.standard, SURFACE_LIVE, identifier=str(self.channel.uuid))
        self.assertEqual(caught.exception.status, 403)


class InternalPrincipalRowTests(AuthorizeBase):
    """The DVR. No account, no user_level, no profiles — and a recording of
    a hidden or adult channel must not break."""

    def _internal(self, surface, **kwargs):
        request = self._request(
            HTTP_X_DISPATCHARR_INTERNAL=internal_auth.internal_principal_token()
        )
        with patch.object(authorize, "network_access_allowed", return_value=True):
            return authorize_stream(request, surface, **kwargs)

    def test_internal_streams_a_hidden_channel(self):
        result = self._internal(SURFACE_LIVE, identifier=str(self.hidden.uuid))
        self.assertEqual(result.channel_uuid, str(self.hidden.uuid))
        self.assertEqual(result.user_id, "")

    def test_internal_streams_an_adult_channel(self):
        self._internal(SURFACE_LIVE, identifier=str(self.adult.uuid))

    def test_internal_skips_the_stream_limit(self):
        with patch.object(authorize, "check_user_stream_limits", return_value=False):
            self._internal(SURFACE_LIVE, identifier=str(self.channel.uuid))

    def test_internal_does_not_skip_the_network_acl(self):
        request = self._request(
            HTTP_X_DISPATCHARR_INTERNAL=internal_auth.internal_principal_token()
        )
        with patch.object(authorize, "network_access_allowed", return_value=False):
            with self.assertRaises(AuthorizeDenied) as caught:
                authorize_stream(request, SURFACE_LIVE, identifier=str(self.channel.uuid))
        self.assertEqual(caught.exception.status, 403)

    def test_a_wrong_internal_token_is_not_a_principal(self):
        request = self._request(HTTP_X_DISPATCHARR_INTERNAL="deadbeef")
        with patch.object(authorize, "network_access_allowed", return_value=True):
            with self.assertRaises(AuthorizeDenied) as caught:
                authorize_stream(request, SURFACE_LIVE, identifier=str(self.hidden.uuid))
        self.assertEqual(caught.exception.status, 403)


class StreamByHashRowTests(AuthorizeBase):
    """/proxy/ts/stream/<stream_hash> has no channel, so no channel check
    applies — the admin UI's single-stream preview keeps working."""

    # An explicit hash, not one Stream.objects.create() produces: the field
    # is null=True and nothing in save() fills it (apps/channels/models.py
    # :92-98), so a created row's stream_hash is None — and
    # get_stream_object(None) falls through to
    # Stream.objects.get(stream_hash=None), which is an IS NULL match that
    # returns this very row. The test would then pass with the whole hash
    # branch deleted. A literal beats generate_hash_key() here because that
    # classmethod reads CoreSettings for its key list.
    HASH = "a" * 64

    def test_a_stream_hash_authorizes_with_no_channel(self):
        from apps.channels.models import Stream

        stream = Stream.objects.create(
            name="pr5-stream", url="http://x.invalid/s.ts", stream_hash=self.HASH
        )
        self.assertTrue(stream.stream_hash)
        result = self._allow(SURFACE_LIVE, identifier=stream.stream_hash)
        self.assertEqual(result.channel_uuid, "")


class XcCredentialRowTests(AuthorizeBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.xc = User.objects.create_user(
            username="pr5-xc", password="x", user_level=1,
            custom_properties={"xc_password": "s3cret"},
        )

    def test_correct_credentials_resolve_the_channel_uuid(self):
        result = self._allow(
            SURFACE_LIVE_XC,
            identifier=str(self.channel.id),
            username="pr5-xc",
            password="s3cret",
        )
        self.assertEqual(result.channel_uuid, str(self.channel.uuid))
        self.assertEqual(result.user_id, str(self.xc.id))

    def test_a_wrong_password_is_401(self):
        with self.assertRaises(AuthorizeDenied) as caught:
            self._allow(
                SURFACE_LIVE_XC, identifier=str(self.channel.id),
                username="pr5-xc", password="wrong",
            )
        self.assertEqual(caught.exception.status, 401)

    def test_an_unknown_username_is_401_not_404(self):
        # Deliberate: the XC credential surfaces answer 401 for both
        # halves, unlike player_api.php (issue #84, a separate view).
        with self.assertRaises(AuthorizeDenied) as caught:
            self._allow(
                SURFACE_LIVE_XC, identifier=str(self.channel.id),
                username="nobody", password="s3cret",
            )
        self.assertEqual(caught.exception.status, 401)

    def test_catchup_xc_uses_the_xc_api_acl_key(self):
        with patch.object(authorize, "network_access_allowed", return_value=True) as acl:
            authorize_stream(
                self._request(), SURFACE_CATCHUP_XC,
                identifier=str(self.channel.id),
                username="pr5-xc", password="s3cret",
            )
        self.assertEqual(acl.call_args.args[1], "XC_API")

    def test_live_xc_uses_the_streams_acl_key(self):
        with patch.object(authorize, "network_access_allowed", return_value=True) as acl:
            authorize_stream(
                self._request(), SURFACE_LIVE_XC,
                identifier=str(self.channel.id),
                username="pr5-xc", password="s3cret",
            )
        self.assertEqual(acl.call_args.args[1], "STREAMS")


class SurfaceScopeTests(AuthorizeBase):
    def test_vod_surfaces_run_no_channel_check_and_no_limit(self):
        # VOD content is not a Channel; the limit stays in stream_vod
        # (plan amendment S1).
        with patch.object(authorize, "check_user_stream_limits") as limits:
            result = self._allow(SURFACE_VOD, identifier="ignored")
        limits.assert_not_called()
        self.assertEqual(result.channel_uuid, "")

    def test_catchup_requires_a_principal(self):
        with self.assertRaises(AuthorizeDenied) as caught:
            self._allow(SURFACE_CATCHUP, identifier=str(self.channel.uuid))
        self.assertEqual(caught.exception.status, 401)

    def test_an_unknown_surface_fails_closed(self):
        with self.assertRaises(AuthorizeDenied) as caught:
            self._allow("not-a-surface", identifier="x")
        self.assertEqual(caught.exception.status, 403)

    def test_the_output_profile_id_is_resolved_from_the_query(self):
        from core.models import OutputProfile

        profile = OutputProfile.objects.create(name="pr5-out", is_active=True)
        request = self.factory.get(
            f"/proxy/ts/stream/x?output_profile={profile.id}"
        )
        with patch.object(authorize, "network_access_allowed", return_value=True):
            result = authorize_stream(
                request, SURFACE_LIVE, identifier=str(self.channel.uuid)
            )
        self.assertEqual(result.output_profile_id, str(profile.id))


class AuthHelpersDbTests(TestCase):
    """resolve_xc_user (xc_password custom property) and
    user_can_access_channel (user_level gate) - exercised against real models
    instead of being mocked away.

    Moved from apps/timeshift/tests/test_views.py: the subject (the two
    helpers this exercises) now lives in apps.proxy.authorize."""

    @classmethod
    def setUpTestData(cls):
        cls.viewer = User.objects.create(
            username="ts-test-viewer", user_level=0,
            custom_properties={"xc_password": "right-pass"},
        )
        cls.no_xc = User.objects.create(
            username="ts-test-noxc", user_level=10,
            custom_properties={},
        )
        cls.basic_channel = Channel.objects.create(name="ts-test-basic", user_level=0)
        cls.admin_channel = Channel.objects.create(name="ts-test-adult", user_level=10)

    def test_valid_xc_password_authenticates(self):
        user = authorize.resolve_xc_user("ts-test-viewer", "right-pass")
        self.assertIsNotNone(user)
        self.assertEqual(user.id, self.viewer.id)

    def test_wrong_xc_password_rejected(self):
        self.assertIsNone(authorize.resolve_xc_user("ts-test-viewer", "wrong"))

    def test_user_without_xc_password_rejected(self):
        # Accounts with no xc_password set (e.g. admins) must be denied even
        # if the caller guesses any string - there is nothing to compare to.
        self.assertIsNone(authorize.resolve_xc_user("ts-test-noxc", ""))
        self.assertIsNone(authorize.resolve_xc_user("ts-test-noxc", "anything"))

    def test_unknown_username_rejected(self):
        self.assertIsNone(authorize.resolve_xc_user("ts-test-ghost", "x"))

    def test_user_level_gate(self):
        # Level-0 viewer with no profiles: allowed on level-0, denied on level-10.
        self.assertTrue(authorize.user_can_access_channel(self.viewer, self.basic_channel))
        self.assertFalse(authorize.user_can_access_channel(self.viewer, self.admin_channel))
