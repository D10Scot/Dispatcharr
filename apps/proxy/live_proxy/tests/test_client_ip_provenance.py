"""Where ip_address in the status payload comes from (parity-matrix row 17).

stream_ts resolves the address once (views.py:195) and hands it to
add_client; the row's invariant is that what lands on the wire is the real
client's address. Asserted as a value, never as a mechanism: 2b-2 changes
the source to X-Relay-Client-IP and this test must survive that.

REMOTE_ADDR is 127.0.0.1 under LiveServerTestCase, which get_client_ip
treats as a trusted proxy (dispatcharr/utils.py:342-370, LOCAL_NETWORK_CIDRS),
so a forwarded header is honoured here exactly as it is behind nginx.
"""

import requests

from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)

from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until


def _signed(method, path, body=b""):
    return {
        HEADER_INTERNAL: internal_principal_token(),
        HEADER_INTERNAL_REQUEST: build_internal_request_header(method, path, body),
    }


FORWARDED_CLIENT = "203.0.113.9"  # TEST-NET-3, RFC 5737: never routable, never local


class ClientIpProvenanceTests(RelayHarnessTestCase):
    def test_ip_address_is_the_real_client_address_on_both_status_endpoints(self):
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            identifier = str(channel.uuid)

            # The first client holds the channel open for the whole test.
            with self.tuned(channel) as first:
                first.read(20 * 188)

                # The second client joins the running channel: no second
                # initialization, no second spawn.
                second = requests.get(
                    f"{self.live_server_url}/proxy/ts/stream/{identifier}",
                    headers={"X-Forwarded-For": FORWARDED_CLIENT},
                    stream=True,
                    timeout=20,
                )
                self.addCleanup(second.close)
                self.assertEqual(second.status_code, 200)
                # Pull one chunk so registration has certainly happened
                # before the status read; never format response.text on a
                # live 200 -- the body does not end.
                next(second.iter_content(chunk_size=188))

                detail_path = f"/proxy/relay/channels/{identifier}"

                def two_clients():
                    payload = requests.get(
                        self.live_server_url + detail_path,
                        headers=_signed("GET", detail_path),
                        timeout=10,
                    ).json()
                    return len(payload.get("clients", [])) >= 2

                wait_until(two_clients, timeout=10, what="both clients registered")

                detail = requests.get(
                    self.live_server_url + detail_path,
                    headers=_signed("GET", detail_path),
                    timeout=10,
                ).json()
                addresses = sorted(c["ip_address"] for c in detail["clients"])
                self.assertEqual(addresses, ["127.0.0.1", FORWARDED_CLIENT])

                list_path = "/proxy/relay/channels?clients=all"
                rows = requests.get(
                    self.live_server_url + list_path,
                    headers=_signed("GET", list_path),
                    timeout=10,
                ).json()["channels"]
                row = next(r for r in rows if r["channel_id"] == identifier)
                self.assertEqual(
                    sorted(c["ip_address"] for c in row["clients"]),
                    ["127.0.0.1", FORWARDED_CLIENT],
                )

            self.stop_channel(channel)
