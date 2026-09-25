"""xc_get_vod_info merges the relation's detailed_info whatever Movie.custom_properties holds (#97)."""

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.output.views import xc_get_vod_info
from apps.vod.models import M3UMovieRelation, Movie

User = get_user_model()

SPARSE = {"bitrate": 4321, "video": {"codec_name": "h264"}, "audio": {"codec_name": "aac"}, "plot": "From the provider."}


class XcGetVodInfoDetailedInfoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="xcvoddetail", password="x")
        self.user.user_level = 10
        self.user.save()
        account = M3UAccount.objects.create(
            name="P", server_url="http://p.example", username="u", password="p",
            account_type=M3UAccount.Types.XC, is_active=True, custom_properties={"enable_vod": True},
        )
        # Movie.custom_properties is None: set explicitly, never inherited from a default.
        self.movie = Movie.objects.create(name="Sparse", year=2020, custom_properties=None)
        M3UMovieRelation.objects.create(
            m3u_account=account, movie=self.movie, stream_id="s-1",
            last_advanced_refresh=timezone.now(),
            custom_properties={"detailed_fetched": True, "detailed_info": SPARSE},
        )

    def _info(self):
        return xc_get_vod_info(RequestFactory().get("/player_api.php"), self.user, str(self.movie.id))["info"]

    def test_detailed_info_was_dropped_when_the_movie_had_no_custom_properties(self):
        info = self._info()
        self.assertEqual(info["bitrate"], 4321)
        self.assertEqual(info["video"], {"codec_name": "h264"})
        self.assertEqual(info["audio"], {"codec_name": "aac"})
        self.assertEqual(info["plot"], "From the provider.")

    def test_movie_custom_properties_still_win_where_they_are_set(self):
        self.movie.custom_properties = {"director": "Movie Director"}
        self.movie.save(update_fields=["custom_properties"])
        self.assertEqual(self._info()["director"], "Movie Director")
