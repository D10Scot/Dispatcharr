"""Per-carrier-class properties of ``scrub_text`` (spec T4, reached by construction).

``tests/test_log_scrub.py``'s trigger-dense random tokens stopped reaching the userinfo, prefix and
root classes once the key pieces were added. Here each carrier CLASS has its own strategy that
builds a carrier of that class on purpose, its own positive control (a scrubber with exactly that
rule disabled must be caught), and a meta-assertion that fails if the strategy produced too few
examples in which ``redact_url`` itself removes the sentinel, so a generator cannot drift empty
again. Fixed witnesses, one per known wrong edit, pin the deterministic side.
"""
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import given, strategies as st

from dispatcharr import log_scrub
from dispatcharr.log_scrub import scrub_text
from dispatcharr.url_redaction import SENSITIVE_QUERY_KEYS
from tests.test_log_scrub import LEADING, SENT, TRAILING, leaks, _oracle, _spellings

HOSTS = ["h.invalid", "example.invalid:8080", "10.0.0.1", "[::1]:80"]
WRAP_LEFT = ["", "", "(", "'", '"', "<", "["]
WRAP_RIGHT = ["", "", ")", "'", '"', ">", ",", ";", "."]


class Vacuous(Exception):
    """A class strategy produced too few oracle removals. Not an AssertionError on purpose."""


def oracle_removes(token):
    """True when ``redact_url`` removes the sentinel from the token or its unwrapped form."""
    for variant in {token, token.lstrip(LEADING).rstrip(TRAILING)}:
        if SENT not in variant:
            continue
        reduced = _oracle(variant)
        if reduced == "***" and variant != "***":
            continue
        if SENT not in reduced:
            return True
    return False


def wrap(draw, core):
    return draw(st.sampled_from(WRAP_LEFT)) + core + draw(st.sampled_from(WRAP_RIGHT))


def casings(word):
    return [word, word.upper(), word.title(), f"%{ord(word[0]):02x}{word[1:]}"]


@st.composite
def userinfo_tokens(draw):
    scheme = draw(st.sampled_from(["http://", "https://", "//", "ftp://", "a+b://", "x://"]))
    # Userinfo may itself contain ":" and extra "@" (the last "@" ends it), and always the sentinel.
    parts = draw(st.lists(st.sampled_from(["u", "x", ":", "@", "%40", "pw", "a.b", "-"]), max_size=5))
    parts.insert(draw(st.integers(0, len(parts))), SENT)
    host = draw(st.sampled_from(HOSTS))
    tail = draw(st.sampled_from(["", "/", "/x", "/get.php?a=1", "?x=1", "#f"]))
    return wrap(draw, scheme + "".join(parts) + "@" + host + tail)


CONTAINED_NAMES = list(log_scrub._CONTAINED_KEYS)


@st.composite
def containment_tokens(draw):
    base = draw(st.sampled_from(CONTAINED_NAMES))
    exact = draw(st.booleans())
    name = base if exact else draw(st.sampled_from(["x_", "csrf_", "my", "id_", "access_"])) + base
    name = draw(st.sampled_from(casings(name)))
    template = draw(st.sampled_from([
        "{n}={S}", "?{n}={S}", "?a=1&{n}={S}", "#{n}={S}", "/p?{n}={S}&b=2",
        "http://h.invalid/x?{n}={S}", "x/{n}={S}", "a=1&{n}={S}",
    ]))
    return wrap(draw, template.format(n=name, S=SENT))


EQUALITY_NAMES = sorted(log_scrub._EQUALITY_KEYS)


@st.composite
def equality_tokens(draw):
    key = draw(st.sampled_from(EQUALITY_NAMES))
    name = draw(st.sampled_from(casings(key) + [f"%20{key}", f"%09{key}", f"{key}%20"]))
    template = draw(st.sampled_from([
        "?{n}={S}", "&{n}={S}", "#{n}={S}", "/cb?{n}={S}", "/cb?a=1&{n}={S}",
        "http://h.invalid/p?{n}={S}", "x#{n}={S}", "?a=1#b=2&{n}={S}", "?{n}={S}&state=y",
    ]))
    return wrap(draw, template.format(n=name, S=SENT))


@st.composite
def prefix_tokens(draw):
    word = draw(st.sampled_from(sorted(log_scrub.url_redaction.XTREAM_PATH_PREFIXES)))
    word = draw(st.sampled_from([word, word.upper(), word.title(), word[:1].upper() + word[1:-1] + word[-1:].upper()]))
    lead = draw(st.sampled_from(["", "/", "http://h.invalid/", "h.invalid/", "a/", "x:", "//h.invalid/", "/srv/"]))
    others = draw(st.lists(st.sampled_from(["u", "p", "1.ts", "a", "-"]), max_size=2))
    segments = [SENT] + others if draw(st.booleans()) else ["u", SENT] + others
    tail = draw(st.sampled_from(["", "/1.ts", "/1.ts#f", ".m3u8"]))
    return wrap(draw, f"{lead}{word}/" + "/".join(segments) + tail)


@st.composite
def root_tokens(draw):
    lead = draw(st.sampled_from(["/", "//h.invalid/", "http://h.invalid/", "x://h.invalid/", "(/", "'/"]))
    first, second = (SENT, "p") if draw(st.booleans()) else ("u", SENT)
    stream_id = draw(st.sampled_from(["1", "123.ts", "9", "\u0663", "7.m3u8", "0"]))
    gap = draw(st.sampled_from(["/", "/", "//"]))
    tail = draw(st.sampled_from(["", "#f", "?q=1", ")"]))
    return wrap(draw, f"{lead}{first}{gap}{second}/{stream_id}{tail}")


KEY_CARRIERS = ["username=v", "password=v", "api_key=v", "x_token=v", "token=v"]


@st.composite
def two_carrier_tokens(draw):
    """Userinfo that itself holds a key carrier, plus (sometimes) a second carrier in the tail."""
    parts = draw(st.lists(st.sampled_from(["x", ":", "&", "%40", "-"]), max_size=3))
    parts.insert(draw(st.integers(0, len(parts))), SENT)
    parts.append(draw(st.sampled_from(["&", ":"])))
    parts.append(draw(st.sampled_from(KEY_CARRIERS)))
    host = draw(st.sampled_from(HOSTS))
    tail = draw(st.sampled_from(["", "/x", "/live/a/b/1", "?token=z", f"/live/{SENT}/b/1", f"?code={SENT}"]))
    return wrap(draw, "//" + "".join(parts) + "@" + host + tail)


def check_class(strategy, scrub, minimum):
    stats = {"examples": 0, "removed": 0}

    @given(strategy)
    def run(token):
        stats["examples"] += 1
        stats["removed"] += oracle_removes(token)
        out = scrub(token)
        assert SENT not in out, f"carrier survived in {token!r} -> {out!r}"
        assert not leaks(scrub, token), f"oracle disagrees on {token!r} -> {out!r}"

    run()
    if stats["removed"] < minimum:
        raise Vacuous(f"only {stats['removed']} of {stats['examples']} examples had a redact_url removal; need {minimum}")
    return stats


# (name, strategy, minimum oracle removals, a patch that disables exactly that rule)
CLASSES = {
    "userinfo": (userinfo_tokens(), 100, ("_authority_spans", ([], []))),
    "key_containment": (containment_tokens(), 20, ("_key_tail", -1)),
    "key_equality": (equality_tokens(), 100, ("_EQUALITY_KEYS", frozenset())),
    "xtream_prefix": (prefix_tokens(), 60, ("_prefix_tail", -1)),
    "root_route": (root_tokens(), 40, ("_root_tail", -1)),
    "two_carriers": (two_carrier_tokens(), 20, ("_authority_spans", ([], []))),
}


class CarrierClassProperties(SimpleTestCase):
    def run_real(self, name):
        strategy, minimum, _ = CLASSES[name]
        return check_class(strategy, scrub_text, minimum)

    def run_control(self, name):
        strategy, _, (attribute, replacement) = CLASSES[name]
        patcher = mock.patch.object(
            log_scrub, attribute,
            new=frozenset() if attribute == "_EQUALITY_KEYS" else mock.Mock(return_value=replacement),
        )
        with patcher:
            with self.assertRaises(AssertionError):
                check_class(strategy, scrub_text, minimum=0)

    def test_userinfo(self):
        self.run_real("userinfo")

    def test_key_containment(self):
        self.run_real("key_containment")

    def test_key_equality(self):
        self.run_real("key_equality")

    def test_xtream_prefix(self):
        self.run_real("xtream_prefix")

    def test_root_route(self):
        self.run_real("root_route")

    def test_two_carriers_in_one_token(self):
        self.run_real("two_carriers")

    def test_control_userinfo_rule_disabled_is_caught(self):
        self.run_control("userinfo")

    def test_control_containment_rule_disabled_is_caught(self):
        self.run_control("key_containment")

    def test_control_equality_rule_disabled_is_caught(self):
        self.run_control("key_equality")

    def test_control_prefix_rule_disabled_is_caught(self):
        self.run_control("xtream_prefix")

    def test_control_root_rule_disabled_is_caught(self):
        self.run_control("root_route")

    def test_control_two_carriers_with_userinfo_disabled_is_caught(self):
        self.run_control("two_carriers")

    def test_the_meta_assertion_fires_on_an_empty_generator(self):
        with self.assertRaises(Vacuous):
            check_class(st.just("plain text"), scrub_text, minimum=1)


class MutantWitnesses(SimpleTestCase):
    """One fixed input per wrong edit the property tests alone could miss."""

    CASES = {
        # rfind("@") -> find("@"): the part after the first "@" of the userinfo survives.
        "userinfo with a later @": f"http://u:x@y:{SENT}@h.invalid/",
        # case-sensitive prefix match.
        "upper-case Xtream prefix": f"/LIVE/user/{SENT}/1.ts",
        "mixed-case Xtream prefix": f"h.invalid/Movie/{SENT}/p/1.ts",
        # equality rule without .strip(): the percent-decoded name is padded.
        "padded equality name": f"?%20code={SENT}",
        "tab-padded equality name": f"/cb?a=1&%09state={SENT}",
        # dropping the userinfo/tail union: a key carrier starts inside the userinfo.
        "key carrier inside the userinfo": f"//{SENT}&token=x@h",
        "password carrier inside the userinfo": f"http://u:{SENT}:password=x@h.invalid/",
        # ASCII-only digit test in the root rule: a non-ASCII digit is a digit.
        "non-ASCII digit stream id": f"/u/{SENT}/\u0663",
    }

    def test_no_sentinel_survives(self):
        for label, text in self.CASES.items():
            with self.subTest(label):
                self.assertNotIn(SENT, scrub_text(text), text)

    def test_the_oracle_removes_what_the_witnesses_expect_removed(self):
        # Where redact_url itself removes the sentinel, the scrubber must too (property (a)).
        for label, text in self.CASES.items():
            with self.subTest(label):
                self.assertFalse(leaks(scrub_text, text), text)

    def test_every_current_key_has_an_equality_or_containment_witness(self):
        for key in sorted(SENSITIVE_QUERY_KEYS):
            for name in _spellings(key):
                self.assertNotIn(SENT, scrub_text(f"?x=1&{name}={SENT}"), name)
