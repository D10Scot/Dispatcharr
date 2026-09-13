"""Amendment A1.4: Django sends EFFECTIVE proxy settings.

The stored CoreSettings group, merged over every TSConfig class-attribute
default, so the Go relay holds no second copy of apps/proxy/config.py and
the two cannot drift.
"""

from django.test import TestCase

from apps.proxy.config import TSConfig, class_attribute_defaults
from apps.proxy.next_source import _with_proxy_settings
from apps.proxy.serializers import RelayProxySettingsSerializer

# The seven keys CoreSettings.get_proxy_settings() stores (core/models.py:
# 719-730). Typed here rather than imported so that a key silently
# disappearing from that dict fails this module rather than agreeing with it.
STORED_KEYS = {
    "buffering_timeout",
    "buffering_speed",
    "redis_chunk_ttl",
    "channel_shutdown_delay",
    "channel_init_grace_period",
    "channel_client_wait_period",
    "new_client_behind_seconds",
}


class EnumerationTests(TestCase):
    """A default cannot be added to config.py without appearing on the wire."""

    def test_every_class_attribute_default_is_a_declared_field(self):
        declared = set(RelayProxySettingsSerializer().fields) - STORED_KEYS
        expected = set(class_attribute_defaults())
        missing = expected - declared
        extra = declared - expected
        self.assertEqual(
            declared,
            expected,
            "RelayProxySettingsSerializer and apps/proxy/config.py disagree about "
            "which defaults reach the relay.\n"
            f"  declared but not a TSConfig default: {sorted(extra)}\n"
            f"  a TSConfig default but not declared: {sorted(missing)}\n"
            "Adding a class attribute to TSConfig or BaseConfig means adding a "
            "field here, or the Go relay never learns the value changed.",
        )

    def test_the_seven_stored_keys_are_still_declared(self):
        # The other half of the same field list. Without this, deleting a
        # stored key's field would leave the test above perfectly happy.
        self.assertTrue(
            STORED_KEYS.issubset(set(RelayProxySettingsSerializer().fields)),
            "RelayProxySettingsSerializer dropped one of the stored keys: "
            f"{sorted(STORED_KEYS - set(RelayProxySettingsSerializer().fields))}",
        )

    def test_a_shadowed_class_attribute_does_not_reach_the_wire(self):
        # TSConfig shadows BaseConfig.BUFFERING_TIMEOUT = 15 with a @property
        # (config.py:162), so the live value comes from the buffering_timeout
        # stored key. Walking BaseConfig instead of TSConfig would put a
        # stale 15 on the wire beside it. Asserted by name because it is the
        # one case where the two halves of this contract could contradict
        # each other.
        defaults = class_attribute_defaults()
        for shadowed in (
            "BUFFERING_TIMEOUT",
            "BUFFERING_SPEED",
            "REDIS_CHUNK_TTL",
            "CHANNEL_SHUTDOWN_DELAY",
            "CHANNEL_INIT_GRACE_PERIOD",
            "CHANNEL_CLIENT_WAIT_PERIOD",
        ):
            self.assertNotIn(
                shadowed,
                defaults,
                f"{shadowed} is a property on TSConfig, not a plain default; its "
                "live value is a stored CoreSettings key. Sending the shadowed "
                "class attribute would put a stale number on the wire beside it.",
            )

    def test_a_field_type_matches_its_python_literal(self):
        # A Go client generated against the schema unmarshals by type. A
        # FloatField where the value is an int is harmless; an IntegerField
        # where the value is 0.5 truncates in the schema and lies to the
        # generator.
        fields = RelayProxySettingsSerializer().fields
        for name, value in class_attribute_defaults().items():
            with self.subTest(name=name):
                field = type(fields[name]).__name__
                want = {int: "IntegerField", float: "FloatField", str: "CharField"}[
                    type(value)
                ]
                self.assertEqual(field, want, f"{name} is {value!r}")


class ValueTests(TestCase):
    """The wire carries the effective value, not a placeholder."""

    def setUp(self):
        self.settings = _with_proxy_settings({})["proxy_settings"]

    def test_the_answer_carries_both_halves(self):
        self.assertTrue(STORED_KEYS.issubset(self.settings))
        self.assertTrue(set(class_attribute_defaults()).issubset(self.settings))

    def test_every_default_reaches_the_wire_with_its_class_value(self):
        # This half proves the WIRING -- that the merge did not drop or
        # rename anything -- and nothing more. It cannot prove the VALUES,
        # because it reads TSConfig exactly as the producer does: it would
        # pass if both read the wrong class. The literals below are what
        # carry that, which is why both tests exist.
        for name, value in class_attribute_defaults().items():
            with self.subTest(name=name):
                self.assertEqual(self.settings[name], value)

    def test_three_values_pinned_against_the_source(self):
        # Typed by hand from apps/proxy/config.py, one per Python type, so
        # this test fails if the producer starts reading a different class
        # or a different attribute set. BUFFER_CHUNK_SIZE especially: the
        # Go ring buffer sizes itself from it, and CLAUDE.md records that
        # input/buffer.py:42's fallback of TS_PACKET_SIZE * 5644 is an
        # UNREACHABLE default four times too large -- so the number a
        # careless reader would copy is the wrong one.
        self.assertEqual(self.settings["BUFFER_CHUNK_SIZE"], 255868)  # config.py:15, 188 * 1361
        self.assertEqual(self.settings["STREAM_TIMEOUT"], 20)  # config.py:103
        self.assertEqual(self.settings["GHOST_CLIENT_MULTIPLIER"], 10.0)  # config.py:113

    def test_the_serializer_renders_every_key(self):
        # The producer and the serializer are two lists that must agree.
        # _with_proxy_settings builds the dict and DRF drops anything the
        # serializer does not declare, so a key present in the dict and
        # absent from the fields vanishes between them in silence.
        rendered = RelayProxySettingsSerializer(self.settings).data
        self.assertEqual(set(rendered), set(self.settings))
