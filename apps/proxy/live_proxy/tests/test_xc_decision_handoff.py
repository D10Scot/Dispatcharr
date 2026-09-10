"""stream_xc authorizes once and hands its decision to stream_ts (row 15).

The observable consequence, and the only one: the XC credentials live in
the URL path segments, which SURFACE_LIVE never reads. A second hop under
SURFACE_LIVE would therefore resolve anonymous -- and anonymous is refused a
channel marked hidden_from_output (authorize.py:386-389). So an ADMIN XC
user tuning a HIDDEN channel over the XC live root is 200 with the hand-off
and 403 without it.

The row's second clause -- "does not mint a second client id" -- has no
externally observable consequence: stream_ts registers exactly one client
either way, and a discarded extra mint_client_id() call is invisible on the
wire. It is recorded here rather than asserted, because a test that appeared
to assert it would pass whether or not the hand-off existed.
"""

import requests

from apps.accounts.models import User

from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase


XC_USERNAME = "row15-xc-admin"
XC_PASSWORD = "row15-xc-secret"


class XcDecisionHandoffTests(RelayHarnessTestCase):
    def test_an_xc_tune_is_not_re_authorized_as_an_anonymous_live_tune(self):
        User.objects.create_user(
            username=XC_USERNAME,
            password="x",
            user_level=User.UserLevel.ADMIN,
            custom_properties={"xc_password": XC_PASSWORD},
        )
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            channel.hidden_from_output = True
            channel.save(update_fields=["hidden_from_output"])

            # The XC live root addresses a channel by its NUMERIC id, and
            # the extension only chooses the output format
            # (authorize_views.py:176-183, views.py:821-822).
            url = (
                f"{self.live_server_url}"
                f"/live/{XC_USERNAME}/{XC_PASSWORD}/{channel.id}.ts"
            )
            response = requests.get(url, stream=True, timeout=20)
            self.addCleanup(response.close)

            # Only a non-200 has a body worth reading: a live 200 never ends.
            if response.status_code != 200:
                self.fail(
                    "the XC tune was re-authorized as an anonymous live tune: "
                    f"{response.status_code} {response.text[:200]}"
                )

            received = b""
            for chunk in response.iter_content(chunk_size=4096):
                received += chunk
                if len(received) >= 20 * 188:
                    break
            self.assertGreaterEqual(len(received), 20 * 188)
            self.assertEqual(received[0], 0x47, "the first byte is a TS sync byte")

        self.stop_channel(channel)
