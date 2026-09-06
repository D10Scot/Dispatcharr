"""Property-based tests for XC expiration-date parsing.

``M3UAccountProfile._parse_exp_date`` (apps/m3u/models.py) converts a
provider-controlled ``user_info.exp_date`` value (unix timestamp or ISO
string) into a datetime, and is specified to return ``None`` for anything
unparseable: its docstring says "Parse a raw exp_date value ... into a
datetime" and the body guards the conversion with
``except (ValueError, TypeError, OSError)`` plus an explicit ``None`` early
return. These properties pin the guarantees the implementation actually
makes:

- values that are plainly invalid per the docstring's contract (``None``,
  empty/whitespace/garbage strings, wrong container types) return ``None``;
- every integer/float timestamp inside the platform's representable range
  round-trips through ``datetime.fromtimestamp(..., tz=timezone.utc)`` — i.e.
  the parser never *invents* a different instant than the one the value
  denotes, and the result is always timezone-aware UTC;
- digit strings parse exactly like their numeric value;
- a parsed result is always a ``datetime`` (never a date, never a string).

The runs are ``SimpleTestCase``-based: ``_parse_exp_date`` is a pure
``@staticmethod`` that touches neither the database nor Redis.

Known gap (deliberately not asserted): values whose numeric magnitude exceeds
the platform ``time_t`` range (e.g. ``float("inf")``, ``"1e30"``) raise
``OverflowError``, which the implementation's ``except`` clause does not
cover — tracked separately as a domain-fuzz finding. These properties avoid
that range so they encode only behaviour the implementation promises.
"""

import math
from datetime import datetime, timezone

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.m3u.models import M3UAccountProfile

# CI-deterministic profile — matches the other fuzz-originated property
# suites (derandomized so a failure replays byte-identically in CI, bounded
# example count so the suite stays fast, no deadline because none of these
# properties are timing-sensitive).
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# datetime's representable epoch bounds on this platform: year 1 .. 9999.
_MIN_EPOCH = -62135596800  # 0001-01-01T00:00:00Z
_MAX_EPOCH = 253402300799  # 9999-12-31T23:59:59Z

parse = M3UAccountProfile._parse_exp_date


class ParseExpDateInvalidInputProperties(SimpleTestCase):
    """Plainly-invalid inputs return None, per the docstring contract."""

    @given(value=st.none() | st.booleans().map(lambda _: None))
    def test_none_returns_none(self, value):
        self.assertIsNone(parse(value))

    @given(
        value=st.text(
            alphabet=st.characters(
                blacklist_categories=("Nd",),  # no digits anywhere
                blacklist_characters=".eE+-_",  # and no float-syntax characters
            ),
            max_size=40,
        )
    )
    def test_garbage_string_returns_none(self, value):
        # A string with no digits and no float syntax can be neither a
        # timestamp nor an ISO date.
        self.assertIsNone(parse(value))

    @given(
        value=st.one_of(
            st.lists(st.integers(), max_size=4),
            st.dictionaries(st.text(max_size=5), st.integers(), max_size=4),
            st.sets(st.integers(), max_size=4),
            st.binary(max_size=16),
        )
    )
    def test_wrong_container_types_return_none(self, value):
        self.assertIsNone(parse(value))


class ParseExpDateTimestampProperties(SimpleTestCase):
    """Numeric timestamps round-trip through UTC exactly."""

    @given(
        value=st.integers(min_value=_MIN_EPOCH, max_value=_MAX_EPOCH)
        | st.floats(
            min_value=_MIN_EPOCH,
            max_value=_MAX_EPOCH,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    def test_in_range_numeric_roundtrips_utc(self, value):
        result = parse(value)
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.tzinfo, timezone.utc)
        # The parser must not invent a different instant than the value denotes.
        self.assertEqual(result, datetime.fromtimestamp(float(value), tz=timezone.utc))

    @given(value=st.integers(min_value=_MIN_EPOCH, max_value=_MAX_EPOCH))
    def test_digit_string_matches_numeric_value(self, value):
        from_string = parse(str(value))
        from_number = parse(value)
        self.assertEqual(from_string, from_number)

    @given(
        value=st.floats(
            min_value=_MIN_EPOCH,
            max_value=_MAX_EPOCH,
            allow_nan=False,
            allow_infinity=False,
        ).map(repr)
    )
    def test_float_repr_string_matches_float(self, value):
        # repr() of a finite float always parses back through float().
        self.assertEqual(parse(value), parse(float(value)))


class ParseExpDateShapeProperties(SimpleTestCase):
    """Anything that parses is a datetime; anything unparseable is None."""

    @given(
        value=st.one_of(
            st.none(),
            st.integers(
                min_value=_MIN_EPOCH,
                max_value=_MAX_EPOCH,
            ),
            st.floats(
                min_value=_MIN_EPOCH,
                max_value=_MAX_EPOCH,
                allow_nan=False,
                allow_infinity=False,
            ),
            st.text(max_size=40).filter(
                lambda s: not _could_be_out_of_range_number(s)
            ),
        )
    )
    def test_result_is_datetime_or_none(self, value):
        result = parse(value)
        self.assertTrue(result is None or isinstance(result, datetime))

    @given(value=st.just("None") | st.just("") | st.just("null"))
    def test_docstring_sentinels_return_none(self, value):
        # The docstring names None / "None" / empty as non-adult... that is
        # parse_is_adult's wording; here the contract is "unparseable -> None".
        self.assertIsNone(parse(value))


def _could_be_out_of_range_number(s):
    """True when the string parses as a float outside the time_t range.

    Such strings raise OverflowError (the known finding above) rather than
    returning None or a datetime, so shape properties must not feed them.
    """
    try:
        f = float(s)
    except (TypeError, ValueError):
        return False
    return math.isinf(f) or abs(f) > _MAX_EPOCH
