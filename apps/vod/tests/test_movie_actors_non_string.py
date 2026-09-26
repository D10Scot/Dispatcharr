"""A provider's non-string `actors`/`cast` must not drop the movie from the refresh (#468).

`process_movie_batch` read `actors_raw = movie_data.get('actors') or movie_data.get('cast')
or ''` and then, for a non-list value, called `actors_raw.strip()`. A provider sending an
int or a dict for either field made that call raise `AttributeError: '<type>' object has
no attribute 'strip'`; the per-movie `except Exception` at the bottom of the batch loop
swallowed it with an ERROR log, so the movie was skipped on every refresh. The list branch
had the same shape one level down: `s.strip()` was called on the raw list element after a
`s and str(s).strip()` filter that let a truthy non-string element (e.g. an int) through,
so `['Bob', 5]` raised the same `AttributeError` on the `5`.

Same class of defect as #242 (`extract_year`, see test_extract_year_non_string.py).

Fix (apps/vod/tasks.py, process_movie_batch): a non-string, non-list actors/cast value is
now treated as absent (`actors = None`) rather than stringified — a stringified dict in
`custom_properties['actors']` would be worse for the UI than no actors at all, and this
mirrors `extract_string_from_array_or_string`'s own handling of a scalar. A list element is
now `str()`-coerced before `.strip()`, so a non-string element no longer raises; the
existing truthiness filter (drop `0`, `''`, `None`) is unchanged. The same list-branch shape
existed a second time in `refresh_movie_advanced_data`'s advanced-info actors merge and is
fixed the same way there.

Invariant pinned here: the movie is NOT dropped, and
`Movie.custom_properties['actors']`, when present, is always a string.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.vod.models import (
    M3UMovieRelation,
    M3UVODCategoryRelation,
    Movie,
    VODCategory,
)
from apps.vod.tasks import process_movie_batch, refresh_movie_advanced_data


class VODMovieActorsNonStringTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Test XC",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.category = VODCategory.objects.create(
            name="Test Movies",
            category_type="movie",
        )
        self.cat_relation = M3UVODCategoryRelation.objects.create(
            category=self.category,
            m3u_account=self.account,
            enabled=True,
        )
        self.categories = {
            "10": self.category,
            "__uncategorized__": self.category,
        }
        self.relations = {self.category.id: self.cat_relation}

    def _list_row(self, stream_id, tmdb_id, name, **overrides):
        row = {
            "stream_id": stream_id,
            "name": name,
            "category_id": "10",
            "tmdb_id": tmdb_id,
            "container_extension": "mkv",
        }
        row.update(overrides)
        return row

    def _process(self, row):
        process_movie_batch(
            self.account,
            [row],
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )

    def _custom_props(self, tmdb_id):
        # actors/director/trailer/release_date land in Movie.custom_properties
        # (set from movie_props in process_movie_batch); M3UMovieRelation's own
        # custom_properties only ever holds basic_data/detailed_* bookkeeping.
        movie = Movie.objects.get(tmdb_id=tmdb_id)
        M3UMovieRelation.objects.get(m3u_account=self.account, movie=movie)
        return movie, movie.custom_properties or {}

    def test_int_actors_value_does_not_drop_the_movie(self):
        row = self._list_row(4681, "468001", "Int Actors Film", actors=5)
        self._process(row)

        self.assertEqual(Movie.objects.count(), 1)
        movie, props = self._custom_props("468001")
        self.assertEqual(movie.name, "Int Actors Film")
        actors = props.get("actors")
        # Pin the chosen "scalar = absent" semantics, not just "didn't crash".
        self.assertIsNone(actors)

    def test_dict_actors_value_does_not_drop_the_movie(self):
        row = self._list_row(4682, "468002", "Dict Actors Film", actors={"name": "Bob"})
        self._process(row)

        self.assertEqual(Movie.objects.count(), 1)
        movie, props = self._custom_props("468002")
        self.assertEqual(movie.name, "Dict Actors Film")
        actors = props.get("actors")
        # A stringified dict would be worse than nothing in the UI: treated as absent.
        self.assertIsNone(actors)

    def test_int_cast_value_with_actors_absent_does_not_drop_the_movie(self):
        row = self._list_row(4683, "468003", "Int Cast Film", cast=7)
        self._process(row)

        self.assertEqual(Movie.objects.count(), 1)
        movie, props = self._custom_props("468003")
        self.assertEqual(movie.name, "Int Cast Film")
        actors = props.get("actors")
        # Pin the chosen "scalar = absent" semantics, not just "didn't crash".
        self.assertIsNone(actors)

    def test_list_with_non_string_element_does_not_drop_the_movie(self):
        row = self._list_row(4684, "468004", "Mixed List Film", actors=["Alice", 5, "Bob"])
        self._process(row)

        self.assertEqual(Movie.objects.count(), 1)
        movie, props = self._custom_props("468004")
        self.assertEqual(movie.name, "Mixed List Film")
        actors = props.get("actors")
        self.assertIsInstance(actors, str)
        # The non-string element is coerced via str(), not dropped by the fix.
        self.assertIn("Alice", actors)
        self.assertIn("5", actors)
        self.assertIn("Bob", actors)

    def test_non_string_stream_icon_does_not_drop_the_movie(self):
        # Neighbouring field of the same shape (#468): len(logo_url) would raise
        # TypeError for a non-string stream_icon, outside the per-movie try/except.
        row = self._list_row(4685, "468005", "Int Logo Film", stream_icon=12345)
        self._process(row)

        self.assertEqual(Movie.objects.count(), 1)
        movie, _props = self._custom_props("468005")
        self.assertEqual(movie.name, "Int Logo Film")

    @patch("core.xtream_codes.Client")
    def test_advanced_refresh_actors_list_with_non_string_element(self, mock_client_cls):
        # refresh_movie_advanced_data's own actors-merge list branch
        # (apps/vod/tasks.py, ~line 2341) has the identical shape bug as
        # process_movie_batch's: s.strip() called on a raw, possibly non-string,
        # list element. Drive it through the provider "info" payload rather than
        # a list-sync row, mocking the XC client the way
        # test_vod_sync_preserve_details.py's
        # test_refresh_runs_when_detailed_fetched_false_despite_recent_timestamp does.
        movie = Movie.objects.create(name="Advanced Actors Film", year=2020, tmdb_id="468006")
        relation = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=movie,
            category=self.category,
            stream_id="4686",
            container_extension="mkv",
        )

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_vod_info.return_value = {
            "info": {"actors": ["A", 5]},
            "movie_data": {"stream_id": "4686", "name": movie.name},
        }

        result = refresh_movie_advanced_data(relation.id, force_refresh=True)

        self.assertEqual(result, "Advanced data refreshed.")
        movie.refresh_from_db()
        actors = (movie.custom_properties or {}).get("actors")
        self.assertIsInstance(actors, str)
        self.assertIn("A", actors)
        self.assertIn("5", actors)
