"""Property-based tests for the VOD image proxy's pure helpers.

Surfaces (``file:line`` at a54b09a9):

- ``is_proxyable_image_url`` (``apps/vod/image_proxy.py:22``): the allowlist that decides
  which stored, provider-controlled URL strings the image proxy will fetch. Security
  relevant, so the exact allowlist is pinned: a ``str`` starting with ``http://``,
  ``https://`` or ``/data``, case-sensitive, nothing else.
- ``_as_backdrop_list`` (``:29``): normalises every stored ``backdrop_path`` shape to a list.
- ``get_relation_artwork`` (``:39``): walks ``info`` > ``info.info`` > ``detailed_info`` >
  ``basic_data`` > the top level, in that order, and always returns
  ``{"movie_image": str, "backdrop_path": list}``.
- ``prefer_relation_artwork`` (``:88``): relation artwork wins, the object's is the fallback.
- ``_url_from_props`` (``:136``): backdrop index bounds, and nothing unproxyable escapes.
- ``format_vod_image_url`` (``:199``) and ``rewrite_backdrop_paths`` (``:220``): the proxy
  URL layout, and a 1:1 rewrite that XC clients index into.

Issues: #92 (vod half), #210, #162.
"""

import hashlib
import string
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.vod.image_proxy import (
    _as_backdrop_list,
    _url_from_props,
    format_vod_image_url,
    get_relation_artwork,
    is_proxyable_image_url,
    prefer_relation_artwork,
    rewrite_backdrop_paths,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# The allowlist, written out independently of the helper under test.
_ALLOWED_PREFIXES = ("http://", "https://", "/data")

# Anything a JSONField (or a buggy caller) can hand these helpers.
anything = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(10**12), max_value=10**12)
    | st.floats(allow_nan=True, allow_infinity=True)
    | st.text(max_size=40)
    | st.binary(max_size=20),
    lambda children: st.lists(children, max_size=5)
    | st.tuples(children, children)
    | st.dictionaries(st.text(max_size=12), children, max_size=5),
    max_leaves=20,
)

# URL-ish text that lands on both sides of the allowlist often, not only by accident.
url_like = st.one_of(
    st.tuples(
        st.sampled_from(
            _ALLOWED_PREFIXES
            + ("HTTP://", "Https://", " http://", "ftp://", "file://", "//", "data:", "/dat", "javascript:", "")
        ),
        st.text(max_size=30),
    ).map("".join),
    st.text(max_size=60),
)

# A non-blank artwork URL and the three blank-ish values providers send instead.
artwork_url = st.text(string.ascii_letters + string.digits + "/:.-_", min_size=1, max_size=20).map(
    lambda s: "https://img/" + s
)
blankish = st.sampled_from([None, "", "   "])
_IMAGE_KEYS = ("movie_image", "cover_big", "stream_icon", "cover")


class IsProxyableImageUrlProperties(SimpleTestCase):
    @given(value=st.one_of(anything, url_like))
    @example(value="HTTP://host/a.jpg")  # scheme match is case-sensitive: rejected
    @example(value=" http://host/a.jpg")  # leading whitespace: rejected
    @example(value="file:///etc/passwd")
    @example(value="//evil/a.jpg")  # scheme-relative: rejected
    @example(value="data:image/png;base64,AAAA")
    @example(value="javascript:alert(1)")
    @example(value="/dat")
    @example(value=b"http://host/a.jpg")  # bytes are not str: rejected
    def test_is_proxyable_image_url_is_exactly_the_three_prefix_allowlist(self, value):
        expected = isinstance(value, str) and value.startswith(_ALLOWED_PREFIXES)
        self.assertIs(is_proxyable_image_url(value), expected)


class AsBackdropListProperties(SimpleTestCase):
    @given(value=anything)
    def test_as_backdrop_list_always_returns_a_list_of_the_input_shape(self, value):
        result = _as_backdrop_list(value)
        self.assertIsInstance(result, list)
        if not value:
            self.assertEqual(result, [])
        elif isinstance(value, str):
            self.assertEqual(result, [value])
        elif isinstance(value, (list, tuple)):
            self.assertEqual(result, list(value))
        else:
            self.assertEqual(result, [])


def _layers_to_props(info, nested, detailed, basic, top):
    props = dict(top)
    if info is not None:
        info = dict(info)
        if nested is not None:
            info["info"] = nested
        props["info"] = info
    if detailed is not None:
        props["detailed_info"] = detailed
    if basic is not None:
        props["basic_data"] = basic
    return props


# One layer: absent (None), or a dict carrying at most one image key and at most one backdrop.
layer = st.one_of(
    st.none(),
    st.fixed_dictionaries(
        {},
        optional={
            "img": st.tuples(st.sampled_from(_IMAGE_KEYS), st.one_of(artwork_url, blankish)),
            "backdrop_path": st.one_of(artwork_url, st.lists(artwork_url, max_size=3), blankish),
        },
    ).map(lambda d: ({d["img"][0]: d["img"][1]} if "img" in d else {}) | (
        {"backdrop_path": d["backdrop_path"]} if "backdrop_path" in d else {}
    )),
)


class RelationArtworkProperties(SimpleTestCase):
    @given(props=anything)
    def test_get_relation_artwork_shape_is_stable_for_any_stored_value(self, props):
        art = get_relation_artwork(props)
        self.assertEqual(set(art), {"movie_image", "backdrop_path"})
        self.assertIsInstance(art["movie_image"], str)
        self.assertEqual(art["movie_image"], art["movie_image"].strip())
        self.assertIsInstance(art["backdrop_path"], list)

    @given(info=layer, nested=layer, detailed=layer, basic=layer, top=layer.map(lambda d: d or {}))
    def test_get_relation_artwork_takes_the_first_layer_that_has_a_value(
        self, info, nested, detailed, basic, top
    ):
        props = _layers_to_props(info, nested, detailed, basic, top)
        # Precedence order, written out from the docstring rather than read from the code.
        ordered = [
            l
            for l in (info, nested if info is not None else None, detailed, basic, top)
            if l is not None
        ]
        expected_image = ""
        for l in ordered:
            values = [l[k] for k in _IMAGE_KEYS if k in l]
            if values and isinstance(values[0], str) and values[0].strip():
                expected_image = values[0].strip()
                break
        expected_backdrop = []
        for l in ordered:
            bp = l.get("backdrop_path")
            if isinstance(bp, str) and bp:
                expected_backdrop = [bp]
                break
            if isinstance(bp, list) and bp:
                expected_backdrop = bp
                break
        art = get_relation_artwork(props)
        self.assertEqual(art["movie_image"], expected_image)
        self.assertEqual(art["backdrop_path"], expected_backdrop)

    @given(rel=anything, obj=anything)
    def test_prefer_relation_artwork_shape_is_stable(self, rel, obj):
        art = prefer_relation_artwork(rel, obj)
        self.assertEqual(set(art), {"movie_image", "backdrop_path"})
        self.assertIsInstance(art["movie_image"], str)
        self.assertIsInstance(art["backdrop_path"], list)

    @given(
        rel_image=st.one_of(artwork_url, blankish),
        obj_image=st.one_of(artwork_url, blankish, st.integers(), st.lists(artwork_url, max_size=2)),
        rel_bp=st.one_of(st.lists(artwork_url, max_size=2), blankish),
        obj_bp=st.one_of(st.lists(artwork_url, max_size=2), artwork_url, blankish),
    )
    def test_prefer_relation_artwork_relation_wins_and_object_fills_gaps(
        self, rel_image, obj_image, rel_bp, obj_bp
    ):
        art = prefer_relation_artwork(
            {"movie_image": rel_image, "backdrop_path": rel_bp},
            {"movie_image": obj_image, "backdrop_path": obj_bp},
        )
        if isinstance(rel_image, str) and rel_image.strip():
            self.assertEqual(art["movie_image"], rel_image.strip())
        elif isinstance(obj_image, str):
            self.assertEqual(art["movie_image"], obj_image.strip())
        else:
            self.assertEqual(art["movie_image"], "")
        # A non-empty string is one backdrop; a non-empty list is the backdrops.
        def as_list(v):
            return [v] if isinstance(v, str) and v else list(v) if isinstance(v, list) else []

        self.assertEqual(art["backdrop_path"], as_list(rel_bp) or as_list(obj_bp))


class UrlFromPropsProperties(SimpleTestCase):
    # ``index`` reaches _url_from_props only as the ``?index=`` query string
    # (apps/vod/image_proxy.py:318), so strings (and the int default) are the whole domain.
    @given(
        paths=st.lists(url_like, max_size=6),
        index=st.one_of(st.integers(min_value=-10, max_value=10), st.text(max_size=8)),
    )
    @example(paths=["http://a/0.jpg", "http://a/1.jpg"], index="-1")  # negative index: no wraparound
    @example(paths=["http://a/0.jpg"], index="1")  # one past the end
    @example(paths=["file:///etc/passwd"], index="0")  # in range but unproxyable
    def test_url_from_props_backdrop_index_is_bounds_checked(self, paths, index):
        result = _url_from_props({"backdrop_path": paths}, "backdrop", index)
        try:
            idx = int(index)
        except ValueError:
            self.assertIsNone(result)
            return
        if 0 <= idx < len(paths) and isinstance(paths[idx], str) and paths[idx].startswith(_ALLOWED_PREFIXES):
            self.assertEqual(result, paths[idx])
        else:
            self.assertIsNone(result)

    @given(kind=st.sampled_from(["movie_image", "poster_path"]), value=st.one_of(anything, url_like))
    def test_url_from_props_never_returns_an_unproxyable_url(self, kind, value):
        result = _url_from_props({kind: value}, kind)
        if result is not None:
            self.assertIs(result, value)
            self.assertTrue(result.startswith(_ALLOWED_PREFIXES))
        else:
            self.assertFalse(isinstance(value, str) and value.startswith(_ALLOWED_PREFIXES))


class ProxyUrlLayoutProperties(SimpleTestCase):
    @given(
        pk=st.integers(min_value=0, max_value=10**9),
        kind=st.sampled_from(["backdrop", "movie_image", "poster_path"]),
        index=st.integers(min_value=0, max_value=50),
        source_url=st.one_of(st.none(), st.just(""), url_like),
        account=st.one_of(st.none(), st.integers(min_value=0, max_value=10**6)),
    )
    def test_format_vod_image_url_layout(self, pk, kind, index, source_url, account):
        url = format_vod_image_url(
            "/api/vod/movies/", "/image/", pk, kind, index=index, source_url=source_url, m3u_account_id=account
        )
        parts = urlsplit(url)
        self.assertEqual(parts.path, f"/api/vod/movies/{pk}/image/")
        query = parse_qs(parts.query, keep_blank_values=True)
        self.assertEqual(query.pop("kind"), [kind])
        if kind == "backdrop":
            self.assertEqual(query.pop("index"), [str(index)])
        if account is not None:
            self.assertEqual(query.pop("m3u_account_id"), [str(account)])
        if source_url:
            self.assertEqual(query.pop("v"), [hashlib.md5(source_url.encode()).hexdigest()[:8]])
        self.assertEqual(query, {})

    @given(
        backdrop_path=st.one_of(anything, url_like, st.lists(st.one_of(url_like, anything), max_size=5)),
        account=st.one_of(st.none(), st.integers(min_value=0, max_value=99)),
    )
    @example(backdrop_path=["http://a/0.jpg", "rel/1.jpg", "https://a/2.jpg"], account=None)
    def test_rewrite_backdrop_paths_is_one_to_one_and_rewrites_only_proxyable_entries(
        self, backdrop_path, account
    ):
        parts = ("/pre/", "/suf")
        result = rewrite_backdrop_paths(None, "movie", 7, backdrop_path, url_parts=parts, m3u_account_id=account)
        if not backdrop_path or not isinstance(backdrop_path, (str, list, tuple)):
            self.assertEqual(result, [])
            return
        entries = [backdrop_path] if isinstance(backdrop_path, str) else list(backdrop_path)
        self.assertEqual(len(result), len(entries))
        for i, (before, after) in enumerate(zip(entries, result)):
            if isinstance(before, str) and before.startswith(_ALLOWED_PREFIXES):
                self.assertEqual(
                    after,
                    format_vod_image_url(*parts, 7, "backdrop", index=i, source_url=before, m3u_account_id=account),
                )
                self.assertIn(f"&index={i}", after)
            else:
                self.assertIs(after, before)
