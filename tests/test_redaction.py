"""Tests for the credential-redaction helpers in dispatcharr/utils.py.

Provider credentials reach this project's logs through three carriers at once:
HTTP userinfo, query parameters (the Xtream ``get.php?username=…&password=…``
shape), and *path segments* (``/live/<user>/<pass>/<id>`` and friends, mounted
at the site root by dispatcharr/urls.py). ``redact_url`` and ``redact_headers``
exist so the five log calls that used to emit those at INFO cannot leak a
working credential.

The properties below state the one thing that actually matters — the secret
substring must not survive into the output — over generated credentials in each
carrier, plus a no-raise property over arbitrary text, because a redaction
helper that throws turns a leak into an outage. The example tests pin the exact
shapes the five patched call sites produce, and the control pins the other half
of the contract: a URL with nothing to redact comes back byte-identical, so
redaction does not quietly rewrite every logged URL.

Runs without Redis or the database (SimpleTestCase, pure functions).
"""

from django.http.request import HttpHeaders
from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from dispatcharr.utils import REDACTED, redact_headers, redact_url

# CI-deterministic profile — see
# apps/proxy/live_proxy/tests/test_property_ts_realignment.py for the rationale.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Credential alphabet: characters a provider actually issues in Xtream
# usernames/passwords, and that need no percent-encoding in a URL. min_size=6
# keeps a generated secret from colliding with an incidental substring of the
# surrounding URL, so every fixed part of the templates below is built from
# alphanumeric runs shorter than six characters ("p.tv", "get.php", "1234.ts").
secrets = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_",
    min_size=6,
    max_size=24,
)

sensitive_query_keys = st.sampled_from(["password", "username", "token", "api_key"])

xtream_prefixes = ["live", "movie", "series", "timeshift"]
xtream_prefix_strategy = st.sampled_from(xtream_prefixes)

# Arbitrary text, including control characters and the bracket soup that
# urlsplit rejects outright — redact_url must return a string for all of it.
arbitrary_text = st.text(max_size=200) | st.text(
    alphabet="[]:@/?&=%#.abcdef0123456789", max_size=200
)


class RedactUrlProperties(SimpleTestCase):
    @given(user=secrets, password=secrets)
    def test_userinfo_secret_never_survives(self, user, password):
        out = redact_url(f"http://{user}:{password}@p.tv/a/b.ts")
        self.assertNotIn(password, out)
        self.assertNotIn(user, out)
        self.assertEqual(out, f"http://{REDACTED}@p.tv/a/b.ts")

    @given(key=sensitive_query_keys, secret=secrets)
    def test_sensitive_query_value_never_survives(self, key, secret):
        out = redact_url(f"http://p.tv/get.php?{key}={secret}&type=m3u")
        self.assertNotIn(secret, out)
        self.assertIn(f"{key}={REDACTED}", out)
        # Untargeted parameters are left alone.
        self.assertIn("type=m3u", out)

    @given(key=sensitive_query_keys, secret=secrets)
    def test_sensitive_query_key_is_case_insensitive(self, key, secret):
        out = redact_url(f"http://p.tv/get.php?{key.upper()}={secret}")
        self.assertNotIn(secret, out)

    @given(prefix=xtream_prefix_strategy, user=secrets, password=secrets)
    def test_xtream_path_credentials_never_survive(self, prefix, user, password):
        out = redact_url(f"http://p.tv/{prefix}/{user}/{password}/1234.ts")
        self.assertNotIn(user, out)
        self.assertNotIn(password, out)
        self.assertEqual(out, f"http://p.tv/{prefix}/{REDACTED}/{REDACTED}/1234.ts")

    @given(
        prefix=xtream_prefix_strategy, user=secrets, password=secrets, sub=secrets
    )
    def test_xtream_credentials_survive_a_server_subpath(
        self, prefix, user, password, sub
    ):
        # apps/m3u/tasks.py builds provider URLs that may carry a sub-path
        # before /live/, so the prefix is matched anywhere in the path.
        assume(sub.lower() not in xtream_prefixes)
        assume(user not in sub and password not in sub)
        out = redact_url(f"http://p.tv/{sub}/{prefix}/{user}/{password}/1234.ts")
        self.assertNotIn(user, out)
        self.assertNotIn(password, out)
        self.assertIn(sub, out)

    @given(user=secrets, password=secrets)
    def test_xc_root_route_credentials_never_survive(self, user, password):
        # dispatcharr/urls.py mounts `/<username>/<password>/<channel_id>` at
        # the site root, with no prefix segment to key off.
        out = redact_url(f"http://p.tv/{user}/{password}/42")
        self.assertNotIn(user, out)
        self.assertNotIn(password, out)
        self.assertEqual(out, f"http://p.tv/{REDACTED}/{REDACTED}/42")

    @given(text=arbitrary_text)
    def test_never_raises_and_always_returns_a_string(self, text):
        self.assertIsInstance(redact_url(text), str)


class RedactUrlExamples(SimpleTestCase):
    """The exact shapes the five patched call sites produce."""

    def test_xc_live_stream_path(self):
        self.assertEqual(redact_url("/live/joe/hunter2/1.ts"), "/live/***/***/1.ts")

    def test_xc_movie_path_with_extension(self):
        self.assertEqual(redact_url("/movie/joe/hunter2/2.mkv"), "/movie/***/***/2.mkv")

    def test_xc_series_path(self):
        self.assertEqual(redact_url("/series/joe/hunter2/3.mp4"), "/series/***/***/3.mp4")

    def test_timeshift_path(self):
        self.assertEqual(
            redact_url("/timeshift/joe/hunter2/60/1757000000/7"),
            "/timeshift/***/***/60/1757000000/7",
        )

    def test_get_php_query_credentials(self):
        self.assertEqual(
            redact_url(
                "http://provider.tv:8080/get.php?username=joe&password=hunter2&type=m3u_plus"
            ),
            "http://provider.tv:8080/get.php?username=***&password=***&type=m3u_plus",
        )

    def test_full_request_path_with_query(self):
        # What request.get_full_path() hands the VOD view.
        self.assertEqual(
            redact_url("/movie/joe/hunter2/2.mkv?token=abc123"),
            "/movie/***/***/2.mkv?token=***",
        )

    def test_dvr_stream_url_with_token(self):
        self.assertEqual(
            redact_url("http://127.0.0.1:9191/proxy/ts/stream/9d1b8f/?token=s3cr3t"),
            "http://127.0.0.1:9191/proxy/ts/stream/9d1b8f/?token=***",
        )

    def test_userinfo_is_stripped_host_and_port_kept(self):
        self.assertEqual(
            redact_url("http://joe:hunter2@provider.tv:8080/live/joe/hunter2/1.ts"),
            "http://***@provider.tv:8080/live/***/***/1.ts",
        )

    def test_m3u_transformed_url_shape(self):
        # apps/m3u/tasks.py builds this probe URL from the account credentials.
        self.assertEqual(
            redact_url("http://provider.tv:8080/live/joe/hunter2/1234.ts"),
            "http://provider.tv:8080/live/***/***/1234.ts",
        )

    def test_credential_free_url_round_trips_unchanged(self):
        url = "https://example.com/a/b.m3u8?x=1"
        # assertIs, not assertEqual: the contract is byte-identical, which the
        # implementation delivers by returning the input object untouched.
        self.assertIs(redact_url(url), url)

    def test_credential_free_deep_path_round_trips_unchanged(self):
        url = "http://example.com/hls/segments/stream/000123.ts?seq=7"
        self.assertIs(redact_url(url), url)

    def test_non_string_input_returns_the_mask(self):
        for value in (None, 42, b"http://example.com/", object(), ["a"], {"a": 1}):
            with self.subTest(value=type(value).__name__):
                self.assertEqual(redact_url(value), REDACTED)

    def test_unparseable_input_returns_the_mask(self):
        # An unterminated IPv6 literal is what urlsplit refuses outright.
        self.assertEqual(redact_url("http://[::1/live/joe/hunter2/1.ts"), REDACTED)

    def test_empty_string_round_trips(self):
        self.assertEqual(redact_url(""), "")

    def test_query_shaped_fragment_is_masked(self):
        # Client-side players carry stream parameters after the "#".
        self.assertEqual(
            redact_url("http://p.tv/play.html#username=joe&password=hunter2&x=1"),
            "http://p.tv/play.html#username=***&password=***&x=1",
        )

    def test_plain_fragment_is_left_alone(self):
        url = "https://example.com/docs/guide.html#password-reset"
        self.assertIs(redact_url(url), url)


class RedactHeadersTests(SimpleTestCase):
    def test_authorization_and_cookie_are_masked(self):
        out = redact_headers(
            {
                "Authorization": "Basic am9lOmh1bnRlcjI=",
                "Cookie": "sessionid=deadbeef",
                "User-Agent": "VLC/3.0.20",
                "Range": "bytes=0-1023",
            }
        )
        self.assertEqual(
            out,
            {
                "Authorization": REDACTED,
                "Cookie": REDACTED,
                "User-Agent": "VLC/3.0.20",
                "Range": "bytes=0-1023",
            },
        )

    def test_every_listed_header_is_masked_case_insensitively(self):
        out = redact_headers(
            {
                "authorization": "a",
                "COOKIE": "b",
                "X-Api-Key": "c",
                "proxy-authorization": "d",
                "Set-Cookie": "e",
            }
        )
        self.assertEqual(set(out.values()), {REDACTED})
        self.assertEqual(len(out), 5)

    def test_meta_style_names_are_masked(self):
        # request.META spelling, which the credential-logging guard also flags.
        out = redact_headers({"HTTP_AUTHORIZATION": "Basic x", "HTTP_HOST": "h"})
        self.assertEqual(out, {"HTTP_AUTHORIZATION": REDACTED, "HTTP_HOST": "h"})

    def test_meta_carries_the_request_line_and_it_is_redacted(self):
        # The dangerous half of request.META is not the headers: PATH_INFO,
        # QUERY_STRING, RAW_URI and REQUEST_URI hold the Xtream credentials
        # verbatim. They are redacted, not blanked — the path is the useful
        # part of a request log.
        out = redact_headers(
            {
                "PATH_INFO": "/live/joe/hunter2/1.ts",
                "QUERY_STRING": "username=joe&password=hunter2&type=m3u",
                "RAW_URI": "/movie/joe/hunter2/2.mkv?token=s3cr3t",
                "REQUEST_URI": "/series/joe/hunter2/3.mp4",
                "HTTP_AUTHORIZATION": "Basic am9lOmh1bnRlcjI=",
                "HTTP_COOKIE": "sessionid=deadbeef",
                "HTTP_X_API_KEY": "k-12345",
                "HTTP_PROXY_AUTHORIZATION": "Basic am9lOmh1bnRlcjI=",
                "REQUEST_METHOD": "GET",
                "SERVER_PORT": "5656",
            }
        )
        self.assertEqual(
            out,
            {
                "PATH_INFO": "/live/***/***/1.ts",
                "QUERY_STRING": "username=***&password=***&type=m3u",
                "RAW_URI": "/movie/***/***/2.mkv?token=***",
                "REQUEST_URI": "/series/***/***/3.mp4",
                "HTTP_AUTHORIZATION": REDACTED,
                "HTTP_COOKIE": REDACTED,
                "HTTP_X_API_KEY": REDACTED,
                "HTTP_PROXY_AUTHORIZATION": REDACTED,
                "REQUEST_METHOD": "GET",
                "SERVER_PORT": "5656",
            },
        )
        self.assertNotIn("hunter2", str(out))
        self.assertNotIn("s3cr3t", str(out))

    def test_credential_free_request_line_is_left_alone(self):
        out = redact_headers(
            {
                "PATH_INFO": "/api/channels/",
                "QUERY_STRING": "page=2&ordering=name",
                "REQUEST_URI": "",
            }
        )
        self.assertEqual(
            out,
            {
                "PATH_INFO": "/api/channels/",
                "QUERY_STRING": "page=2&ordering=name",
                "REQUEST_URI": "",
            },
        )

    def test_unparseable_request_line_value_yields_the_mask(self):
        out = redact_headers({"REQUEST_URI": "http://[::1/live/joe/hunter2/1.ts"})
        self.assertEqual(out, {"REQUEST_URI": REDACTED})

    def test_non_string_request_line_value_yields_the_mask(self):
        out = redact_headers({"PATH_INFO": None, "QUERY_STRING": None})
        # PATH_INFO goes through redact_url (non-string -> mask); an empty
        # QUERY_STRING is falsy and copied through untouched.
        self.assertEqual(out, {"PATH_INFO": REDACTED, "QUERY_STRING": None})

    def test_returns_a_plain_dict_not_the_input_mapping(self):
        source = {"User-Agent": "VLC/3.0.20"}
        out = redact_headers(source)
        self.assertIsInstance(out, dict)
        self.assertIsNot(out, source)

    def test_django_httpheaders_mapping_is_accepted(self):
        headers = HttpHeaders(
            {
                "HTTP_AUTHORIZATION": "Basic am9lOmh1bnRlcjI=",
                "HTTP_COOKIE": "sessionid=deadbeef",
                "HTTP_USER_AGENT": "VLC/3.0.20",
            }
        )
        out = redact_headers(headers)
        self.assertEqual(out["Authorization"], REDACTED)
        self.assertEqual(out["Cookie"], REDACTED)
        self.assertEqual(out["User-Agent"], "VLC/3.0.20")

    def test_non_mapping_input_returns_an_empty_dict(self):
        for value in (None, 42, "Authorization: Basic x", ["a", "b"]):
            with self.subTest(value=type(value).__name__):
                self.assertEqual(redact_headers(value), {})

    @given(secret=secrets)
    def test_authorization_secret_never_survives(self, secret):
        out = redact_headers({"Authorization": f"Bearer {secret}"})
        self.assertNotIn(secret, str(out))
