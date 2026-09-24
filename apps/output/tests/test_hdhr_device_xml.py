"""device.xml reads the configured HDHRDevice row.

#83 - HDHRDeviceXMLAPIView.get (apps/hdhr/api_views.py) hardcoded
<DeviceID>12345678</DeviceID> and <FriendlyName>Dispatcharr HDHomeRun</FriendlyName>
unconditionally, while DiscoverAPIView.get read HDHRDevice.objects.first() and
preferred its fields when a row exists. A configured HDHRDevice row made the
two documents permanently disagree about the device's own identity.
device.xml now reads the same row and the same two fields, XML-escaping the
admin-editable friendly_name, and falls back to the old literals when no row
exists.
"""

import xml.etree.ElementTree as ET

from django.test import Client, TestCase

from apps.hdhr.models import HDHRDevice


class HDHRDeviceXMLTests(TestCase):
    def setUp(self):
        self.client = Client(REMOTE_ADDR="127.0.0.1")

    def test_device_xml_ignored_a_configured_hdhr_device_row(self):
        HDHRDevice.objects.create(
            friendly_name="Den <Tuner> & Co", device_id="ABCD1234"
        )

        xml_res = self.client.get("/hdhr/device.xml")
        self.assertEqual(xml_res.status_code, 200)
        body = xml_res.content.decode()

        # Parse first: an unescaped '<' or '&' in friendly_name makes this
        # raise ET.ParseError before either assertIn below runs, which is
        # what break-check A (dropping escape()) is expected to trip.
        root = ET.fromstring(body)

        self.assertIn("<DeviceID>ABCD1234</DeviceID>", body)
        self.assertIn(
            "<FriendlyName>Den &lt;Tuner&gt; &amp; Co</FriendlyName>", body
        )

        xml_device_id = root.findtext("DeviceID")
        xml_friendly_name = root.findtext("FriendlyName")
        self.assertEqual(xml_device_id, "ABCD1234")
        self.assertEqual(xml_friendly_name, "Den <Tuner> & Co")

        discover_res = self.client.get("/hdhr/discover.json")
        self.assertEqual(discover_res.status_code, 200)
        discover = discover_res.json()

        self.assertEqual(discover["DeviceID"], xml_device_id)
        self.assertEqual(discover["FriendlyName"], xml_friendly_name)

    def test_device_xml_without_a_device_row_keeps_the_default_identity(self):
        self.assertFalse(HDHRDevice.objects.exists())

        xml_res = self.client.get("/hdhr/device.xml")
        self.assertEqual(xml_res.status_code, 200)
        body = xml_res.content.decode()

        self.assertIn("<DeviceID>12345678</DeviceID>", body)
        self.assertIn(
            "<FriendlyName>Dispatcharr HDHomeRun</FriendlyName>", body
        )
