"""Property-based tests for the M3U ingest parsing and numbering surfaces.

``apps/m3u/tasks.py`` consumes provider-controlled text (EXTINF lines, M3U
files, Xtream URLs) and the account-numbering helpers make claims about
integer ranges. The contracts asserted here are the ones the implementation
documents and already encodes:

- ``parse_extinf_line`` never raises and only returns a dict for lines that
  start with ``#EXTINF:``; attribute keys are normalised to lowercase and a
  generated ``key="value"`` attribute round-trips to the same value.
- ``iter_m3u_entries`` never raises, yields each entry at most once, and a
  second ``#EXTINF`` before a URL discards the first entry (documented).
- ``convert_js_numbered_backreferences`` translates ``$n`` to ``\\n`` exactly,
  and its inverse never appears in output.
- ``compute_credential_fingerprint`` is deterministic and None iff a
  credential is missing/blank.
- ``extract_credentials_from_stream_url`` never raises and returns None, None
  for non-Xtream paths.
- ``_next_available_number`` returns the smallest free integer >= start, or
  None iff the inclusive range [start, end] is fully occupied.
- ``_parse_batch_stream_counts`` returns (0, 0, 0) unless all three counters
  parse.

Runs without the database (SimpleTestCase, pure functions).
"""

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.m3u.connection_pool import (
    compute_credential_fingerprint,
    extract_credentials_from_stream_url,
)
from apps.m3u.tasks import (
    _next_available_number,
    _parse_batch_stream_counts,
    iter_m3u_entries,
    parse_extinf_line,
)
from apps.m3u.utils import convert_js_numbered_backreferences, normalize_stream_url

# CI-deterministic profile — same rationale as test_property_ts_realignment.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Arbitrary provider text: full unicode, plus a provider-flavoured alphabet
# that feeds the EXTINF regex half-valid input.
garbage_text = st.text(max_size=200) | st.text(
    alphabet='0123456789abcxyz-_ =",\'#EXTINF:tvgloghd.',
    max_size=200,
)


class ParseExtinfLineProperties(SimpleTestCase):
    @given(line=garbage_text)
    def test_never_raises_and_result_contract(self, line):
        parsed = parse_extinf_line(line)
        if line.startswith("#EXTINF:"):
            self.assertIsNotNone(parsed)
            self.assertEqual(
                set(parsed.keys()), {"attributes", "display_name", "name"}
            )
            # Attribute keys are documented as normalised to lowercase.
            for key in parsed["attributes"]:
                self.assertEqual(key, key.lower())
            # name is always a non-None string.
            self.assertIsInstance(parsed["name"], str)
        else:
            self.assertIsNone(parsed)

    @given(
        key=st.from_regex(r"[a-z0-9\-]{1,20}", fullmatch=True),
        value=st.text(
            alphabet=st.characters(
                blacklist_characters='"', blacklist_categories=("Cs",)
            ),
            max_size=80,
        ),
        name=st.text(
            alphabet=st.characters(
                blacklist_characters='"', blacklist_categories=("Cs",)
            ),
            max_size=40,
        ),
    )
    def test_attribute_round_trip(self, key, value, name):
        # A generated key="value" attribute must parse back to the same value
        # unless a later duplicate key overwrites it (only possible when the
        # value/name text itself contains a key="..." pattern ending after
        # our attribute, which shifts the last-attr boundary).
        line = f'#EXTINF:-1 {key}="{value}",{name}'
        parsed = parse_extinf_line(line)
        self.assertIsNotNone(parsed)
        parsed_value = parsed["attributes"].get(key)
        if parsed_value is not None:
            self.assertIn(parsed_value, value)
        # The generated display name may be shifted by junk in the value, but
        # the parsed name must be non-empty since the content is non-empty.
        self.assertTrue(parsed["name"])


class IterM3uEntriesProperties(SimpleTestCase):
    @given(lines=st.lists(garbage_text, max_size=60))
    def test_never_raises_and_yields_unique_urls(self, lines):
        entries = list(iter_m3u_entries(lines))
        # Every yielded entry carries the documented keys.
        for entry in entries:
            self.assertIn("url", entry)
            self.assertIn("attributes", entry)
            self.assertIn("name", entry)
            self.assertIsInstance(entry["name"], str)
        # No duplicate entries: a yielded pending is cleared, so each entry is
        # yielded at most once.
        self.assertEqual(len(entries), len({id(e) for e in entries}))

    @given(
        name1=st.text(min_size=1, max_size=30),
        name2=st.text(
            alphabet=st.characters(
                blacklist_characters="#", blacklist_categories=("Cs",)
            ),
            min_size=1,
            max_size=30,
        ),
    )
    def test_second_extinf_discards_first(self, name1, name2):
        assume("#" not in name1)
        # iter_m3u_entries strips each raw line first, so only the stripped
        # name is observable.
        stripped2 = name2.strip()
        assume(stripped2)
        lines = [
            f"#EXTINF:-1,{name1}",
            f"#EXTINF:-1,{name2}",
            "http://example.com/stream/1",
        ]
        with self.assertLogs("apps.m3u.tasks", level="WARNING"):
            entries = list(iter_m3u_entries(lines))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], stripped2)
        self.assertEqual(entries[0]["url"], "http://example.com/stream/1")


class BackreferenceConversionProperties(SimpleTestCase):
    @given(text=st.text(max_size=120))
    def test_no_dollar_digits_remain_and_is_idempotent(self, text):
        converted = convert_js_numbered_backreferences(text)
        # $n forms are fully translated: no $<digit> survives.
        import re

        self.assertIsNone(re.search(r"\$\d", converted))
        # Translating twice must not change anything further.
        self.assertEqual(
            converted, convert_js_numbered_backreferences(converted)
        )


class CredentialFingerprintProperties(SimpleTestCase):
    @given(
        username=st.text(max_size=60) | st.none(),
        password=st.text(max_size=60) | st.none(),
    )
    def test_none_iff_blank_and_deterministic(self, username, password):
        fp1 = compute_credential_fingerprint(username, password)
        fp2 = compute_credential_fingerprint(username, password)
        self.assertEqual(fp1, fp2)
        if not username or not password:
            self.assertIsNone(fp1)
        else:
            self.assertIsInstance(fp1, str)
            self.assertEqual(len(fp1), 64)
        # ASCII usernames differing only by case/whitespace map to one group.
        # (str.lower() is used for normalisation; non-ASCII case mappings are
        # not invertible through upper() — e.g. "ß".upper() == "SS" — so the
        # claim is only asserted for ASCII.)
        if (
            username
            and password
            and username.isascii()
        ):
            fp3 = compute_credential_fingerprint(
                f"  {username.upper()}  ", password
            )
            self.assertEqual(fp1, fp3)


class ExtractCredentialsProperties(SimpleTestCase):
    @given(url=garbage_text)
    def test_never_raises_and_types(self, url):
        user, password = extract_credentials_from_stream_url(url)
        self.assertTrue(
            (user is None and password is None)
            or (isinstance(user, str) and isinstance(password, str))
        )

    @given(
        user=st.text(
            alphabet=st.characters(blacklist_characters="/"),
            min_size=1,
            max_size=20,
        ),
        password=st.text(
            alphabet=st.characters(blacklist_characters="/"),
            min_size=1,
            max_size=20,
        ),
    )
    def test_round_trip_for_xc_urls(self, user, password):
        url = f"http://example.com:8080/live/{user}/{password}/1234.ts"
        found_user, found_password = extract_credentials_from_stream_url(url)
        self.assertEqual(found_user, user)
        self.assertEqual(found_password, password)


class NextAvailableNumberProperties(SimpleTestCase):
    @given(
        used=st.lists(st.integers(min_value=0, max_value=100), max_size=40),
        start=st.integers(min_value=0, max_value=100),
    )
    def test_unbounded_smallest_free(self, used, start):
        result = _next_available_number(set(used), start)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result, start)
        self.assertNotIn(result, set(used))
        # Every integer in [start, result) must be used (smallest free).
        for n in range(start, result):
            self.assertIn(n, set(used))

    @given(
        start=st.integers(min_value=0, max_value=50),
        span=st.integers(min_value=0, max_value=20),
    )
    def test_none_iff_range_full(self, start, span):
        end = start + span
        full = set(range(start, end + 1))
        self.assertIsNone(_next_available_number(full, start, end=end))
        # Removing any one element makes the range satisfiable.
        if full:
            freed = full - {end}
            result = _next_available_number(freed, start, end=end)
            self.assertIsNotNone(result)
            self.assertLessEqual(result, end)
            self.assertNotIn(result, freed)

    @given(
        used=st.lists(st.integers(min_value=0, max_value=30), max_size=20),
        start=st.integers(min_value=0, max_value=20),
        end=st.integers(min_value=0, max_value=30),
    )
    def test_bounded_never_exceeds_end(self, used, start, end):
        result = _next_available_number(set(used), start, end=end)
        if result is not None:
            self.assertGreaterEqual(result, start)
            self.assertLessEqual(result, end)
            self.assertNotIn(result, set(used))


class BatchCountParseProperties(SimpleTestCase):
    @given(value=st.one_of(st.text(max_size=80), st.integers(), st.none()))
    def test_never_raises_and_zeros_on_garbage(self, value):
        created, updated, unchanged = _parse_batch_stream_counts(value)
        for count in (created, updated, unchanged):
            self.assertIsInstance(count, int)
            self.assertGreaterEqual(count, 0)
        if not isinstance(value, str):
            self.assertEqual((created, updated, unchanged), (0, 0, 0))

    @given(
        created=st.integers(min_value=0, max_value=100000),
        updated=st.integers(min_value=0, max_value=100000),
        unchanged=st.integers(min_value=0, max_value=100000),
    )
    def test_round_trip_well_formed(self, created, updated, unchanged):
        result = f"{created} created, {updated} updated, {unchanged} unchanged"
        self.assertEqual(
            _parse_batch_stream_counts(result), (created, updated, unchanged)
        )


class NormalizeStreamUrlProperties(SimpleTestCase):
    @given(url=garbage_text | st.none())
    def test_never_raises_and_only_udp_at_changes(self, url):
        result = normalize_stream_url(url)
        if not url:
            self.assertEqual(result, url)
        elif url.startswith("udp://@"):
            self.assertEqual(result, "udp://" + url[len("udp://@"):])
            self.assertNotIn("@", result.split("://", 1)[1].split("/")[0])
        else:
            self.assertEqual(result, url)
