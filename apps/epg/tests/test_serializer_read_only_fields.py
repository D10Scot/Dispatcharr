"""EPGSourceSerializer/EPGDataSerializer.read_only_fields live in Meta (#15).

Both serializers declared `read_only_fields` directly in the class body, a
sibling of `class Meta`, where `ModelSerializer` never reads it.

`EPGSourceSerializer` exposed `updated_at` ("last successful refresh") as
writable over the API as a result. `EPGDataSerializer` is served only by
`EPGDataViewSet`, a `ReadOnlyModelViewSet` (`apps/epg/api_views.py`), so its
misplaced `read_only_fields = ["epg_source"]` has no reachable API
consequence today -- checked at the field level instead, so a future PATCH
route added to that viewset would not silently reopen it.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.epg.models import EPGData, EPGSource
from apps.epg.serializers import EPGDataSerializer

User = get_user_model()


class EPGSourceReadOnlyFieldsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="epg-admin", password="testpass123")
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.source = EPGSource.objects.create(name="Read-only fields source", source_type="xmltv")
        self.assertIsNone(self.source.updated_at)

    def test_epg_source_updated_at_is_not_writable_over_the_api(self):
        response = self.client.patch(
            f"/api/epg/sources/{self.source.id}/",
            {"updated_at": "1999-01-02T03:04:05Z"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.source.refresh_from_db()
        self.assertIsNone(
            self.source.updated_at,
            "updated_at was writable over the API despite being declared read-only",
        )


class EPGDataReadOnlyFieldsTests(TestCase):
    def setUp(self):
        self.epg_source = EPGSource.objects.create(name="Owner source", source_type="xmltv")
        self.epg_data = EPGData.objects.create(
            tvg_id="test-tvg", name="Test EPG", epg_source=self.epg_source
        )

    def test_epg_data_epg_source_is_read_only(self):
        self.assertTrue(
            EPGDataSerializer().fields["epg_source"].read_only,
            "EPGDataSerializer.epg_source is not read-only",
        )
