"""Properties and fixed cases of ``dispatcharr.log_scrub.scrub_text`` / ``scrub_tail``.

Spec: docs/superpowers/specs/2026-11-12-log-scrubber-design.md, T4 (no listed
carrier survives, differential against ``redact_url``), T5 (idempotence, the
same-object guarantee, the accepted over-masks) and T6 (caps and linear time).

Every property has a positive control: a deliberately wrong scrubber patched in
must be caught by the very same checker, so a property that cannot fail cannot
pass for the real one either.
"""
import io
import logging
import re
import time
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from dispatcharr import log_scrub
from dispatcharr import utils as dispatcharr_utils
from dispatcharr.log_scrub import scrub_tail, scrub_text
from dispatcharr.url_redaction import SENSITIVE_QUERY_KEYS
from dispatcharr.utils import redact_url
from tests.log_scrub_rig import FactoryTestCase

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

SENT = "qzq"  # lower case: urlunsplit lower-cases a scheme, so an upper-case sentinel would look removed
CAP = 16384
TAIL_CAP = 65536
LEADING = "\"'(<[{"
TRAILING = "\"')>]},;."

PIECES = [
    "/", "//", "://", "?", "#", "&", "=", "@", ":", "%", "%77", "'", '"', "(", ")", "[", "]",
    "<", ">", "{", "}", ",", ";", ".",
    "username", "USERNAME", "Password", "passWord", "token", "api_key", "API_KEY", "api%5fkey",
    "%75sername", "pass%77ord", "tok%65n", "code", "state", "client_secret",
    "live", "movie", "series", "timeshift", "LIVE", "Movie",
    "http", "https", "ftp", "h.invalid", "example.invalid",
    "1", "23", "3.ts", "\u00e9", "\u0663", SENT,
    # Denser chunks: single draws from a 56-piece alphabet rarely line up a key and its "=".
    "username=", "?password=", "&token=", "#api_key=", "x_token=", "?code=", "&state=", "/live/", "/movie/",
    "live/", "http://", "https://u:", "//u:", "a@", "/a/b/1", "/u/p/3.ts", "?username=", "%20code=",
]



def _spellings(key):
    """Raw, upper-case and percent-encoded (first letter) spellings of a key name."""
    return [key, key.upper(), f"%{ord(key[0]):02x}{key[1:]}"]


# Every CURRENT key, iterated from the set (never listed by hand), in query and fragment
# positions, raw, upper-case and percent-encoded.
for _key in sorted(SENSITIVE_QUERY_KEYS):
    for _name in _spellings(_key):
        PIECES.extend([_name, f"?{_name}=", f"&{_name}=", f"#{_name}="])

CARRIER_EXAMPLES = [
    f"http://u:{SENT}@h.invalid/x",
    f"https://h.invalid/get.php?username=u&password={SENT}",
    f"h.invalid/live/u/{SENT}/1.ts",
    f"/u/{SENT}/1.ts",
    f"x?token={SENT}",
    f"//{SENT}@h",
    f"#api_key={SENT}",
    f"?code={SENT}",
]


@st.composite
def tokens(draw, max_pieces=28):
    # A uniform length (not hypothesis' small-biased list size), so long trigger-dense tokens are common.
    size = draw(st.integers(1, max_pieces - 1))
    pieces = draw(st.lists(st.sampled_from(PIECES), min_size=size, max_size=size))
    pieces.insert(draw(st.integers(0, len(pieces))), SENT)
    return "".join(pieces)


def _oracle(variant):
    """``redact_url`` with the root route counted only when the text starts with ``/``."""
    if variant.startswith("/"):
        return redact_url(variant)
    never = mock.MagicMock()
    never.match.return_value = None
    with mock.patch.object(dispatcharr_utils, "_XC_STREAM_ID_RE", never):
        return redact_url(variant)


def leaks(scrub, token):
    """True when the oracle removed the sentinel from a variant and ``scrub`` did not."""
    out = scrub(token)
    if SENT not in out:
        return False
    for variant in {token, token.lstrip(LEADING).rstrip(TRAILING)}:
        if SENT not in variant:
            continue
        reduced = _oracle(variant)
        if reduced == "***" and variant != "***":
            continue  # a parse failure is not a removal
        if SENT not in reduced:
            return True
    return False


def userinfo_only(text):
    """A deliberately leaky scrubber: masks userinfo and nothing else."""
    import re

    return re.sub(r"(?<=//)[^/?#@\s]*@", "***@", text)


def with_examples(fn):
    for example_text in CARRIER_EXAMPLES:
        fn = example(example_text)(fn)
    return fn


class NoCarrierSurvives(SimpleTestCase):
    """T4: property (a), differential against ``redact_url``."""

    @given(tokens())
    @with_examples
    def test_oracle_removal_implies_scrub_removal(self, token):
        self.assertFalse(leaks(scrub_text, token), f"carrier survived in {token!r} -> {scrub_text(token)!r}")

    @given(tokens(max_pieces=14))
    @with_examples
    def test_oracle_removal_implies_scrub_tail_removal(self, token):
        self.assertFalse(leaks(scrub_tail, token), f"carrier survived in {token!r}")

    def test_control_a_userinfo_only_scrubber_is_caught(self):
        @given(tokens())
        @with_examples
        def run(token):
            self.assertFalse(leaks(userinfo_only, token), token)

        with self.assertRaises(AssertionError):
            run()

    def test_control_the_identity_scrubber_is_caught(self):
        @given(tokens())
        @with_examples
        def run(token):
            self.assertFalse(leaks(lambda t: t, token), token)

        with self.assertRaises(AssertionError):
            run()

    def test_fixed_exact_outputs(self):
        # Exact output, not only absence: a restored wrapper fails even when the sentinel is gone.
        cases = {
            f"username={SENT})))": "username=***",
            "username=***)))": "username=***",
            "password=)))": "password=***",
        }
        for text, expected in cases.items():
            self.assertEqual(scrub_text(text), expected, text)

    def test_fixed_absence_cases(self):
        for text in (
            f"https://outer.invalid/?username=https://{SENT}.invalid/x",
            f"https://outer.invalid/#token=https://{SENT}.invalid/",
            f"password=https://{SENT}.invalid/",
            f"x=token={SENT}",
            f"pass%77ord={SENT}",
            f"//u:{SENT}@h/x",
            f"http://h//u/{SENT}/1.ts",
            f"https://outer.invalid/?to=http://u:{SENT}@inner.invalid/live/a/b/1",
        ):
            self.assertNotIn(SENT, scrub_text(text), text)

    def test_parse_failure_is_not_a_leak(self):
        text = f"http://[{SENT}"
        self.assertEqual(redact_url(text), "***")  # the oracle's parse-failure output
        self.assertEqual(scrub_text(text), text)
        self.assertFalse(leaks(scrub_text, text))

    def test_spec_fixed_examples_exact(self):
        # section 3.3 and section 12's fixed examples, every row exact.
        cases = {
            "http://user:pass@example.invalid/get.php": "http://***@example.invalid/get.php",
            "https://example.invalid/xmltv.php?username=user&password=pass": "https://example.invalid/xmltv.php?username=***",
            "https://x.invalid/?username=https://user.invalid/x": "https://x.invalid/?username=***",
            "password=)))": "password=***",
            "username=***)))": "username=***",
            "x=token=pass": "x=token=***",
            "example.invalid/live/user/pass/1.ts#t": "example.invalid/live/***",
            "/user/pass/1234.ts#t": "/***",
            "http://h.invalid/user/pass/1.ts": "http://h.invalid/***",
            "https://o.invalid/?to=http://user:pass@example.invalid/live/a/b/1": "https://o.invalid/?to=http://***@example.invalid/live/***",
            "username=CANARY)))": "username=***",
            "https://outer.invalid/?username=https://CANARY.invalid/x": "https://outer.invalid/?username=***",
            "/play.html#token=https://CANARY.invalid/": "/play.html#token=***",
            "pass%77ord=CANARY": "pass%77ord=***",
            "http://u:p@h.invalid/x)": "http://***@h.invalid/x)",
            "http://h.invalid//u/CANARY/1.ts": "http://h.invalid/***",
            "get.php?username=u&password=p#a": "get.php?username=***",
            "/alice/bravo/123.ts#frag": "/***",
            "'/u/p/1.ts',": "'/***",
            "(/live/u/p)": "(/live/***",
        }
        for text, expected in cases.items():
            self.assertEqual(scrub_text(text), expected, text)


# ---------------------------------------------------------------------------
# T5


BENIGN = [
    "A&E / HD",
    "24/7 News",
    "2026/11/12",
    "https://docs.example.invalid/guide",
    "http://127.0.0.1:5658",
    "http://example.invalid/channels/5",
    "/api/channels/streams/",
    "page 1/2/3/4",
]

OVER_MASKS = {
    "http://***@example.invalid/live/***/***/1.ts": "http://***@example.invalid/live/***",
    "get.php?username=u&page=2": "get.php?username=***",
    "Not Found: /api/channels/5/": "Not Found: /***",
    "https://h.invalid/api/v1/2": "https://h.invalid/***",
    "/srv/live/cache/config.json": "/srv/live/***",
    "C:/live/cache/config.json": "C:/live/***",
    "movie/series counts": "movie/*** counts",
    "csrf_token=abc": "csrf_token=***",
    "next_token=abc": "next_token=***",
    "'password=x',": "'password=***",
    "(/live/u/p)": "(/live/***",
}


def check_idempotent(scrub, text):
    once = scrub(text)
    assert scrub(once) == once, f"second pass changed {once!r}"


def check_same_object(scrub, text):
    assert scrub(text) is text, f"{text!r} was not returned as the same object"


@st.composite
def joined_tokens(draw):
    parts = draw(st.lists(tokens(max_pieces=12), min_size=1, max_size=6))
    return " ".join(parts)


@st.composite
def near_cap(draw, cap):
    base = draw(joined_tokens()) + " "
    length = cap + draw(st.integers(-200, 400))
    return (base * (length // len(base) + 1))[:length]


class IdempotenceSameObjectAndOverMasks(SimpleTestCase):
    @given(joined_tokens())
    def test_idempotent(self, text):
        check_idempotent(scrub_text, text)
        check_idempotent(scrub_tail, text)

    @given(near_cap(CAP))
    def test_idempotent_near_the_message_cap(self, text):
        check_idempotent(scrub_text, text)

    @hyp_settings(max_examples=25)
    @given(near_cap(TAIL_CAP))
    def test_idempotent_near_the_tail_cap(self, text):
        check_idempotent(scrub_tail, text)

    def test_fixed_dense_inputs_are_idempotent(self):
        for unit in ("username=x ", "password= ", "//a@", "//a@ ", "/live/x ", "x=token=y ", "a=b "):
            for count in range(2590, 2810, 7):
                text = unit * count
                check_idempotent(scrub_text, text)
        check_idempotent(scrub_tail, "username=x " * 6000)

    def test_control_a_non_idempotent_scrubber_is_caught(self):
        with self.assertRaises(AssertionError):
            check_idempotent(lambda s: s + "!", "plain")

    def test_benign_text_is_the_same_object(self):
        for text in BENIGN:
            check_same_object(scrub_text, text)
            check_same_object(scrub_tail, text)

    def test_control_a_rebuilding_scrubber_is_caught(self):
        with self.assertRaises(AssertionError):
            check_same_object(lambda s: "".join(list(s)), "A&E / HD")

    def test_unchanged_record_keeps_its_msg_and_args(self):
        args = ("A&E / HD", "2026/11/12")
        msg = "%s and %s counted"
        record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)
        log_scrub._scrub_record(record)
        self.assertIs(record.msg, msg)
        self.assertIs(record.args, args)

    def test_changed_record_gets_the_rendered_text_and_empty_args(self):
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "got %s", ("password=x",), None)
        log_scrub._scrub_record(record)
        self.assertEqual(record.msg, "got password=***")
        self.assertEqual(record.args, ())

    def test_accepted_over_masks_exact(self):
        for text, expected in OVER_MASKS.items():
            self.assertEqual(scrub_text(text), expected, text)

    def test_the_root_rule_does_not_start_after_a_digit(self):
        # 2026/11/12 cannot catch this: from either slash there are fewer than three segments.
        self.assertEqual(scrub_text("page 1/2/3/4"), "page 1/2/3/4")


class KeyRule(SimpleTestCase):
    """The key rule: containment on four names, equality after ?, & or # for the rest."""

    def test_every_current_key_is_masked_in_query_and_fragment_positions(self):
        # The guard: fails if a key is added to SENSITIVE_QUERY_KEYS that neither containment
        # nor the equality rule reaches.
        self.assertGreaterEqual(len(SENSITIVE_QUERY_KEYS), 13)
        for key in sorted(SENSITIVE_QUERY_KEYS):
            for name in _spellings(key):
                for lead in ("?", "&", "#"):
                    text = f"/cb{lead}{name}={SENT}"
                    self.assertNotIn(SENT, scrub_text(text), f"{key!r} as {text!r} survived")
                    self.assertFalse(leaks(scrub_text, text), text)

    def test_the_equality_keys_are_derived_from_the_shared_set(self):
        contained = log_scrub._CONTAINED_KEYS
        self.assertEqual(contained, ("username", "password", "token", "api_key"))
        self.assertEqual(
            log_scrub._EQUALITY_KEYS,
            {k for k in SENSITIVE_QUERY_KEYS if not any(c in k for c in contained)},
        )
        self.assertTrue({"code", "state", "client_secret"} <= log_scrub._EQUALITY_KEYS)

    def test_oidc_token_names_are_covered_by_containment_anywhere(self):
        for name in ("id_token", "access_token", "refresh_token"):
            for text in (f"{name}={SENT}", f"x/{name}={SENT}", f"?{name}={SENT}"):
                self.assertNotIn(SENT, scrub_text(text), text)

    def test_exact_rows(self):
        masked = {
            "/cb?code=abc&state=xyz": "/cb?code=***",
            "/cb?a=1&state=xyz&b=2": "/cb?a=1&state=***",
            "#access_token=abc": "#access_token=***",
            "?%63ode=abc": "?%63ode=***",
            "/cb?CODE=abc": "/cb?CODE=***",
        }
        for text, expected in masked.items():
            self.assertEqual(scrub_text(text), expected, text)

    def test_bare_and_look_alike_names_are_unchanged_same_object(self):
        # client_secret=abc bare is a documented residual (spec 7): it is not preceded by ?, & or #.
        for text in (
            "status_code=500", "exit_code=1", "codec=h264", "state=running", "estate=x",
            "code=5", "client_secret=abc", "a/state=running",
        ):
            check_same_object(scrub_text, text)


# ---------------------------------------------------------------------------
# T6


def within_cap(scrub, text, cap):
    out = scrub(text)
    assert len(out) <= cap, f"len {len(out)} exceeds cap {cap}"
    return out


def fast_enough(scrub, text, seconds):
    start = time.perf_counter()
    scrub(text)
    took = time.perf_counter() - start
    assert took < seconds, f"took {took * 1000:.0f} ms, limit {seconds * 1000:.0f} ms"


TIMING_UNITS = [
    "/", "//", "a/", "a://", "a=&", "password=) ", "/a/b/1#username=x ", "//a@", "=/", "(/a", "%=", "(/a/b/",
]


class CapsAndLinearTime(SimpleTestCase):
    def test_output_never_exceeds_the_cap(self):
        for unit in ("username=x ", "password= ", "//a@", "/live/x "):
            for cap, scrub in ((CAP, scrub_text), (TAIL_CAP, scrub_tail)):
                k0 = cap // len(unit)
                for k in range(k0 - 20, k0 + 21):
                    within_cap(scrub, unit * k, cap)
        for k in range(1480, 1501):  # round 2's 16,379-character case is k == 1489
            within_cap(scrub_text, "username=x " * k, CAP)
        self.assertEqual(len(scrub_text("username=x " * 1489)), 16362)

    def test_control_an_unbounded_scrubber_is_caught(self):
        with self.assertRaises(AssertionError):
            within_cap(lambda s: s, "w " * 20000, CAP)

    def test_adversarial_shapes_are_fast_at_the_message_cap(self):
        for unit in TIMING_UNITS:
            text = (unit * (CAP // len(unit) + 1))[:CAP]
            fast_enough(scrub_text, text, 0.1)

    def test_adversarial_shapes_are_fast_at_the_tail_cap(self):
        for unit in TIMING_UNITS:
            text = (unit * (TAIL_CAP // len(unit) + 1))[:TAIL_CAP]
            fast_enough(scrub_tail, text, 0.4)

    def test_control_a_slow_scrubber_is_caught(self):
        def slow(text):
            time.sleep(0.15)
            return text

        with self.assertRaises(AssertionError):
            fast_enough(slow, "x", 0.1)

    def test_oversized_input_is_cut_at_whitespace_with_a_marker(self):
        for sep in (" ", "\t", "\n", "\u00a0", "\u2003", "\u2028"):
            text = ("word" + sep) * 4000  # 20,000 characters
            out = within_cap(scrub_text, text, CAP)
            self.assertTrue(out.endswith(" characters]"), repr(out[-60:]))
            self.assertIn("[log scrubber: truncated from 20000 characters]", out)
            self.assertGreater(len(out), 16000, f"head lost for separator {sep!r}")
        out = within_cap(scrub_text, "word " * 300000, CAP)
        self.assertTrue(out.endswith("[log scrubber: truncated from 1500000 characters]"))
        self.assertEqual(scrub_text(out), out)

    def test_oversized_traceback_keeps_its_last_line(self):
        for sep in (" ", "\t", "\n", "\u00a0", "\u2003", "\u2028"):
            text = ("word" + sep) * 16000 + "ValueError: tail-marker"
            out = within_cap(scrub_tail, text, TAIL_CAP)
            self.assertTrue(out.endswith("ValueError: tail-marker"), f"separator {sep!r}")
            self.assertTrue(out.startswith("[log scrubber: truncated from "))

    def test_no_whitespace_in_the_window_withholds_everything(self):
        out = scrub_text("x" * 30000)
        self.assertTrue(out.startswith(" [log scrubber: truncated from 30000 characters]"), out[:80])
        self.assertLess(len(out), 100)

    def test_a_token_straddling_the_tail_cut_is_withheld_whole(self):
        # scrub_tail keeps the tail and cuts at the first whitespace at or after
        # len - (TAIL_CAP - 64). A cut inside a token would leave "er:pass@host/..." with no "//".
        carrier = f"http://{SENT}u:{SENT}p@h.invalid/x?password={SENT}s"
        keep = TAIL_CAP - 64
        pre = "w " * 500
        for inside in range(1, len(carrier)):
            after = (" w" * (keep + len(carrier)))[: inside + keep - len(carrier)]
            text = pre + carrier + after
            n = len(text)
            cut = n - keep
            self.assertEqual(cut, len(pre) + inside)  # the cut starts `inside` characters into the token
            out = scrub_tail(text)
            boundary = re.compile(r"\s").search(text, cut).start()
            expected = f"[log scrubber: truncated from {n} characters]" + text[boundary:]
            self.assertEqual(out, expected, f"inside={inside}")
            self.assertNotIn(SENT, out)

    def test_the_scan_never_reads_more_than_the_cap(self):
        # D4: the input is cut BEFORE scanning, so the scanner never sees more than the cap.
        for scrub, cap in ((scrub_text, CAP), (scrub_tail, TAIL_CAP)):
            seen = []
            with mock.patch.object(log_scrub, "_scan", side_effect=lambda text: (seen.append(len(text)), text)[1]):
                scrub("word " * 120000)
            self.assertTrue(seen)
            self.assertLessEqual(max(seen), cap, scrub.__name__)

    def test_a_carrier_straddling_the_cut_is_absent(self):
        carrier = f"http://{SENT}u:{SENT}p@h.invalid/x?password={SENT}s"
        limit = CAP - 64
        for pad in range(limit - 70, limit + 10):
            prefix = ("w " * pad)[:pad]
            text = prefix + " " + carrier + " " + "w " * 2000
            out = scrub_text(text)
            self.assertNotIn(SENT, out, f"pad {pad}")
            self.assertLessEqual(len(out), CAP)


# ---------------------------------------------------------------------------
# T7: failure never raises into the caller and never emits the original text


class FailureBehaviour(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.assert_scrubber_installed()
        patcher = mock.patch.object(logging, "raiseExceptions", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def presetting_factory(self, **attrs):
        """A foreign factory below the scrubber that sets record attributes, as a chained one could."""

        def foreign_factory(*args, **kwargs):
            record = logging.LogRecord(*args, **kwargs)
            for name, value in attrs.items():
                setattr(record, name, value)
            return record

        logging.setLogRecordFactory(foreign_factory)
        self.assertTrue(log_scrub.install())

    def test_case_1_scrub_text_raising_is_withheld(self):
        logger, stream = self.capture("t7.one")
        with mock.patch.object(log_scrub, "scrub_text", side_effect=ValueError(SENT)):
            logger.info("fetch http://u:%s@h.invalid/x", SENT)  # no exception reaches the caller
        self.assertEqual(stream.getvalue(), "<log message withheld: scrubber failed (ValueError)>\n")
        self.assertNotIn(SENT, stream.getvalue())

    def test_case_2_a_formatting_failure_is_withheld_and_not_dumped_to_stderr(self):
        logger, stream = self.capture("t7.two")
        stderr = io.StringIO()
        with mock.patch("sys.stderr", stderr):
            logger.info("%d", SENT)
        self.assertEqual(stream.getvalue(), "<log message withheld: formatting failed (TypeError)>\n")
        self.assertNotIn(SENT, stream.getvalue())
        self.assertNotIn(SENT, stderr.getvalue(), "logging's own error dump printed the raw arguments")

    def test_case_3_a_preset_exc_text_is_scrubbed(self):
        self.presetting_factory(exc_text=f"Traceback (most recent call last):\nValueError: username={SENT}")
        logger, stream = self.capture("t7.three")
        logger.info("failed")
        self.assertIn("username=***", stream.getvalue())
        self.assertNotIn(SENT, stream.getvalue())

    def test_case_4_logger_exception_scrubs_the_traceback(self):
        logger, stream = self.capture("t7.four")
        try:
            raise ValueError(f"bad http://h.invalid/get.php?username={SENT}")
        except ValueError:
            logger.exception("failed http://example.invalid/xmltv.php?username=%s", SENT)
        out = stream.getvalue()
        self.assertIn("xmltv.php?username=***", out)
        self.assertIn("ValueError: bad http://h.invalid/get.php?username=***", out)
        self.assertNotIn(SENT, out)

    def test_case_5_scrub_tail_raising_withholds_both_fields(self):
        self.presetting_factory(exc_text=f"ValueError: username={SENT}", stack_info=f"File x: username={SENT}")
        logger, stream = self.capture("t7.five")
        with mock.patch.object(log_scrub, "scrub_tail", side_effect=RuntimeError(SENT)):
            logger.info("failed")
        out = stream.getvalue()
        self.assertIn("<traceback withheld: scrubber failed (RuntimeError)>", out)
        self.assertIn("<stack withheld: scrubber failed (RuntimeError)>", out)
        self.assertNotIn(SENT, out)

    def test_case_6_the_outer_fallback_withholds_all_three_fields(self):
        # The message-step helper itself raises, so no per-field handler sees it.
        self.presetting_factory(exc_text=f"ValueError: username={SENT}", stack_info=f"File x: username={SENT}")
        logger, stream = self.capture("t7.six")
        with mock.patch.object(log_scrub, "_scrub_message", side_effect=RuntimeError(SENT)):
            logger.info("fetch username=%s", SENT)
        out = stream.getvalue()
        self.assertIn("<log message withheld: scrubber failed (RuntimeError)>", out)
        self.assertIn("<traceback withheld: scrubber failed (RuntimeError)>", out)
        self.assertIn("<stack withheld: scrubber failed (RuntimeError)>", out)
        self.assertNotIn(SENT, out)

    def test_case_7_an_oversized_traceback_keeps_its_last_line(self):
        self.presetting_factory(exc_text=("word " * 20000) + "\nValueError: tail-marker")
        logger, stream = self.capture("t7.seven")
        logger.info("failed")
        out = stream.getvalue()
        self.assertTrue(out.rstrip("\n").endswith("ValueError: tail-marker"))
        self.assertIn("[log scrubber: truncated from ", out)

    def test_the_traceback_is_rendered_once_and_exc_info_is_kept(self):
        logger, stream = self.capture("t7.keep")
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        try:
            raise ValueError(f"x?password={SENT}")
        except ValueError:
            logger.exception("failed")
        (record,) = records
        self.assertIsNotNone(record.exc_info)
        self.assertIsNotNone(record.exc_text)
        self.assertNotIn(SENT, record.exc_text)
        self.assertIn("password=***", record.exc_text)

    def test_a_traceback_between_the_two_caps_keeps_its_last_line(self):
        # Longer than the message cap, shorter than the tail cap: only scrub_tail keeps the last
        # line. Routing exc_text or stack_info through scrub_text would cut it to the head.
        body = ("word " * 6000) + "\nValueError: tail-marker"
        self.assertTrue(CAP < len(body) < TAIL_CAP)
        for field in ("exc_text", "stack_info"):
            with self.subTest(field):
                self.presetting_factory(**{field: body})
                logger, stream = self.capture(f"t7.between.{field}")
                logger.info("failed")
                out = stream.getvalue()
                self.assertTrue(out.rstrip("\n").endswith("ValueError: tail-marker"), out[-80:])
                self.assertNotIn("[log scrubber: truncated", out)
                logging.setLogRecordFactory(self.entry_factory)

    def test_a_rendered_traceback_between_the_two_caps_keeps_its_last_line(self):
        logger, stream = self.capture("t7.rendered")
        try:
            raise ValueError(("word " * 6000) + "tail-marker")
        except ValueError:
            logger.exception("failed")
        out = stream.getvalue()
        self.assertGreater(len(out), CAP)
        self.assertTrue(out.rstrip("\n").endswith("tail-marker"), out[-80:])
        self.assertNotIn("[log scrubber: truncated", out)


class WholePathArguments(FactoryTestCase):
    """A string argument that is a path holding whitespace is read as one token.

    Django logs ``request.path`` decoded (``"%s: %s", reason, request.path``), so
    an Xtream credential holding a space is one path segment there but two
    tokens in the rendered message; the per-token rule alone masked the first
    token only and logged the rest of the credential.
    """

    LEAK = "a credential holding a space survived: the path argument was not read whole"

    def scrubbed(self, msg, args):
        record = logging.LogRecord("django.request", logging.WARNING, __file__, 1, msg, args, None)
        log_scrub._scrub_record(record)
        return record

    def test_spaced_username_and_password_in_a_prefix_route(self):
        path = "/movie/xcuser sentinel-sp3/xcuser sentinel-sp3/1.mp4"
        record = self.scrubbed("%s: %s", ("Unauthorized", path))
        out = record.getMessage()
        self.assertNotIn("sentinel-sp3", out, self.LEAK)
        self.assertNotIn("xcuser", out, self.LEAK)
        self.assertEqual(out, "Unauthorized: /movie/***")
        self.assertEqual(record.args, ())

    def test_short_password_after_a_spaced_username(self):
        record = self.scrubbed("%s: %s", ("Unauthorized", "/movie/ab cd/xyz/1.mp4"))
        out = record.getMessage()
        for piece in ("cd", "xyz"):
            self.assertNotIn(piece, out, self.LEAK)
        self.assertEqual(out, "Unauthorized: /movie/***")

    def test_spaced_username_in_the_bare_root_route(self):
        record = self.scrubbed("%s: %s", ("Not Implemented", "/xc user/sentinel-pw/1.ts"))
        self.assertEqual(record.getMessage(), "Not Implemented: /***", self.LEAK)

    def test_mapping_arguments(self):
        record = self.scrubbed("%(reason)s: %(path)s", {"reason": "Not Found", "path": "/live/ab cd/xyz/1.ts"})
        self.assertEqual(record.getMessage(), "Not Found: /live/***", self.LEAK)

    def test_through_the_installed_factory(self):
        self.assert_scrubber_installed()
        logger, stream = self.capture("whole.path.factory")
        logger.warning("%s: %s", "Unauthorized", "/series/ab cd/xyz/1.mkv")
        self.assertEqual(stream.getvalue(), "Unauthorized: /series/***\n", self.LEAK)

    def test_an_argument_over_the_cap_is_withheld_not_read(self):
        record = self.scrubbed("%s: %s", ("Not Found", "/movie/" + "a b" * CAP))
        self.assertEqual(record.getMessage(), "Not Found: /***")

    def test_control_a_slash_leading_argument_without_spaces_is_untouched(self):
        msg, args = "%s: %s", ("Not Found", "/api/channels/streams/")
        record = self.scrubbed(msg, args)
        self.assertIs(record.msg, msg)
        self.assertIs(record.args, args)

    def test_control_a_benign_spaced_path_argument_is_untouched(self):
        msg, args = "%s: %s", ("Saved", "/data/My Recordings/show.ts")
        record = self.scrubbed(msg, args)
        self.assertIs(record.msg, msg)
        self.assertIs(record.args, args)
