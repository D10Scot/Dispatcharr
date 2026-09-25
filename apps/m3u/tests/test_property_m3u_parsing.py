"""Property tests for the M3U ingest parsing surfaces (issues #218, #69).

Surfaces, with their line at seed a54b09a9:

- ``parse_extinf_line`` (``apps/m3u/tasks.py:598``)
- ``iter_m3u_entries`` (``apps/m3u/tasks.py:644``)
- ``get_case_insensitive_attr`` (``apps/m3u/tasks.py:590``)
- ``_open_m3u_text_source`` (``apps/m3u/tasks.py:169``), fed arbitrary bytes
  through ``iter_m3u_entries`` -- the #217 seam: it holds only once C-3 decodes
  invalid UTF-8 instead of raising ``UnicodeDecodeError``.
- ``normalize_stream_url`` (``apps/m3u/utils.py:37``)
- ``parse_is_adult`` (``apps/m3u/utils.py:25``)

Provider playlists are untrusted input: every property here is either a
"never raises" totality claim or a round trip of a structure the generator
built, so the oracle is the generator, never the parser.
"""

import gzip
import lzma
import os
import string
import tempfile

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.m3u.tasks import (
    _open_m3u_text_source,
    get_case_insensitive_attr,
    iter_m3u_entries,
    parse_extinf_line,
)
from apps.m3u.utils import normalize_stream_url, parse_is_adult

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Provider-flavoured half-valid text plus full unicode.
garbage_text = st.text(max_size=200) | st.text(
    alphabet='0123456789abcxyz-_ =",\'#EXTINF:tvgloghd.', max_size=200
)
attr_keys = st.text(
    alphabet=string.ascii_letters + string.digits + "-_", min_size=1, max_size=12
)
# Attribute values: no quote of either style and no line break.
attr_values = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",), blacklist_characters="\"'\n\r"
    ),
    max_size=30,
)
# Display names: no line break, and no '=' or quote so the attribute regex
# cannot legitimately extend into them.
display_names = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",), blacklist_characters="\n\r=\"'"
    ),
    max_size=40,
)
url_tails = st.text(
    alphabet=string.ascii_letters + string.digits + "/._-", min_size=1, max_size=20
)


@st.composite
def extinf_lines(draw):
    """An #EXTINF line, the attributes it carries (keys lowercased), and its display name."""
    attrs = {}
    rendered = []
    for _ in range(draw(st.integers(min_value=0, max_value=4))):
        key = draw(attr_keys)
        if key.lower() in attrs:
            continue  # last-write-wins makes a duplicate key unobservable
        value = draw(attr_values)
        quote = draw(st.sampled_from(('"', "'")))
        attrs[key.lower()] = value
        rendered.append(f"{key}={quote}{value}{quote}")
    display = draw(display_names)
    content = f"-1 {' '.join(rendered)},{display}" if rendered else f"-1,{display}"
    return "#EXTINF:" + content, attrs, display


class ParseExtinfLineProperties(SimpleTestCase):
    @given(line=garbage_text)
    def test_parse_extinf_line_is_total_and_none_exactly_without_the_prefix(self, line):
        parsed = parse_extinf_line(line)
        if not line.startswith("#EXTINF:"):
            self.assertIsNone(parsed)
            return
        self.assertEqual(set(parsed), {"attributes", "display_name", "name"})
        for key in parsed["attributes"]:
            self.assertEqual(key, key.lower())
        self.assertIsInstance(parsed["name"], str)
        self.assertIsInstance(parsed["display_name"], str)

    @given(drawn=extinf_lines())
    def test_generated_attributes_and_display_name_round_trip(self, drawn):
        line, attrs, display = drawn
        parsed = parse_extinf_line(line)
        self.assertEqual(parsed["attributes"], attrs)
        self.assertEqual(parsed["display_name"], display.strip())
        if display.strip():
            # The comma text is the canonical title (base #EXTINF spec).
            self.assertEqual(parsed["name"], display.strip())

    @given(content=st.text(max_size=80).filter(lambda s: s.strip() and "\n" not in s))
    def test_name_is_never_empty_for_non_blank_content(self, content):
        # The four-way fallback ends in ``content.strip()``.
        self.assertTrue(parse_extinf_line("#EXTINF:" + content)["name"])


class IterM3uEntriesProperties(SimpleTestCase):
    @given(lines=st.lists(garbage_text, max_size=60))
    def test_iter_m3u_entries_is_total_and_every_entry_has_a_url(self, lines):
        for entry in iter_m3u_entries(lines):
            self.assertIsInstance(entry["url"], str)
            self.assertIsInstance(entry["attributes"], dict)
            self.assertIsInstance(entry["name"], str)

    @given(
        names=st.lists(display_names, min_size=1, max_size=8),
        scheme=st.sampled_from(("http", "https", "rtsp", "rtp")),
        tails=st.lists(url_tails, min_size=8, max_size=8),
    )
    def test_each_extinf_url_pair_yields_exactly_one_entry_in_order(self, names, scheme, tails):
        lines = []
        for name, tail in zip(names, tails):
            lines += [f"#EXTINF:-1,{name}", f"{scheme}://host/{tail}"]
        entries = list(iter_m3u_entries(lines))
        self.assertEqual(
            [e["url"] for e in entries],
            [f"{scheme}://host/{t}" for t in tails[: len(names)]],
        )

    @given(names=st.lists(display_names, min_size=2, max_size=5), tail=url_tails)
    def test_an_extinf_without_a_url_is_discarded_by_the_next_extinf(self, names, tail):
        lines = [f"#EXTINF:-1,{n}" for n in names] + [f"http://host/{tail}"]
        with self.assertLogs("apps.m3u.tasks", level="WARNING"):
            entries = list(iter_m3u_entries(lines))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["display_name"], names[-1].strip())

    @given(
        group=st.text(alphabet=string.ascii_letters + " -_", max_size=20),
        vlc_opt=st.text(alphabet=string.ascii_letters + "=-/.", max_size=20),
        explicit=st.booleans(),
        tail=url_tails,
    )
    def test_extgrp_fills_group_title_only_when_absent_and_extvlcopt_attaches(
        self, group, vlc_opt, explicit, tail
    ):
        extinf = '#EXTINF:-1 group-title="Explicit",N' if explicit else "#EXTINF:-1,N"
        lines = [extinf, f"#EXTGRP:{group}", f"#EXTVLCOPT:{vlc_opt}", f"http://host/{tail}"]
        (entry,) = list(iter_m3u_entries(lines))
        expected_group = "Explicit" if explicit else group.strip()
        self.assertEqual(entry["attributes"]["group-title"], expected_group)
        self.assertEqual(entry["vlc_opts"], [vlc_opt.strip()])


# Names built from characters a Latin-1 or Windows-1252 provider sends: every
# one of them is a byte >= 0xA0 once encoded, i.e. invalid as a lone UTF-8
# byte, so a strict UTF-8 decode of the playlist raises.
latin1_names = st.text(
    alphabet=string.ascii_letters + " " + "".join(chr(c) for c in range(0xA0, 0x100)),
    min_size=1,
    max_size=20,
)


def _write(tmpdir, suffix, data):
    path = os.path.join(tmpdir, "playlist.m3u" + suffix)
    opener = {"": open, ".gz": gzip.open, ".xz": lzma.open}[suffix]
    with opener(path, "wb") as fh:
        fh.write(data)
    return path


class OpenM3uTextSourceProperties(SimpleTestCase):
    """#217 seam: holds after C-3 decodes invalid byte runs instead of raising."""

    @given(
        data=st.binary(max_size=400),
        suffix=st.sampled_from(("", ".gz", ".xz")),
    )
    # #217: a Latin-1 playlist raised UnicodeDecodeError ... byte 0xe9.
    @example(data="#EXTINF:-1,TF1 Séries HD\nhttp://h/1\n".encode("latin-1"), suffix="")
    def test_arbitrary_playlist_bytes_never_raise_on_any_compression(self, data, suffix):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, suffix, data)
            with _open_m3u_text_source(path) as fh:
                for entry in iter_m3u_entries(fh):
                    self.assertIsInstance(entry["url"], str)

    @given(
        names=st.lists(latin1_names, min_size=1, max_size=6),
        suffix=st.sampled_from(("", ".gz", ".xz")),
    )
    def test_a_latin1_playlist_yields_one_entry_per_url(self, names, suffix):
        body = "".join(f"#EXTINF:-1,{n}\nhttp://host/{i}\n" for i, n in enumerate(names))
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, suffix, body.encode("latin-1"))
            with _open_m3u_text_source(path) as fh:
                urls = [e["url"] for e in iter_m3u_entries(fh)]
        self.assertEqual(urls, [f"http://host/{i}" for i in range(len(names))])


class GetCaseInsensitiveAttrProperties(SimpleTestCase):
    @given(
        key=attr_keys,
        value=st.text(max_size=20),
        noise=st.dictionaries(attr_keys, st.text(max_size=10), max_size=5),
        spelling=st.sampled_from((str.upper, str.lower, str.swapcase)),
    )
    def test_a_present_key_is_found_whatever_its_case(self, key, value, noise, spelling):
        noise = {k: v for k, v in noise.items() if k.lower() != key.lower()}
        attributes = {**noise, spelling(key): value}
        self.assertEqual(get_case_insensitive_attr(attributes, key), value)

    @given(
        attributes=st.dictionaries(attr_keys, st.text(max_size=10), max_size=5),
        default=st.text(min_size=1, max_size=10),
    )
    def test_an_absent_key_returns_the_supplied_default(self, attributes, default):
        attributes = {k: v for k, v in attributes.items() if k.lower() != "tvg-id"}
        self.assertEqual(get_case_insensitive_attr(attributes, "tvg-ID", default), default)


class NormalizeStreamUrlProperties(SimpleTestCase):
    @given(url=st.none() | garbage_text | garbage_text.map(lambda s: "udp://@" + s))
    def test_only_a_leading_vlc_udp_at_is_removed_and_only_once(self, url):
        result = normalize_stream_url(url)
        if url and url.startswith("udp://@"):
            self.assertEqual(result, "udp://" + url[len("udp://@"):])
        else:
            self.assertEqual(result, url)


class ParseIsAdultProperties(SimpleTestCase):
    json_values = st.recursive(
        st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=10),
        lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=3), inner, max_size=3),
        max_leaves=6,
    )

    @given(value=json_values)
    def test_parse_is_adult_is_total_over_provider_json(self, value):
        self.assertIsInstance(parse_is_adult(value), bool)

    @given(
        n=st.integers(min_value=-5, max_value=5),
        render=st.sampled_from((lambda n: n, str, lambda n: f" {n} ")),
    )
    def test_true_exactly_for_one_as_int_or_string(self, n, render):
        self.assertEqual(parse_is_adult(render(n)), n == 1)
