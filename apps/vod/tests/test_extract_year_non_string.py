"""`extract_year` must not raise on a non-string provider `releaseDate` (#242).

A provider sending `"releaseDate": 2011` (a bare JSON number, not a string) made
`apps/vod/tasks.py::extract_year` raise `AttributeError: 'int' object has no attribute
'split'`, because `date_string.split('-')` ran outside the function's own
`except (ValueError, IndexError)`. That exception is not caught by
`process_series_batch`, so one malformed series row aborted the whole series
refresh task. See https://github.com/D10Scot/Dispatcharr/issues/242.
"""

from django.test import SimpleTestCase

from apps.vod.tasks import extract_year


class ExtractYearNonStringTests(SimpleTestCase):
    def test_integer_release_date_yields_the_year_instead_of_raising(self):
        self.assertEqual(extract_year(2011), 2011)

    def test_shrunk_counterexample_one_does_not_raise(self):
        # The fuzz campaign's shrunk counterexample. Must match today's behaviour
        # for the string form, which already works.
        self.assertEqual(extract_year(1), extract_year("1"))
        self.assertEqual(extract_year(1), 1)

    def test_non_scalar_release_date_is_no_year_not_attribute_error(self):
        for value in ([2011], 2011.5, True):
            with self.subTest(value=value):
                self.assertIsNone(extract_year(value))
