"""The provider-slot reconciler's beat entry (#513).

Here rather than beside the reconciler's own tests because it pins
dispatcharr/settings.py and core/tasks.py, whose edits select core.tests.
"""

from django.conf import settings
from django.test import SimpleTestCase

from apps.proxy import slot_reconciler
from core.tasks import reconcile_provider_slots


class ReconcileProviderSlotsBeatEntryTests(SimpleTestCase):
    def test_the_beat_entry_names_the_task_on_a_tick_shorter_than_the_spacing_floor(self):
        entry = settings.CELERY_BEAT_SCHEDULE["reconcile-provider-slots"]
        self.assertEqual(entry["task"], reconcile_provider_slots.name)
        # The tick bounds how late a run starts; the reconciler enforces the
        # spacing itself, so the tick must be shorter than the spacing's floor.
        self.assertLess(entry["schedule"], slot_reconciler.MIN_SPACING_SECONDS)
