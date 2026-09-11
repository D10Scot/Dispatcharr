"""server.py's Redis event listener loop (Gate 2 coverage).

The listener (server.py:173-470) is the relay's inter-worker interface: a
daemon thread psubscribed to live:events:*, acting on each event only when
this worker owns the channel (the guard at :245, which every branch sits
under). Tests reach it by owning the channel and publishing the payload
another worker would publish -- the shapes ChannelService._publish_*
(services/channel_service.py:942-1013) put on that channel, mirrored rather
than invented.

NOT a matrix row. Spec D2 deletes the multi-worker protocol outright: the Go
relay is one process, so there is no second worker to hear from. What ports
is the requirement, not the mechanism -- an admin's stop must reach the
worker serving the stream. These tests are deleted with
apps/proxy/live_proxy/ in 2d.

The listener runs on its own OS thread, so every assertion here is a
wait_until on an observable, never a sleep.
"""

import json
import uuid as uuid_module

import requests

from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)
from apps.proxy.live_proxy.constants import (
    ChannelMetadataField,
    ChannelState,
    EventType,
)
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until


def _signed(method, path, body=b""):
    return {
        HEADER_INTERNAL: internal_principal_token(),
        HEADER_INTERNAL_REQUEST: build_internal_request_header(method, path, body),
    }


class EventListenerTests(RelayHarnessTestCase):
    """Events on a channel this worker owns, published as another worker."""

    def setUp(self):
        super().setUp()
        self.server = ProxyServer.get_instance()
        self.redis = self.server.redis_client
        self.assertIsNotNone(self.redis)
        self.identifier = str(uuid_module.uuid4())
        self.addCleanup(self._drop_keys)

        # Own the channel, and give the owner a heartbeat so
        # check_if_channel_exists calls it present rather than a zombie.
        self.heartbeat = RedisKeys.worker_heartbeat(self.server.worker_id)
        self.redis.setex(self.heartbeat, 60, "1")
        self.addCleanup(self.redis.delete, self.heartbeat)
        self.redis.setex(
            RedisKeys.channel_owner(self.identifier), 60, self.server.worker_id
        )
        self.redis.hset(
            RedisKeys.channel_metadata(self.identifier),
            mapping={
                ChannelMetadataField.STATE: ChannelState.ACTIVE,
                ChannelMetadataField.OWNER: self.server.worker_id,
            },
        )

    def _drop_keys(self):
        for key in self.redis.scan_iter(
            match=f"live:channel:{self.identifier}:*", count=500
        ):
            self.redis.delete(key)

    def _publish(self, payload):
        self.redis.publish(
            RedisKeys.events_channel(self.identifier), json.dumps(payload)
        )

    def test_the_admin_stop_route_publishes_when_the_client_is_not_local(self):
        """The HTTP half, and ONLY the HTTP half.

        This test deliberately does NOT wait for the stop key, and an earlier
        draft of this plan did: stop_client sets that key ITSELF, first thing
        (services/channel_service.py:647-651), before it checks the channel
        exists and long before it publishes anything. A wait_until on the key
        therefore passes with the event listener dead, which makes it a test
        of nothing. The listener's own branch is asserted below, by a route
        that cannot be satisfied any other way.
        """
        client_id = "client_on_some_other_worker"
        path = f"/proxy/relay/channels/{self.identifier}/clients/{client_id}"
        response = requests.delete(
            self.live_server_url + path, headers=_signed("DELETE", path), timeout=10
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        body = response.json()
        self.assertTrue(body["event_published"])
        self.assertFalse(body["locally_processed"])
        self.assertTrue(body["stop_key_set"])

    def test_a_client_stop_event_from_another_worker_sets_the_clients_stop_key(self):
        """The listener's CLIENT_STOP branch (server.py:402-419).

        Published directly rather than through the admin route, and that is
        the point: the route sets the stop key itself before publishing, so
        only an event that arrives WITHOUT the route running can prove the
        listener set it. The payload mirrors
        ChannelService._publish_client_stop_event (:992-1013) exactly; a
        second relay worker puts precisely this on the channel.
        """
        client_id = "client_only_the_listener_can_stop"
        stop_key = RedisKeys.client_stop(self.identifier, client_id)
        self.assertFalse(
            self.redis.exists(stop_key), "the key must not exist before the event"
        )

        self._publish({
            "event": EventType.CLIENT_STOP,
            "channel_id": self.identifier,
            "client_id": client_id,
            "requester_worker_id": "some-other-worker",
        })

        wait_until(
            lambda: bool(self.redis.exists(stop_key)),
            timeout=10,
            what="the listener to set the client's stop key",
        )

    def test_a_channel_stop_event_from_another_worker_is_acknowledged(self):
        pubsub = self.redis.pubsub()
        pubsub.subscribe(RedisKeys.events_channel(self.identifier))
        self.addCleanup(pubsub.close)

        self._publish({
            "event": EventType.CHANNEL_STOP,
            "channel_id": self.identifier,
            "requester_worker_id": "some-other-worker",
        })

        seen = []

        def acknowledged():
            message = pubsub.get_message(timeout=0.1)
            while message is not None:
                if message.get("type") == "message":
                    try:
                        seen.append(json.loads(message["data"]))
                    except (TypeError, ValueError):
                        pass
                message = pubsub.get_message(timeout=0.0)
            return any(
                event.get("event") == EventType.CHANNEL_STOPPED
                and event.get("worker_id") == self.server.worker_id
                for event in seen
            )

        wait_until(
            acknowledged,
            timeout=10,
            what="a channel_stopped acknowledgement from this worker",
        )

    def test_a_malformed_event_payload_does_not_kill_the_listener(self):
        # server.py:432-433 catches per-message, so the listener survives a
        # payload it cannot parse. Proven by the NEXT event still working --
        # a test that only published garbage would prove nothing.
        self.redis.publish(
            RedisKeys.events_channel(self.identifier), b"this is not json"
        )

        client_id = "client_after_garbage"
        self._publish({
            "event": EventType.CLIENT_STOP,
            "channel_id": self.identifier,
            "client_id": client_id,
            "requester_worker_id": "some-other-worker",
        })

        stop_key = RedisKeys.client_stop(self.identifier, client_id)
        wait_until(
            lambda: bool(self.redis.exists(stop_key)),
            timeout=10,
            what="the listener to keep working after a malformed payload",
        )


class StreamSwitchEventTests(RelayHarnessTestCase):
    """The listener's largest branch (server.py:262-357), which needs a live
    StreamManager and is therefore this task's one tune."""

    def test_a_stream_switch_event_from_another_worker_switches_the_channel(self):
        server = ProxyServer.get_instance()
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            identifier = str(channel.uuid)
            detail_path = f"/proxy/relay/channels/{identifier}"

            with self.tuned(channel) as stream:
                stream.read(20 * 188)

                # A URL the same fake upstream also serves, so the switch
                # can actually connect. FakeUpstream.url is the canonical
                # one; a query string makes it a different URL without
                # making it a different server.
                new_url = f"{self.upstream.url}?switched=1"
                server.redis_client.publish(
                    RedisKeys.events_channel(identifier),
                    json.dumps({
                        "event": EventType.STREAM_SWITCH,
                        "channel_id": identifier,
                        "url": new_url,
                        "user_agent": "harness",
                        "stream_id": None,
                        "m3u_profile_id": None,
                        "stream_name": None,
                        "requester": "some-other-worker",
                    }),
                )

                def switched():
                    payload = requests.get(
                        self.live_server_url + detail_path,
                        headers=_signed("GET", detail_path),
                        timeout=10,
                    ).json()
                    return payload.get("url") == new_url

                wait_until(
                    switched,
                    timeout=15,
                    what="the status endpoint to report the switched URL",
                )

                # The listener records the outcome for whoever asked
                # (server.py:330-332).
                status_key = RedisKeys.switch_status(identifier)
                self.assertEqual(server.redis_client.get(status_key), "switched")

                # The same URL again: server.py:296-300 treats that as a
                # success without asking the manager to reconnect.
                server.redis_client.delete(status_key)
                server.redis_client.publish(
                    RedisKeys.events_channel(identifier),
                    json.dumps({
                        "event": EventType.STREAM_SWITCH,
                        "channel_id": identifier,
                        "url": new_url,
                        "requester": "some-other-worker",
                    }),
                )
                wait_until(
                    lambda: server.redis_client.get(status_key) == "switched",
                    timeout=15,
                    what="the same-URL switch to be recorded as switched",
                )

            self.stop_channel(channel)

    def test_a_stream_switch_event_carries_channel_name_and_m3u_profile_name_into_metadata(self):
        """PIN. pr-review bot finding, verified and confirmed blocking: this
        is the consuming end of the follower-branch fix. A follower worker's
        change_stream_url now publishes channel_name/m3u_profile_name on the
        STREAM_SWITCH event (see test_stream_switch.py's
        test_pubsub_event_carries_channel_name_and_m3u_profile_name for the
        publish side); this test proves the owner's listener actually reads
        them back off the event and writes them into the metadata hash,
        rather than the event carrying them for nothing. Every existing test
        in this class omits both fields from the published payload, so none
        of them could distinguish "threaded" from "never wired up" on this
        end."""
        server = ProxyServer.get_instance()
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            identifier = str(channel.uuid)

            with self.tuned(channel) as stream:
                stream.read(20 * 188)

                new_url = f"{self.upstream.url}?switched=names"
                server.redis_client.publish(
                    RedisKeys.events_channel(identifier),
                    json.dumps({
                        "event": EventType.STREAM_SWITCH,
                        "channel_id": identifier,
                        "url": new_url,
                        "user_agent": "harness",
                        "stream_id": None,
                        "m3u_profile_id": None,
                        "stream_name": None,
                        "channel_name": "Real Listener Channel Name",
                        "m3u_profile_name": "Real Listener Profile Name",
                        "requester": "some-other-worker",
                    }),
                )

                metadata_key = RedisKeys.channel_metadata(identifier)

                wait_until(
                    lambda: server.redis_client.hget(
                        metadata_key, ChannelMetadataField.CHANNEL_NAME
                    ) == "Real Listener Channel Name",
                    timeout=15,
                    what="the listener to write channel_name from the event into the metadata hash",
                )
                self.assertEqual(
                    server.redis_client.hget(
                        metadata_key, ChannelMetadataField.M3U_PROFILE_NAME
                    ),
                    "Real Listener Profile Name",
                )

            self.stop_channel(channel)
