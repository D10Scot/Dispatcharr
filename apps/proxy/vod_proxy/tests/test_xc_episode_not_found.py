"""stream_xc_episode answers 404 for an unknown episode id, not 500 (#99)."""

from unittest.mock import patch

from django.test import RequestFactory, TestCase

from apps.proxy.authorize import SURFACE_VOD_XC, AuthorizeResult


def _decision():
    return AuthorizeResult(surface=SURFACE_VOD_XC, user_id="", relay_name="py", user=None)


class StreamXcEpisodeNotFoundTests(TestCase):
    @patch("apps.proxy.vod_proxy.views.stream_vod")
    @patch("apps.proxy.vod_proxy.views.resolve_authorization", return_value=_decision())
    def test_an_unknown_episode_id_dereferenced_none_and_was_a_500(self, _auth, stream_vod):
        from apps.proxy.vod_proxy.views import stream_xc_episode

        request = RequestFactory().get("/series/u/p/987654321.mp4")
        response = stream_xc_episode(request, username="u", password="p", stream_id=987654321, extension="mp4")
        self.assertEqual(response.status_code, 404)
        stream_vod.assert_not_called()
