"""Property-based tests for M3U ingestion parsing and channel-number allocation.

Surfaces covered (all in ``apps/m3u/``):

* ``tasks.parse_extinf_line`` — attribute extraction and display-name fallback
  from ``#EXTINF`` lines. The implementation promises (docstring): every
  ``key="value"`` pair lands in ``attributes`` with the key lowercased; text
  after the last attribute is the display name; ``name`` is never empty for
  non-empty content; non-``#EXTINF:`` input returns ``None``.
* ``tasks.iter_m3u_entries`` — generator assembly of stream entries from raw
  lines. The docstring promises: a second ``#EXTINF`` before a URL discards
  the pending entry; entries are yielded exactly once, in order, with a
  ``url`` key; unrecognised lines never produce entries by themselves.
* ``tasks.get_case_insensitive_attr`` — case-insensitive dict lookup with a
  default. The function returns the first value whose key case-matches, or
  the default.
* ``tasks._next_available_number`` / ``tasks._pick_target_number`` — channel
  number allocation. The docstrings promise: the result is always free (not
  in ``used_numbers``); for ``provider`` mode a free provider number is used
  as-is; ``next_available`` starts at 1; ``None`` signals range exhaustion.
* ``utils.convert_js_numbered_backreferences`` — translation of JS-style
  ``$N`` backreferences to Python ``\\N``. The promised invariant (shared by
  the live rename and the UI preview): every ``$<digits>`` token becomes
  ``\\<digits>`` and all other characters pass through untouched.

These tests run without the database or Redis: every class is a
``SimpleTestCase`` over pure functions.
"""

import string
from types import SimpleNamespace

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.m3u.tasks import (
    _next_available_number,
    _pick_target_number,
    get_case_insensitive_attr,
    iter_m3u_entries,
    parse_extinf_line,
)
from apps.m3u.utils import convert_js_numbered_backreferences

# CI-deterministic profile. Registered/loaded at module import because the
# Django test runner has no pytest-style conftest hook. derandomize=True makes
# runs reproducible; deadline=None because CI container timing is noisy.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Attribute keys as accepted by _EXTINF_ATTR_RE: no whitespace, no '='.
attr_keys = st.text(
    alphabet=string.ascii_letters + string.digits + "-_", min_size=1, max_size=12
)

# Attribute values with no quote characters at all — both quote styles must
# survive intact for these.
bare_attr_values = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",), blacklist_characters=("\"", "'", "\n", "\r")
    ),
    max_size=30,
)

# Display names: printable, no newline (lines are split on newlines upstream).
display_names = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",), blacklist_characters=("\n", "\r")
    ),
    max_size=40,
)


@st.composite
def extinf_lines(draw):
    """Build an #EXTINF line from drawn attributes and a display name.

    Attribute values are drawn quote-free and may be rendered with either
    quote style; the display name never starts with a key= token so the
    attribute regex cannot extend into it.
    """
    n_attrs = draw(st.integers(min_value=0, max_value=4))
    attrs = []
    seen = set()
    for _ in range(n_attrs):
        key = draw(attr_keys)
        if key.lower() in seen:
            # Last-write-wins makes duplicate keys unobservable; skip them.
            continue
        seen.add(key.lower())
        value = draw(bare_attr_values)
        quote = draw(st.sampled_from(('"', "'")))
        attrs.append((key, value, quote))
    display = draw(display_names)
    # Keep the display name from looking like another attribute, which would
    # legitimately be parsed as one.
    assume("=" not in display.split(" ", 1)[0])
    parts = " ".join(f"{k}={q}{v}{q}" for k, v, q in attrs)
    content = f"-1 {parts},{display}" if parts else f"-1,{display}"
    return "#EXTINF:" + content, {k.lower(): v for k, v, _ in attrs}, display


# ---------------------------------------------------------------------------
# parse_extinf_line
# ---------------------------------------------------------------------------


class ParseExtinfLineProperties(SimpleTestCase):
    @given(drawn=extinf_lines())
    def test_round_trips_attributes_and_display_name(self, drawn):
        line, expected_attrs, display = drawn

        parsed = parse_extinf_line(line)

        self.assertIsNotNone(parsed)
        # Every rendered attribute is recovered, key lowercased.
        for key, value in expected_attrs.items():
            self.assertEqual(parsed["attributes"].get(key), value)
        self.assertEqual(parsed["display_name"], display.strip())
        # name is the comma text when present (base EXTINF spec), and is
        # never empty while the line has content.
        if display.strip():
            self.assertEqual(parsed["name"], display.strip())
        self.assertTrue(parsed["name"])

    @given(content=st.text(max_size=60))
    def test_never_raises_and_returns_none_without_prefix(self, content):
        assume(not content.startswith("#EXTINF:"))
        self.assertIsNone(parse_extinf_line(content))

    @given(content=st.text(max_size=80))
    def test_arbitrary_extinf_content_never_crashes_and_name_is_nonempty(
        self, content
    ):
        assume("\n" not in content and "\r" not in content)
        assume(content.strip() != "")
        parsed = parse_extinf_line("#EXTINF:" + content)
        self.assertIsNotNone(parsed)
        # Guaranteed by the final `or content.strip()` fallback.
        self.assertTrue(parsed["name"])
        self.assertIsInstance(parsed["attributes"], dict)
        self.assertIsInstance(parsed["display_name"], str)


# ---------------------------------------------------------------------------
# iter_m3u_entries
# ---------------------------------------------------------------------------


class IterM3uEntriesProperties(SimpleTestCase):
    @given(
        names=st.lists(display_names, min_size=1, max_size=8),
        url_suffixes=st.lists(
            st.text(
                alphabet=string.ascii_letters + string.digits + "/._-",
                min_size=1,
                max_size=20,
            ),
            min_size=1,
            max_size=8,
        ),
        scheme=st.sampled_from(("http", "rtsp", "rtp")),
    )
    def test_every_extinf_followed_by_url_yields_exactly_once(
        self, names, url_suffixes, scheme
    ):
        assume(len(names) >= len(url_suffixes))
        lines = []
        for name, suffix in zip(names, url_suffixes):
            lines.append(f"#EXTINF:-1,{name}")
            lines.append(f"{scheme}://host/{suffix}")

        entries = list(iter_m3u_entries(lines))

        self.assertEqual(len(entries), len(url_suffixes))
        for entry, suffix in zip(entries, url_suffixes):
            self.assertEqual(entry["url"], f"{scheme}://host/{suffix}")

    @given(
        junk_lines=st.lists(
            st.text(
                alphabet=string.ascii_letters + string.digits + " #=-_\"',",
                min_size=1,
                max_size=30,
            ),
            min_size=0,
            max_size=6,
        )
    )
    def test_lines_without_extinf_and_url_yield_nothing(self, junk_lines):
        # Filter out anything that could itself start an entry or complete one.
        cleaned = [
            line
            for line in junk_lines
            if not line.strip().startswith(("#EXTINF", "http", "rtsp", "rtp", "udp"))
        ]
        self.assertEqual(list(iter_m3u_entries(cleaned)), [])

    @given(
        first_names=st.lists(display_names, min_size=2, max_size=5),
        url_suffix=st.text(
            alphabet=string.ascii_letters + string.digits + "/._-",
            min_size=1,
            max_size=20,
        ),
    )
    def test_extinf_without_url_is_discarded_by_next_extinf(
        self, first_names, url_suffix
    ):
        # N #EXTINF lines back-to-back followed by one URL: only the *last*
        # pending entry can be completed; the rest are discarded.
        lines = [f"#EXTINF:-1,{name}" for name in first_names]
        lines.append(f"http://host/{url_suffix}")

        entries = list(iter_m3u_entries(lines))

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["url"], f"http://host/{url_suffix}")

    @given(
        group=st.text(
            alphabet=string.ascii_letters + string.digits + " -_", max_size=20
        ),
        vlc_opt=st.text(
            alphabet=string.ascii_letters + string.digits + "=-/.", max_size=20
        ),
        name=display_names,
        url_suffix=st.text(
            alphabet=string.ascii_letters + string.digits + "/._-",
            min_size=1,
            max_size=20,
        ),
    )
    def test_extgrp_and_extvlcopt_attach_to_pending_entry(
        self, group, vlc_opt, name, url_suffix
    ):
        assume("=" not in name.split(" ", 1)[0])
        lines = [
            f"#EXTINF:-1,{name}",
            f"#EXTGRP:{group}",
            f"#EXTVLCOPT:{vlc_opt}",
            f"http://host/{url_suffix}",
        ]

        entries = list(iter_m3u_entries(lines))

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        # #EXTGRP sets group-title only because no explicit attribute won.
        self.assertEqual(entry["attributes"]["group-title"], group.strip())
        self.assertEqual(entry["vlc_opts"], [vlc_opt])


# ---------------------------------------------------------------------------
# get_case_insensitive_attr
# ---------------------------------------------------------------------------


class GetCaseInsensitiveAttrProperties(SimpleTestCase):
    @given(
        key=attr_keys,
        value=st.text(max_size=20),
        noise=st.dictionaries(attr_keys, st.text(max_size=10), max_size=5),
    )
    def test_finds_key_regardless_of_case(self, key, value, noise):
        assume(all(k.lower() != key.lower() for k in noise))
        attributes = {**noise, key.upper(): value}

        self.assertEqual(get_case_insensitive_attr(attributes, key.lower()), value)
        self.assertEqual(get_case_insensitive_attr(attributes, key), value)

    @given(
        attributes=st.dictionaries(attr_keys, st.text(max_size=10), max_size=5),
        default=st.text(max_size=10),
    )
    def test_missing_key_returns_default(self, attributes, default):
        assume("tvg-id" not in {k.lower() for k in attributes})
        self.assertEqual(
            get_case_insensitive_attr(attributes, "tvg-ID", default), default
        )


# ---------------------------------------------------------------------------
# _next_available_number / _pick_target_number
# ---------------------------------------------------------------------------

used_number_sets = st.sets(
    st.integers(min_value=-1000, max_value=1000), max_size=30
)


class NextAvailableNumberProperties(SimpleTestCase):
    @given(
        used=used_number_sets,
        start=st.integers(min_value=-100, max_value=100),
    )
    def test_unbounded_result_is_free_and_at_least_start(self, used, start):
        result = _next_available_number(used, start)

        self.assertIsNotNone(result)
        self.assertGreaterEqual(result, start)
        self.assertNotIn(result, used)

    @given(
        used=used_number_sets,
        start=st.integers(min_value=-100, max_value=100),
        end=st.integers(min_value=-100, max_value=200),
    )
    def test_bounded_result_is_free_within_range_or_none(self, used, start, end):
        assume(start <= end)
        result = _next_available_number(used, start, end=end)

        if result is None:
            # Exhaustion is only legitimate when every slot in [start, end]
            # is occupied.
            self.assertEqual(len(used & set(range(start, end + 1))), end - start + 1)
        else:
            self.assertGreaterEqual(result, start)
            self.assertLessEqual(result, end)
            self.assertNotIn(result, used)

    @given(
        used=used_number_sets,
        start=st.integers(min_value=-100, max_value=100),
    )
    def test_result_is_the_smallest_free_number(self, used, start):
        result = _next_available_number(used, start)
        # Everything between start and result must be occupied — otherwise a
        # smaller free number existed and should have been returned.
        self.assertTrue(all(n in used for n in range(start, result)))


class PickTargetNumberProperties(SimpleTestCase):
    def _stream(self, chno):
        return SimpleNamespace(stream_chno=chno)

    @given(
        used=used_number_sets,
        chno=st.integers(min_value=-1000, max_value=1000),
    )
    def test_provider_mode_uses_free_provider_number_verbatim(self, used, chno):
        assume(chno not in used)
        result = _pick_target_number(
            "provider", self._stream(chno), used, 1, 1, end_number=5000
        )
        self.assertEqual(result, chno)

    @given(
        used=used_number_sets,
        fallback=st.integers(min_value=1, max_value=100),
        end=st.integers(min_value=1, max_value=200),
    )
    def test_provider_mode_falls_back_within_range(self, used, fallback, end):
        assume(fallback <= end)
        # Force the fallback path by picking the provider number from the used
        # set itself (skip when the set is empty).
        assume(len(used) > 0)
        chno = sorted(used)[0]
        result = _pick_target_number(
            "provider", self._stream(chno), used, 1, fallback, end_number=end
        )
        if result is not None:
            self.assertNotIn(result, used)
            self.assertGreaterEqual(result, fallback)
            self.assertLessEqual(result, end)

    @given(used=used_number_sets)
    def test_next_available_mode_ignores_end_and_starts_at_one(self, used):
        # Docstring: "next_available: lowest free number from 1; End does not
        # apply (its UI has no range, so a stale End must not cap it)."
        result = _pick_target_number(
            "next_available", self._stream(None), used, 1, 1, end_number=3
        )
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result, 1)
        self.assertNotIn(result, used)

    @given(mode=st.sampled_from(("provider", "next_available", "fixed")))
    def test_result_is_always_free_or_none(self, mode):
        used = {1, 2, 3}
        stream = self._stream(2 if mode == "provider" else None)
        result = _pick_target_number(mode, stream, used, 1, 1, end_number=5)
        if result is not None:
            self.assertNotIn(result, used)


# ---------------------------------------------------------------------------
# convert_js_numbered_backreferences
# ---------------------------------------------------------------------------


class ConvertJsBackreferenceProperties(SimpleTestCase):
    @given(replacement=st.text(max_size=60))
    def test_no_dollar_digits_remain_and_other_chars_survive(self, replacement):
        import re as _re

        converted = convert_js_numbered_backreferences(replacement)

        # Every $<digits> token is gone...
        self.assertIsNone(_re.search(r"\$\d", converted))
        # ...and removing all converted backreference tokens reproduces the
        # input with its $<digits> tokens removed: no other character was
        # fabricated, dropped, or reordered.
        stripped_converted = _re.sub(r"\\\d+", "", converted)
        stripped_input = _re.sub(r"\$\d+", "", replacement)
        self.assertEqual(stripped_converted, stripped_input)

    @given(
        prefix=st.text(
            alphabet=st.characters(blacklist_characters=("$", "\\")), max_size=20
        ),
        group_number=st.integers(min_value=1, max_value=99),
        suffix=st.text(
            alphabet=st.characters(blacklist_characters=("$",)), max_size=20
        ),
    )
    def test_single_reference_translates_exactly(self, prefix, group_number, suffix):
        replacement = f"{prefix}${group_number}{suffix}"
        converted = convert_js_numbered_backreferences(replacement)
        self.assertEqual(converted, f"{prefix}\\{group_number}{suffix}")
