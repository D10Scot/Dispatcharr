"""Tests of the zero-ORM scanner itself.

The guard in test_zero_orm_reads.py is only as good as this file. Issue
#253 records that the spec's prescribed grep fails in BOTH directions --
it misses a real read behind a method call, and it counts a docstring
that quotes the ORM line it replaced. Each direction is pinned here on a
synthetic source, so the pin survives the tree moving underneath it.
"""

import textwrap
from django.test import SimpleTestCase

from . import zero_orm_scan


class ScannerShapeTests(SimpleTestCase):
    def _scan(self, source, path="apps/proxy/live_proxy/fake.py"):
        return zero_orm_scan.scan_source(
            textwrap.dedent(source), path, zero_orm_scan.model_method_names()
        )

    def test_a_model_method_call_is_seen_though_its_call_line_names_no_orm(self):
        """Issue #253's under-count: the shape a grep cannot see.

        get_stream_profile is defined on apps/channels/models.py's Channel
        and Stream and reaches StreamProfile.objects.get (models.py:467).
        Its call line contains neither `.objects.` nor `get_object_or_404(`.
        """
        hits = self._scan(
            """
            def tune(channel):
                return channel.get_stream_profile()
            """
        )
        self.assertEqual(
            [(h.lineno, h.shape, h.symbol) for h in hits],
            [(3, "model_method", "get_stream_profile")],
        )

    def test_a_docstring_quoting_an_orm_line_is_not_a_hit(self):
        """Issue #253's over-count, and the more insidious of the two.

        The cheapest way to silence a line-based grep here is to stop
        quoting the old code in the docstring -- making the codebase less
        legible to satisfy a check. `ast` sees a docstring as a Constant
        and never as an Attribute, so the shape simply does not arise.
        """
        hits = self._scan(
            '''
            def resolve(identifier):
                """Phase 1 PR 6 moved this.

                Was: StreamProfile.objects.get(name="ffmpeg", locked=True)
                and get_object_or_404(Stream.objects.all(), pk=identifier).
                """
                return None
            '''
        )
        self.assertEqual(hits, [])

    def test_a_real_objects_attribute_is_a_hit_in_the_same_file(self):
        """The discriminating half of the test above.

        Without this, `test_a_docstring...` passes with a scanner that
        sees nothing at all -- Global Constraint 3.
        """
        hits = self._scan(
            """
            from apps.channels.models import Stream

            def resolve(pk):
                return Stream.objects.filter(id=pk).first()
            """
        )
        self.assertEqual([(h.lineno, h.shape) for h in hits], [(5, "objects")])

    def test_get_object_or_404_is_a_hit(self):
        hits = self._scan(
            """
            def resolve(pk):
                return get_object_or_404(Channel, pk=pk)
            """
        )
        self.assertEqual([(h.lineno, h.shape) for h in hits], [(3, "shortcut")])

    def test_a_stoplisted_name_is_not_a_hit(self):
        """`update` is a StreamProfile method name AND dict.update.

        Measured at 93900a6f: 8 hits in live_proxy, all dict.update().
        The stoplist is how the model-method rule stays usable; this test
        is what stops it growing silently.
        """
        self.assertIn("update", zero_orm_scan.model_method_names())
        hits = self._scan(
            """
            def build(mapping, extra):
                mapping.update(extra)
                return mapping
            """
        )
        self.assertEqual(hits, [])
        self.assertEqual(
            sorted(zero_orm_scan._NAMES_TOO_GENERIC),
            ["update"],
            "the stoplist grew -- every entry costs the guard a shape it "
            "can no longer see, so each needs its own comment and this "
            "assertion updated deliberately",
        )
