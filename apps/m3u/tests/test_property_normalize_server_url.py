"""Property-based tests for ``core.xtream_codes.normalize_server_url``.

The normaliser runs on every XC account's ``server_url`` before credentials
are attached (apps/m3u/tasks.py ``get_transformed_credentials``), so its
input is operator-pasted, frequently-malformed provider text. The
implementation promises, by construction:

- totality: ``url.strip()``, ``urlparse`` and a pure string rebuild never
  raise on ``str`` input, and ``None``/empty short-circuit to the input;
- only the path is rewritten: scheme and netloc survive verbatim, query and
  fragment are dropped, and the path is right-stripped of ``/`` and of one
  trailing ``*.php`` segment (the XC API endpoints are always ``.php``
  files, per the comment in the function);
- idempotence: re-normalising a normalised URL changes nothing, because a
  stripped path ends in neither ``/`` nor ``.php``.

These properties are deliberately weaker than "the output is a valid URL" —
the function documents no such guarantee and passes unparseable input
through unchanged (e.g. ``"not a url"``).

``SimpleTestCase``-based: the function is pure (no DB, no Redis, no I/O).
"""

from urllib.parse import urlparse

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from core.xtream_codes import normalize_server_url

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

url_text = st.text(max_size=200)
host = st.from_regex(r"[a-z0-9.-]{1,20}", fullmatch=True)
path_segment = st.from_regex(r"[A-Za-z0-9_.~-]{1,12}", fullmatch=True)


def _parsed(value):
    return urlparse(value.strip())


class NormalizeServerUrlTotalityProperties(SimpleTestCase):
    @given(value=st.one_of(st.none(), url_text))
    def test_never_raises_and_preserves_falsy(self, value):
        # The input contract is str | None (M3UAccount.server_url is a
        # URLField); non-str truthy input is outside it.
        result = normalize_server_url(value)
        if not value:
            # falsy input short-circuits to itself
            self.assertIs(result, value)
        else:
            self.assertIsInstance(result, str)


class NormalizeServerUrlStructureProperties(SimpleTestCase):
    @given(
        scheme=st.sampled_from(["http", "https"]),
        host=host,
        port=st.one_of(st.none(), st.integers(min_value=1, max_value=65535)),
        segments=st.lists(path_segment, max_size=4),
        php_suffix=st.booleans(),
    )
    def test_scheme_netloc_survive_and_path_is_stripped(
        self, scheme, host, port, segments, php_suffix
    ):
        path = "/" + "/".join(segments) if segments else ""
        if php_suffix:
            path = f"{path}/player_api.php"
        netloc = f"{host}:{port}" if port else host
        url = f"{scheme}://{netloc}{path}"

        result = normalize_server_url(url)
        parsed = _parsed(result)

        self.assertEqual(parsed.scheme, scheme)
        self.assertEqual(parsed.netloc, netloc)
        # query/fragment are always dropped by the rebuild
        self.assertEqual(parsed.query, "")
        self.assertEqual(parsed.fragment, "")
        # the path never ends in '/' or '.php' after normalising
        self.assertFalse(parsed.path.endswith("/"))
        self.assertFalse(parsed.path.split("/")[-1].endswith(".php"))
        if php_suffix:
            # the .php endpoint segment was stripped, the rest preserved
            expected = "/" + "/".join(segments) if segments else ""
            self.assertEqual(parsed.path, expected)
        else:
            self.assertEqual(parsed.path, path)

    @given(
        value=url_text.map(lambda s: s.strip()).filter(
            lambda s: "\xa0" not in s and not any(c.isspace() for c in s)
        )
    )
    def test_idempotent(self, value):
        # Idempotence holds for whitespace-free input (the function strips
        # once internally; urlparse also strips some unicode spaces like
        # \xa0, but only on the first pass — a second pass on the result is
        # then stable).
        once = normalize_server_url(value)
        self.assertEqual(once, normalize_server_url(once))
