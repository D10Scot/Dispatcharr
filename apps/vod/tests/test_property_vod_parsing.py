"""Property-based tests for VOD provider-data date parsing.

``apps.vod.tasks.parse_date`` consumes the ``air_date`` / ``releasedate`` /
``release_date`` strings stored by arbitrary IPTV providers during VOD
refresh. Its documented contract is deliberately forgiving: return a
``datetime`` when the string parses as ISO-8601 or ``%Y-%m-%d``, otherwise
return None — and never raise, whatever the provider sent. A crash here
aborts a whole series/movie refresh task.

Also covers the ``apps.output.streaming_chunk_cache`` chunk codec: the leader
stores whatever the source generator yields (text) via ``_encode_chunk`` and
followers read it back with ``_decode_chunk``; text must round-trip exactly,
which is what keeps a follower's response byte-identical to the leader's.

Runs without Redis or the database (SimpleTestCase, pure functions).
"""

from datetime import datetime

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.output.streaming_chunk_cache import _decode_chunk, _encode_chunk
from apps.vod.tasks import parse_date

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Provider date strings: mostly ISO-shaped, plus the junk providers actually
# send — whitespace padding, slashes, truncated values, unicode digits.
dateish = st.one_of(
    st.datetimes().map(lambda d: d.isoformat()),
    st.dates().map(str),
    st.text(
        alphabet="0123456789-/:TZ. +",
        min_size=0,
        max_size=40,
    ),
    st.text(max_size=40),
    st.none(),
    st.just(""),
)


class ParseDateProperties(SimpleTestCase):
    @given(value=dateish)
    def test_never_raises_and_result_type_is_stable(self, value):
        result = parse_date(value)
        self.assertTrue(result is None or isinstance(result, datetime))

    @given(d=st.dates())
    def test_canonical_iso_date_always_parses(self, d):
        result = parse_date(str(d))
        self.assertIsNotNone(result)
        self.assertEqual((result.year, result.month, result.day), (d.year, d.month, d.day))


class ChunkCodecProperties(SimpleTestCase):
    @given(chunk=st.text(max_size=2000))
    def test_text_round_trips_byte_identically(self, chunk):
        self.assertEqual(_decode_chunk(_encode_chunk(chunk)), chunk)

    @given(chunk=st.text(max_size=2000))
    def test_encode_produces_bytes_for_text(self, chunk):
        encoded = _encode_chunk(chunk)
        self.assertIsInstance(encoded, bytes)
        self.assertEqual(encoded, chunk.encode("utf-8"))
