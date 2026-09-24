"""#110 — hide_adult_content hid adult movies from the XC listings but not
from the streaming routes.

`xc_get_vod_streams` and `xc_get_vod_info` (apps/output/views.py) already
refuse to *list* an adult movie to a non-admin user with the
`hide_adult_content` preference set. `stream_vod` and `stream_xc_movie`
applied no such filter, so the same movie was still streamable by UUID or
stream_id. This mirrors that listing predicate at every place `stream_vod`
resolves a movie: the XC entry point, both of the Redirect/session branches,
and the first-request UUID lookup that covers an adopted idle session (where
the session branch never sees a resolved user).

Only `Movie` carries `is_adult`; `Series` and `Episode` have neither the
field nor a listing that filters by it, so nothing about episodes changes
here (`stream_xc_episode` is untouched — see #110's per-issue analysis).
"""

import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse, HttpResponseRedirect
from django.test import RequestFactory, TestCase

from apps.m3u.models import M3UAccount
from apps.vod.models import M3UMovieRelation, Movie

User = get_user_model()


def _decision(user):
    from apps.proxy.authorize import SURFACE_VOD, AuthorizeResult

    return AuthorizeResult(
        surface=SURFACE_VOD,
        user_id=str(user.id) if user is not None else "",
        relay_name="py",
        user=user,
    )


class VodAdultFilterTestBase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.account = M3UAccount.objects.create(
            name="Provider A",
            server_url="http://a.example.com",
            username="a",
            password="a",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            priority=1,
        )
        self.adult_movie = Movie.objects.create(name="Adult Movie", is_adult=True)
        self.adult_relation = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.adult_movie,
            stream_id="m-adult",
        )
        self.clean_movie = Movie.objects.create(name="Clean Movie", is_adult=False)
        self.clean_relation = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.clean_movie,
            stream_id="m-clean",
        )

    def _hide_adult_user(self, user_level=User.UserLevel.STANDARD):
        return User.objects.create_user(
            username=f"hideadult-{uuid.uuid4().hex[:8]}",
            password="testpass123",
            user_level=user_level,
            custom_properties={"hide_adult_content": True},
        )

    def _plain_user(self, user_level=User.UserLevel.STANDARD, custom_properties=None):
        return User.objects.create_user(
            username=f"plain-{uuid.uuid4().hex[:8]}",
            password="testpass123",
            user_level=user_level,
            custom_properties=custom_properties or {},
        )

    def _request(self, path="/proxy/vod/movie/uuid/"):
        request = self.factory.get(path, HTTP_USER_AGENT="test-agent")
        request.user = MagicMock(is_authenticated=False)
        return request


class StreamXcMovieAdultFilterTests(VodAdultFilterTestBase):
    @patch("apps.proxy.vod_proxy.views.resolve_authorization")
    def test_stream_xc_movie_streamed_an_adult_movie_to_a_hide_adult_user(
        self, mock_authorize
    ):
        user = self._hide_adult_user()
        mock_authorize.return_value = _decision(user)

        request = self.factory.get(
            f"/movie/u/p/{self.adult_movie.id}.mp4", HTTP_USER_AGENT="test-agent"
        )

        from apps.proxy.vod_proxy import views

        with patch.object(views, "stream_vod", wraps=views.stream_vod) as spy_stream_vod:
            from apps.proxy.vod_proxy.views import stream_xc_movie

            response = stream_xc_movie(request, "u", "p", str(self.adult_movie.id), "mp4")

        self.assertEqual(response.status_code, 403)
        spy_stream_vod.assert_not_called()


class StreamVodRedirectBranchAdultFilterTests(VodAdultFilterTestBase):
    @patch("apps.proxy.vod_proxy.views.close_old_connections")
    @patch("apps.proxy.vod_proxy.views._find_idle_vod_session", return_value=None)
    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=True,
    )
    def test_stream_vod_redirect_branch_streamed_an_adult_movie_to_a_hide_adult_user(
        self, _is_redirect, mock_select, _idle, _close
    ):
        user = self._hide_adult_user()
        # A UUID not in the database: call (4)'s lookup misses and lets the
        # first request through, so the Redirect branch (call 2) is the only
        # thing that can still refuse it.
        unknown_uuid = str(uuid.uuid4())
        mock_select.return_value = {
            "content_obj": self.adult_movie,
            "m3u_account": self.account,
            "m3u_profile": MagicMock(),
            "current_connections": 0,
            "final_stream_url": "http://provider.example/adult.mp4",
        }

        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            self._request(),
            content_type="movie",
            content_id=unknown_uuid,
            session_id=None,
            user=user,
            decision=_decision(user),
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIsInstance(response, HttpResponseRedirect)


class StreamVodSessionBranchAdultFilterTests(VodAdultFilterTestBase):
    @patch("apps.proxy.vod_proxy.views.close_old_connections")
    @patch("apps.proxy.vod_proxy.views.MultiWorkerVODConnectionManager")
    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    def test_stream_vod_session_branch_streamed_an_adult_movie_to_a_hide_adult_user(
        self, mock_select, mock_manager_cls, _close
    ):
        user = self._hide_adult_user()
        mock_select.return_value = {
            "content_obj": self.adult_movie,
            "m3u_account": self.account,
            "m3u_profile": MagicMock(),
            "current_connections": 0,
            "final_stream_url": "http://provider.example/adult.mp4",
        }
        from django.http import StreamingHttpResponse

        mock_manager = MagicMock()
        mock_manager.stream_content_with_session.return_value = StreamingHttpResponse(
            streaming_content=iter([b"data"]),
            content_type="video/mp4",
        )
        mock_manager_cls.get_instance.return_value = mock_manager

        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            self._request("/proxy/vod/movie/uuid/session123/"),
            content_type="movie",
            content_id=str(self.adult_movie.uuid),
            session_id="session123",
            user=user,
            decision=_decision(user),
        )

        self.assertEqual(response.status_code, 403)
        mock_manager.stream_content_with_session.assert_not_called()


class StreamVodAdoptedIdleSessionAdultFilterTests(VodAdultFilterTestBase):
    @patch("apps.proxy.vod_proxy.views._vod_session_path_redirect")
    @patch(
        "apps.proxy.vod_proxy.views._find_idle_vod_session",
        return_value="idle_session_abc",
    )
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=True,
    )
    def test_an_adopted_idle_session_streamed_an_adult_movie_to_a_hide_adult_user(
        self, _is_redirect, mock_idle, mock_path_redirect
    ):
        user = self._hide_adult_user()
        mock_path_redirect.return_value = HttpResponse(
            status=301, headers={"Location": "/proxy/vod/movie/uuid/idle_session_abc"}
        )

        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            self._request(),
            content_type="movie",
            content_id=str(self.adult_movie.uuid),
            session_id=None,
            user=user,
            decision=_decision(user),
        )

        self.assertEqual(response.status_code, 403)
        mock_path_redirect.assert_not_called()
        # Call (4) is gated on `not session_id` alone, so it fires before the
        # idle-session lookup is even consulted.
        mock_idle.assert_not_called()


class StreamVodAdultFilterControlTests(VodAdultFilterTestBase):
    """The three pairings that must keep streaming: admin, no preference, no adult content."""

    @patch("apps.proxy.vod_proxy.views.close_old_connections")
    @patch("apps.proxy.vod_proxy.views._find_idle_vod_session", return_value=None)
    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=True,
    )
    def test_an_admin_with_hide_adult_content_still_streams_an_adult_movie(
        self, _is_redirect, mock_select, _idle, _close
    ):
        # A non-default pairing (admin AND the preference set): a pin that
        # supplies the default (a non-admin, or the preference absent) would
        # pass even if the admin bypass were dropped.
        user = self._hide_adult_user(user_level=User.UserLevel.ADMIN)
        mock_select.return_value = {
            "content_obj": self.adult_movie,
            "m3u_account": self.account,
            "m3u_profile": MagicMock(),
            "current_connections": 0,
            "final_stream_url": "http://provider.example/adult.mp4",
        }

        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            self._request(),
            content_type="movie",
            content_id=str(self.adult_movie.uuid),
            session_id=None,
            user=user,
            decision=_decision(user),
        )

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertEqual(response["Location"], "http://provider.example/adult.mp4")

    @patch("apps.proxy.vod_proxy.views.close_old_connections")
    @patch("apps.proxy.vod_proxy.views._find_idle_vod_session", return_value=None)
    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=True,
    )
    def test_a_user_without_hide_adult_content_still_streams_an_adult_movie(
        self, _is_redirect, mock_select, _idle, _close
    ):
        user = self._plain_user(user_level=User.UserLevel.STANDARD)
        mock_select.return_value = {
            "content_obj": self.adult_movie,
            "m3u_account": self.account,
            "m3u_profile": MagicMock(),
            "current_connections": 0,
            "final_stream_url": "http://provider.example/adult.mp4",
        }

        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            self._request(),
            content_type="movie",
            content_id=str(self.adult_movie.uuid),
            session_id=None,
            user=user,
            decision=_decision(user),
        )

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertEqual(response["Location"], "http://provider.example/adult.mp4")

    @patch("apps.proxy.vod_proxy.views.close_old_connections")
    @patch("apps.proxy.vod_proxy.views._find_idle_vod_session", return_value=None)
    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=True,
    )
    def test_a_hide_adult_user_still_streams_a_non_adult_movie(
        self, _is_redirect, mock_select, _idle, _close
    ):
        user = self._hide_adult_user()
        mock_select.return_value = {
            "content_obj": self.clean_movie,
            "m3u_account": self.account,
            "m3u_profile": MagicMock(),
            "current_connections": 0,
            "final_stream_url": "http://provider.example/clean.mp4",
        }

        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            self._request(),
            content_type="movie",
            content_id=str(self.clean_movie.uuid),
            session_id=None,
            user=user,
            decision=_decision(user),
        )

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertEqual(response["Location"], "http://provider.example/clean.mp4")
