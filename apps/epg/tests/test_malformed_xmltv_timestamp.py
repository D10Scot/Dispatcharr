"""#76 (dup #156): a malformed <programme> timestamp must not abort the
byte-offset lookup for the rest of the channel's block, and must not 500
POST /api/epg/programs/current/ for every channel in the request.

#75: an offset written without the separating space before the sign (e.g.
"...183000+0530" instead of "...183000 +0530") is silently read as if no
timezone were present and treated as UTC.
"""

import os
import tempfile
from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.epg.models import EPGData, EPGSource
from apps.epg.tasks import (
    _read_programs_at_offsets,
    _scan_from_offset_for_tvg_id,
    build_programme_index,
    parse_xmltv_time,
)

User = get_user_model()

CURRENT_PROGRAMS_URL = "/api/epg/current-programs/"


def _write_xmltv(xml):
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", encoding="utf-8", delete=False
    ) as f:
        f.write(xml)
        return f.name


class MalformedOffsetLookupTests(TestCase):
    """#76: a +2400 offset (hour out of range for a timezone) 500'd the
    offset-based lookup instead of being skipped like the bulk parser does."""

    def setUp(self):
        self.now = timezone.now()

    def test_malformed_offset_is_skipped_by_offset_lookup_not_raised(self):
        # #76's counterexample: an out-of-range +2400 offset on the first
        # programme of a block, an always-on programme right after it for
        # the same channel, so both land under the one recorded offset.
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <channel id="offset.lookup"/>\n'
            '  <programme start="20260101120000 +2400" '
            'stop="20260101130000 +0000" channel="offset.lookup">\n'
            "    <title>Bad Offset</title>\n"
            "  </programme>\n"
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="offset.lookup">\n'
            "    <title>Always On</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        tmp_path = _write_xmltv(xml)
        try:
            src = EPGSource.objects.create(
                name="Offset Lookup", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            src.refresh_from_db()
            offsets = src.programme_index["channels"]["offset.lookup"]

            result = _read_programs_at_offsets(
                tmp_path, "offset.lookup", offsets, self.now
            )

            self.assertIsNotNone(
                result,
                "the malformed +2400 offset must be skipped, not raised, so "
                "the scan can reach the well-formed programme after it",
            )
            self.assertEqual(result["title"], "Always On")
        finally:
            os.unlink(tmp_path)

    def test_malformed_offset_is_skipped_by_interleaved_scan_not_raised(self):
        # #156's counterexample, +2460, through the interleaved forward
        # scan. A leading programme for a different channel exercises the
        # "skip, don't stop at a boundary" behaviour this helper is for.
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <channel id="other.channel"/>\n'
            '  <channel id="interleaved.scan"/>\n'
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="other.channel">\n'
            "    <title>Other</title>\n"
            "  </programme>\n"
            '  <programme start="20260101120000 +2460" '
            'stop="20260101130000 +0000" channel="interleaved.scan">\n'
            "    <title>Bad Offset</title>\n"
            "  </programme>\n"
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="interleaved.scan">\n'
            "    <title>Always On</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        tmp_path = _write_xmltv(xml)
        try:
            result = _scan_from_offset_for_tvg_id(
                tmp_path, "interleaved.scan", 0, self.now
            )

            self.assertNotEqual(
                result, "timeout", "the scan must not time out on a small file"
            )
            self.assertIsNotNone(
                result,
                "the malformed +2460 offset must be skipped, not raised, so "
                "the scan can reach the well-formed programme after it",
            )
            self.assertEqual(result["title"], "Always On")
        finally:
            os.unlink(tmp_path)

    def test_current_programs_api_does_not_500_on_a_malformed_programme_timestamp(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <channel id="api.channel"/>\n'
            '  <programme start="20260101120000 +2400" '
            'stop="20260101130000 +0000" channel="api.channel">\n'
            "    <title>Bad Offset</title>\n"
            "  </programme>\n"
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="api.channel">\n'
            "    <title>Always On</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        tmp_path = _write_xmltv(xml)
        try:
            src = EPGSource.objects.create(
                name="API Timestamp", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            epg = EPGData.objects.create(
                tvg_id="api.channel", name="API Channel", epg_source=src
            )

            user = User.objects.create_user(
                username="malformed-timestamp-tester", password="testpass123"
            )
            user.user_level = 10
            user.save()
            client = APIClient()
            client.force_authenticate(user=user)

            response = client.post(
                CURRENT_PROGRAMS_URL,
                {"epg_data_ids": [epg.id]},
                format="json",
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_200_OK,
                "a malformed timestamp on one channel must not 500 the "
                "whole multi-channel request",
            )
            self.assertEqual(len(response.data), 1)
            self.assertEqual(response.data[0]["title"], "Always On")
        finally:
            os.unlink(tmp_path)


class AdjacentOffsetXmltvTimestampTests(SimpleTestCase):
    """#75: "20260728183000+0530" (no space before the sign) is read as if
    it carried no timezone at all, and the +0530 offset is dropped."""

    def test_adjacent_positive_offset_is_applied_not_read_as_utc(self):
        result = parse_xmltv_time("20260728183000+0530")
        self.assertEqual(
            result,
            datetime(2026, 7, 28, 13, 0, tzinfo=dt_timezone.utc),
            "the +0530 offset must be applied instead of the timestamp "
            "being read as bare UTC",
        )

    def test_adjacent_negative_offset_is_applied_not_read_as_utc(self):
        result = parse_xmltv_time("20260728183000-0800")
        self.assertEqual(
            result,
            datetime(2026, 7, 29, 2, 30, tzinfo=dt_timezone.utc),
            "the -0800 offset must be applied instead of the timestamp "
            "being read as bare UTC",
        )

    def test_spaced_offset_still_parses_the_same(self):
        # Control: the already-correctly-spaced form must be unaffected.
        result = parse_xmltv_time("20260728183000 +0530")
        self.assertEqual(
            result,
            datetime(2026, 7, 28, 13, 0, tzinfo=dt_timezone.utc),
            "a properly spaced offset must keep parsing the same way",
        )
