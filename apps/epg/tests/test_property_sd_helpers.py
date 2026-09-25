"""Property-based tests for the Schedules Direct helpers.

Surfaces (seed a54b09a9):

* ``sd_poster_cache_bust`` / ``sd_poster_proxy_path`` (apps/epg/utils.py:32, :44).
* ``sd_auth_lockout_seconds_for_code`` (apps/epg/sd_utils.py:81) - the /token
  cooldown table.
* ``sd_credential_fingerprint`` (:109) - clears a persisted lockout or cached
  token exactly when the credentials change.
* ``sd_auth_failure_message`` (:209) and ``sd_token_response_code`` (:266).
* ``sd_parse_response_payload`` (:691) - every SD HTTP body goes through it.
* ``_sd_pick_poster_url`` (apps/epg/sd_tasks.py:220) - picks a poster from
  SD's image list (called at :672 on provider JSON).

Closes the SD part of #202 (and duplicates #274, #158, #74).
"""

import json
import string

import requests
from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.epg.sd_tasks import SD_POSTER_STYLE_CONFIG, _sd_pick_poster_url
from apps.epg.sd_utils import (
    SD_AUTH_LOCKOUT_CODES,
    SD_AUTH_LOCKOUT_SECONDS,
    SD_AUTH_LOCKOUT_SECONDS_ACCOUNT_LOCK,
    SD_AUTH_LOCKOUT_SECONDS_SOFT,
    SD_AUTH_SOFT_CODES,
    SD_CODE_ACCOUNT_LOCKED,
    sd_auth_failure_message,
    sd_auth_lockout_seconds_for_code,
    sd_credential_fingerprint,
    sd_parse_response_payload,
    sd_token_response_code,
)
from apps.epg.utils import sd_poster_cache_bust, sd_poster_proxy_path

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# JSON values as json.loads produces them. Infinite floats are excluded:
# _sd_image_width's int() raises OverflowError on a JSON Infinity width
# (sd_tasks.py:140-143 catches only TypeError/ValueError) - plan I notes it as
# a minor finding; Schedules Direct is not a hostile source.
json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-10**6, 10**6)
    | st.floats(allow_infinity=False) | st.text(max_size=12),
    lambda inner: st.lists(inner, max_size=4)
    | st.dictionaries(st.text(max_size=8), inner, max_size=4),
    max_leaves=12,
)
_KNOWN_CODES = sorted(SD_AUTH_LOCKOUT_CODES)
codes = st.one_of(
    st.sampled_from(_KNOWN_CODES), st.integers(-10, 10000), st.none(),
    st.text(max_size=8), st.booleans(),
)


class SdPosterPathProperties(SimpleTestCase):
    @given(url=st.one_of(st.none(), st.text(max_size=120)), pid=st.integers(1, 10**12))
    def test_the_bust_is_twelve_hex_iff_there_is_a_url_and_the_path_carries_it(
        self, url, pid
    ):
        bust = sd_poster_cache_bust(url)
        path = sd_poster_proxy_path(pid, url)
        base = f"/api/epg/programs/{pid}/poster/"
        if not url:
            self.assertEqual(bust, "")
            self.assertEqual(path, base)
        else:
            self.assertRegex(bust, r"\A[0-9a-f]{12}\Z")
            self.assertEqual(bust, sd_poster_cache_bust(url))
            self.assertEqual(path, f"{base}?v={bust}")

    @given(a=st.text(min_size=1, max_size=60), b=st.text(min_size=1, max_size=60))
    def test_a_new_artwork_uri_gets_a_new_bust(self, a, b):
        if a != b:
            self.assertNotEqual(sd_poster_cache_bust(a), sd_poster_cache_bust(b))


class SdLockoutProperties(SimpleTestCase):
    @given(code=codes)
    def test_every_code_maps_to_its_documented_cooldown(self, code):
        seconds = sd_auth_lockout_seconds_for_code(code)
        if code == SD_CODE_ACCOUNT_LOCKED:
            expected = SD_AUTH_LOCKOUT_SECONDS_ACCOUNT_LOCK
        elif code in SD_AUTH_SOFT_CODES:
            expected = SD_AUTH_LOCKOUT_SECONDS_SOFT
        else:
            expected = SD_AUTH_LOCKOUT_SECONDS
        self.assertEqual(seconds, expected)

    def test_the_cooldowns_are_ordered_locked_then_soft_then_default(self):
        self.assertLess(SD_AUTH_LOCKOUT_SECONDS_ACCOUNT_LOCK, SD_AUTH_LOCKOUT_SECONDS_SOFT)
        self.assertLess(SD_AUTH_LOCKOUT_SECONDS_SOFT, SD_AUTH_LOCKOUT_SECONDS)


_cred = st.one_of(st.none(), st.text(alphabet=string.printable, max_size=30))
_ws = st.text(alphabet=" \t\n", max_size=3)


class SdCredentialFingerprintProperties(SimpleTestCase):
    @given(user=_cred, password=_cred, lead=_ws, trail=_ws)
    def test_the_fingerprint_ignores_none_versus_empty_and_outer_whitespace(
        self, user, password, lead, trail
    ):
        fp = sd_credential_fingerprint(user, password)
        self.assertRegex(fp, r"\A[0-9a-f]{64}\Z")
        self.assertEqual(
            fp,
            sd_credential_fingerprint(
                lead + (user or "") + trail, lead + (password or "") + trail
            ),
        )

    @given(
        user=st.text(alphabet=string.ascii_letters + string.digits, max_size=20),
        password=st.text(alphabet=string.ascii_letters + string.digits, max_size=20),
        edit=st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=4),
    )
    def test_any_edit_to_either_credential_changes_the_fingerprint(
        self, user, password, edit
    ):
        fp = sd_credential_fingerprint(user, password)
        self.assertNotEqual(fp, sd_credential_fingerprint(user + edit, password))
        self.assertNotEqual(fp, sd_credential_fingerprint(user, password + edit))
        self.assertNotEqual(fp, sd_credential_fingerprint(edit + user, password))


class SdTokenCodeAndMessageProperties(SimpleTestCase):
    @given(body=json_values)
    def test_the_token_code_is_the_int_code_or_zero_for_any_json_body(self, body):
        code = sd_token_response_code(body)
        self.assertIsInstance(code, int)
        if isinstance(body, dict) and isinstance(body.get("code"), int):
            self.assertEqual(code, body["code"])
        else:
            self.assertEqual(code, 0)

    @given(code=codes, sd_message=st.one_of(st.none(), st.text(max_size=40)))
    def test_the_failure_message_is_fixed_for_known_codes_and_echoes_unknown_ones(
        self, code, sd_message
    ):
        msg = sd_auth_failure_message(code, sd_message)
        self.assertIsInstance(msg, str)
        self.assertTrue(msg)
        if code in SD_AUTH_LOCKOUT_CODES:
            self.assertEqual(msg, sd_auth_failure_message(code, None))
        else:
            self.assertIn(f"(code {code})", msg)
            if sd_message:
                self.assertTrue(msg.endswith(sd_message))


def _response(body, content_type):
    r = requests.Response()
    r.status_code = 200
    r._content = body
    if content_type is not None:
        r.headers["Content-Type"] = content_type
    r.encoding = None
    return r


class SdParseResponsePayloadProperties(SimpleTestCase):
    @given(
        body=st.one_of(
            st.binary(max_size=80),
            json_values.map(lambda v: json.dumps(v).encode()),
        ),
        content_type=st.sampled_from(
            [None, "", "application/json", "text/html", "APPLICATION/JSON; charset=utf-8"]
        ),
    )
    def test_any_body_yields_a_dict_and_its_int_code_or_nothing(self, body, content_type):
        code, data = sd_parse_response_payload(_response(body, content_type))
        if data is None:
            self.assertIsNone(code)
            return
        self.assertIsInstance(data, dict)
        self.assertEqual(data, json.loads(body))
        self.assertEqual(code, data["code"] if isinstance(data.get("code"), int) else None)

    @given(payload=st.dictionaries(st.text(max_size=8), json_values, max_size=4),
           code=st.integers(-10, 10000))
    def test_a_json_object_body_round_trips_with_its_code(self, payload, code):
        payload = dict(payload, code=code)
        got_code, data = sd_parse_response_payload(
            _response(json.dumps(payload).encode(), "text/plain")
        )
        self.assertEqual((got_code, data), (code, payload))

    def test_no_response_is_nothing(self):
        self.assertEqual(sd_parse_response_payload(None), (None, None))


_image = st.dictionaries(
    st.sampled_from(["uri", "category", "aspect", "width", "primary", "height"]),
    st.one_of(
        json_values,
        st.sampled_from(["Iconic", "Banner-L1", "Box Art", "2x3", "3x4", "16x9", "1x1",
                         "true", "True", "0", "240", "1920"]),
    ),
    max_size=6,
)
_styles = st.sampled_from(sorted(SD_POSTER_STYLE_CONFIG) + ["sd_recommended", "bogus", None])


class SdPickPosterUrlProperties(SimpleTestCase):
    @given(images=st.lists(st.one_of(_image, json_values), max_size=8), style=_styles)
    def test_the_pick_is_none_or_a_uri_taken_from_the_input(self, images, style):
        uri = _sd_pick_poster_url(images, style)
        if uri is None:
            return
        self.assertIn(
            uri, [img.get("uri") for img in images if isinstance(img, dict) and img.get("uri")]
        )

    @given(
        others=st.lists(_image, max_size=6),
        aspect=st.sampled_from(["2x3", "3x4"]),
        width=st.integers(240, 4000),
    )
    def test_a_primary_poster_category_image_is_always_found(self, others, aspect, width):
        # Any primary image in a poster category with a uri is reachable by
        # every style's fallback chain (recommended tier 1; configured styles'
        # "SD primary among poster categories" fallback).
        target = {"uri": "wanted", "category": "Iconic", "aspect": aspect,
                  "width": width, "primary": "true"}
        # A loop with msg=, not subTest: Hypothesis disables subTest under @given.
        for style in sorted(SD_POSTER_STYLE_CONFIG) + ["sd_recommended"]:
            self.assertIsNotNone(_sd_pick_poster_url(others + [target], style), msg=style)

    def test_an_empty_list_is_no_poster_for_every_style(self):
        for style in sorted(SD_POSTER_STYLE_CONFIG) + ["sd_recommended", "bogus"]:
            with self.subTest(style=style):
                self.assertIsNone(_sd_pick_poster_url([], style))
