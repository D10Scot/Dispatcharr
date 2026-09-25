"""Property tests for provider-controlled Xtream account values (issue #200; seam #199).

Surfaces, with their line at seed a54b09a9:

- ``M3UAccountProfile._parse_exp_date`` (``apps/m3u/models.py:307``): a
  provider's ``user_info.exp_date`` (a unix timestamp or ISO string) becomes
  an aware datetime, or ``None`` for anything unparseable.
- ``M3UAccountProfile._parse_exp_date_from_custom_properties``
  (``apps/m3u/models.py:323``): reads ``custom_properties["user_info"]``.
- ``core.xtream_codes.normalize_server_url`` (``core/xtream_codes.py:9``):
  strips a pasted XC API endpoint (``.../player_api.php?...``) back to the
  server base URL.

The #199 seam: at seed ``datetime.fromtimestamp`` raises ``OverflowError`` for
a timestamp past the platform range, and the ``except`` does not catch it. A
non-dict ``user_info`` raises ``AttributeError``. ``save()`` re-parses on
every save, so one bad provider value wedges the row. C-3 catches
``OverflowError`` and reads ``user_info`` through a dict-or-``{}`` accessor.
After C-3 the parser is total over every JSON scalar, so this module draws
the full range with no overflow filter. #200's reference branch filtered the
overflow range out; that filter is gone here on purpose.
"""

import math
import string
from datetime import datetime, timezone
from urllib.parse import urlparse

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.m3u.models import M3UAccountProfile
from core.xtream_codes import normalize_server_url

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

parse = M3UAccountProfile._parse_exp_date

# datetime's representable range: 0001-01-01 .. 9999-12-31T23:59:59 UTC.
MIN_EPOCH = -62135596800
MAX_EPOCH = 253402300799

json_scalars = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats()
    | st.text(max_size=30)
    | st.integers().map(str)
    | st.floats().map(repr)
)
json_values = st.recursive(
    json_scalars,
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner, max_size=3),
    max_leaves=6,
)


class ParseExpDateProperties(SimpleTestCase):
    @given(value=json_values)
    # #199: past the platform time_t range these raised OverflowError.
    @example(value="999999999999999999999999")
    @example(value="1e30")
    @example(value=float("inf"))
    @example(value="-1e20")
    def test_exp_date_parsing_is_total_over_provider_json(self, value):
        result = parse(value)
        if result is not None:
            self.assertIsInstance(result, datetime)

    @given(
        value=st.integers(min_value=MIN_EPOCH, max_value=MAX_EPOCH)
        | st.floats(min_value=MIN_EPOCH, max_value=MAX_EPOCH, allow_nan=False)
    )
    def test_an_in_range_timestamp_is_that_instant_in_utc(self, value):
        expected = datetime(1970, 1, 1, tzinfo=timezone.utc).timestamp() + float(value)
        result = parse(value)
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertAlmostEqual(result.timestamp(), expected, delta=1e-3)

    @given(value=st.integers(min_value=MIN_EPOCH, max_value=MAX_EPOCH))
    def test_a_digit_string_parses_like_its_number(self, value):
        self.assertEqual(parse(str(value)), parse(value))

    @given(user_info=json_values)
    # #199: a non-dict user_info raised AttributeError.
    @example(user_info=None)
    @example(user_info=[1])
    @example(user_info="x")
    @example(user_info={"exp_date": "999999999999999999999999"})
    def test_exp_date_from_custom_properties_is_total_over_any_user_info(self, user_info):
        profile = M3UAccountProfile(custom_properties={"user_info": user_info})
        result = profile._parse_exp_date_from_custom_properties()
        if result is not None:
            self.assertIsInstance(result, datetime)


hosts = st.from_regex(r"[a-z0-9][a-z0-9.-]{0,15}", fullmatch=True)
segments = st.text(alphabet=string.ascii_letters + string.digits + "_.~-", min_size=1, max_size=10).filter(
    lambda s: not s.endswith(".php") and s not in (".", "..")
)


class NormalizeServerUrlProperties(SimpleTestCase):
    @given(value=st.none() | st.text(max_size=120))
    def test_normalize_server_url_is_total_and_passes_falsy_through(self, value):
        result = normalize_server_url(value)
        if not value:
            self.assertIs(result, value)
        else:
            self.assertIsInstance(result, str)

    @given(
        scheme=st.sampled_from(("http", "https")),
        host=hosts,
        port=st.none() | st.integers(min_value=1, max_value=65535),
        base=st.lists(segments, max_size=3),
        endpoint=st.none() | st.sampled_from(("player_api.php", "get.php", "xmltv.php", "panel_api.php")),
        query=st.sampled_from(("", "?username=u&password=p", "?action=get_live_streams")),
        trailing_slash=st.booleans(),
    )
    def test_a_pasted_api_url_normalises_to_scheme_host_and_base_path(
        self, scheme, host, port, base, endpoint, query, trailing_slash
    ):
        netloc = f"{host}:{port}" if port else host
        base_path = "".join("/" + s for s in base)
        path = base_path + (f"/{endpoint}" if endpoint else "") + ("/" if trailing_slash and not endpoint else "")
        self.assertEqual(
            normalize_server_url(f"{scheme}://{netloc}{path}{query}"),
            f"{scheme}://{netloc}{base_path}",
        )

    @given(value=st.text(max_size=80).filter(lambda s: ";" not in s))
    def test_normalising_twice_changes_nothing(self, value):
        # ';' is excluded: urlparse splits ';params' off the LAST path segment
        # and the rebuild drops them, so 'http://h/a;b' loses ';b' and ';/'
        # takes two passes to settle (plan I, finding F-9).
        once = normalize_server_url(value)
        self.assertEqual(normalize_server_url(once), once)
