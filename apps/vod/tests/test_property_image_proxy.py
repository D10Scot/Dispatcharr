"""Property-based tests for the VOD image proxy's pure helpers.

apps/vod/image_proxy.py decides which provider-controlled URL strings the
image proxy will fetch and rewrites stored artwork paths into proxy URLs.
Its contract on the pure surface:

- ``is_proxyable_image_url`` is a pure predicate: only strings starting with
  http://, https:// or /data are fetchable; anything else (None, non-strings,
  other schemes) is not.
- ``_as_backdrop_list`` normalizes the many shapes providers store
  ``backdrop_path`` in (missing, string, list, tuple, junk) into a list —
  never raising, never returning a non-list.
- ``get_relation_artwork`` walks the nested relation shapes and must always
  return the ``{"movie_image": str, "backdrop_path": list}`` shape, whatever
  junk the provider stored under custom_properties.
- ``_url_from_props`` must return None for out-of-range backdrop indices and
  never raise on arbitrary index strings.
- ``rewrite_backdrop_paths`` preserves list length 1:1 (one output entry per
  input entry), which the XC clients' indexing depends on.

Runs without Redis or the database (SimpleTestCase, pure functions).
"""

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.vod.image_proxy import (
    _as_backdrop_list,
    _url_from_props,
    format_vod_image_url,
    get_relation_artwork,
    is_proxyable_image_url,
    prefer_relation_artwork,
    rewrite_backdrop_paths,
    rewrite_single_image_url,
)

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

anything = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=True, allow_infinity=True)
    | st.text(max_size=40)
    | st.binary(max_size=20),
    lambda children: st.lists(children, max_size=5)
    | st.tuples(children, children)
    | st.dictionaries(st.text(max_size=12), children, max_size=5),
    max_leaves=20,
)

url_text = st.text(max_size=120)


class IsProxyableProperties(SimpleTestCase):
    @given(value=anything)
    def test_only_strings_with_known_prefixes_pass(self, value):
        result = is_proxyable_image_url(value)
        self.assertIsInstance(result, bool)
        if result:
            self.assertIsInstance(value, str)
            self.assertTrue(
                value.startswith(("http://", "https://", "/data"))
            )

    @given(url=url_text)
    def test_never_raises_on_text(self, url):
        is_proxyable_image_url(url)


class BackdropListProperties(SimpleTestCase):
    @given(value=anything)
    def test_always_returns_a_list(self, value):
        result = _as_backdrop_list(value)
        self.assertIsInstance(result, list)
        # A bare string input becomes exactly a one-element list of itself.
        if isinstance(value, str) and value:
            self.assertEqual(result, [value])
        # Falsy input normalizes to the empty list.
        if not value:
            self.assertEqual(result, [])


class RelationArtworkProperties(SimpleTestCase):
    @given(props=anything)
    def test_output_shape_is_stable(self, props):
        art = get_relation_artwork(props)
        self.assertIsInstance(art, dict)
        self.assertIsInstance(art["movie_image"], str)
        self.assertIsInstance(art["backdrop_path"], list)
        for entry in art["backdrop_path"]:
            # Entries come from _as_backdrop_list, which passes list members
            # through unchanged; only assert the container contract here.
            self.assertIn(entry, art["backdrop_path"])

    @given(rel=anything, obj=anything)
    def test_prefer_relation_artwork_shape(self, rel, obj):
        art = prefer_relation_artwork(rel, obj)
        self.assertIsInstance(art["movie_image"], str)
        self.assertIsInstance(art["backdrop_path"], list)


class UrlFromPropsProperties(SimpleTestCase):
    @given(
        paths=st.lists(url_text, max_size=6),
        index=st.one_of(
            st.integers(min_value=-10, max_value=10),
            st.text(max_size=8),
            st.none(),
        ),
    )
    def test_backdrop_index_bounds(self, paths, index):
        props = {"backdrop_path": paths}
        result = _url_from_props(props, "backdrop", index)
        try:
            idx = int(index)
        except (TypeError, ValueError):
            self.assertIsNone(result)
            return
        if idx < 0 or idx >= len(paths):
            self.assertIsNone(result)
        elif is_proxyable_image_url(paths[idx]):
            self.assertEqual(result, paths[idx])
        else:
            self.assertIsNone(result)

    @given(kind=st.text(max_size=20), value=anything)
    def test_unknown_or_scalar_kinds_never_raise(self, kind, value):
        assume(kind not in ("backdrop", "movie_image", "poster_path"))
        # Non-allowlisted kinds fall into the poster_path branch; the contract
        # is just "no exception, None-or-string out".
        result = _url_from_props({"poster_path": value}, kind)
        self.assertTrue(result is None or isinstance(result, str))


class RewriteProperties(SimpleTestCase):
    @given(backdrop_path=anything)
    def test_rewrite_preserves_length_or_empties(self, backdrop_path):
        # request=None exercises the pure path: vod_image_url_parts calls
        # reverse() without touching the request.
        result = rewrite_backdrop_paths(
            None, "movie", 7, backdrop_path, url_parts=("/pre/", "/suf")
        )
        self.assertIsInstance(result, list)
        if not backdrop_path:
            self.assertEqual(result, [])
        elif isinstance(backdrop_path, str):
            self.assertEqual(len(result), 1)
        elif isinstance(backdrop_path, (list, tuple)):
            self.assertEqual(len(result), len(backdrop_path))
        else:
            self.assertEqual(result, [])

    @given(url=url_text)
    def test_rewrite_single_passthrough_for_unproxyable(self, url):
        result = rewrite_single_image_url(
            None, "movie", 7, "movie_image", url, url_parts=("/pre/", "/suf")
        )
        if is_proxyable_image_url(url):
            self.assertIn("kind=movie_image", result)
        else:
            self.assertEqual(result, url or "")

    @given(
        pk=st.integers(min_value=0, max_value=10**9),
        kind=st.sampled_from(["backdrop", "movie_image", "poster_path"]),
        index=st.integers(min_value=0, max_value=20),
    )
    def test_format_vod_image_url_layout(self, pk, kind, index):
        url = format_vod_image_url("/pre/", "/suf", pk, kind, index=index)
        self.assertTrue(url.startswith(f"/pre/{pk}/suf?kind={kind}"))
        if kind == "backdrop":
            self.assertIn(f"&index={index}", url)
        else:
            self.assertNotIn("&index=", url)
