"""resolve_output_profile never resolves an HLS profile (Phase 4a-1d, spec D12):
an HLS profile is chosen per channel, so a per-client choice of one is ignored."""

from unittest.mock import MagicMock

from django.test import TestCase

from apps.proxy import authorize
from core.models import OutputProfile


def _rows():
    hls, _ = OutputProfile.objects.get_or_create(
        name="HLS (Automatic)",
        defaults={
            "hls_mode": "automatic",
            "command": "ffmpeg",
            "parameters": "(built by the relay)",
            "locked": True,
            "is_active": True,
        },
    )
    OutputProfile.objects.filter(id=hls.id).update(hls_mode="automatic", is_active=True)
    ac3 = OutputProfile.objects.create(
        name="authorize-ac3", command="ffmpeg", parameters="-i pipe:0 -c:a ac3 pipe:1"
    )
    return hls, ac3


class ResolveOutputProfileHlsTests(TestCase):
    def test_an_hls_profile_in_the_query_resolves_to_none(self):
        hls, ac3 = _rows()
        request = MagicMock()
        request.GET = {"output_profile": str(hls.id)}
        self.assertIsNone(authorize.resolve_output_profile(request, user=None))
        request.GET = {"output_profile": str(ac3.id)}
        self.assertEqual(authorize.resolve_output_profile(request, user=None), ac3)

    def test_an_hls_profile_in_custom_properties_resolves_to_none(self):
        hls, ac3 = _rows()
        request = MagicMock()
        request.GET = {}
        user = MagicMock()
        user.custom_properties = {"output_profile": hls.id}
        self.assertIsNone(authorize.resolve_output_profile(request, user=user))
        user.custom_properties = {"output_profile": ac3.id}
        self.assertEqual(authorize.resolve_output_profile(request, user=user), ac3)
