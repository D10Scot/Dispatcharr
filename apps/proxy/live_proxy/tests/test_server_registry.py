"""server.py's channel registry and zombie detection (Gate 2 coverage).

check_if_channel_exists (server.py:881-969) is the relay's answer to "is
this channel real, and is anyone still running it". Every branch is a
decision about Redis state, so every one is reachable by seeding that state
and asking the question over HTTP -- DELETE /proxy/relay/channels/<id>,
whose JSON says which way the answer went.

NOT a matrix row. Ownership leases and cross-worker heartbeats are deleted
outright by spec D2 (the Go relay is one process, ownership is a
map[uuid]*Channel behind a sync.RWMutex), so there is no Go behaviour to
hold to parity here. What survives the port is the requirement these tests
describe: a channel nobody is running must not be reported as running, and
its keys must not outlive it. These tests are deleted with
apps/proxy/live_proxy/ in 2d.
"""

import time
import uuid as uuid_module

import requests

from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .harness.relay import RelayHarnessTestCase


def _signed(method, path, body=b""):
    return {
        HEADER_INTERNAL: internal_principal_token(),
        HEADER_INTERNAL_REQUEST: build_internal_request_header(method, path, body),
    }


# check_if_channel_exists:944 treats a channel in an unrecognised state as
# stale once it has been there longer than this. Read from the code, not
# invented: server.py:944 is `if state_age > 60:`.
STALE_STATE_SECONDS = 60


class ChannelRegistryTests(RelayHarnessTestCase):
    def setUp(self):
        super().setUp()
        self.redis = ProxyServer.get_instance().redis_client
        self.assertIsNotNone(self.redis)
        self.identifier = str(uuid_module.uuid4())
        self.addCleanup(self._drop_keys)

    def _drop_keys(self):
        for key in self.redis.scan_iter(
            match=f"live:channel:{self.identifier}:*", count=500
        ):
            self.redis.delete(key)

    def _seed_metadata(self, **fields):
        self.redis.hset(
            RedisKeys.channel_metadata(self.identifier), mapping=fields
        )

    def _stop(self):
        path = f"/proxy/relay/channels/{self.identifier}"
        response = requests.delete(
            self.live_server_url + path, headers=_signed("DELETE", path), timeout=10
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        return response.json()

    def _metadata_exists(self):
        return bool(self.redis.exists(RedisKeys.channel_metadata(self.identifier)))

    def test_a_channel_whose_owner_still_heartbeats_is_reported_present(self):
        # NOTE the shape of the assertion, and do not add a metadata check
        # here: on the success path stop_channel goes on to run
        # _clean_redis_keys (server.py:1831), which DELETES the hash. A
        # `status: success` and a surviving metadata key are mutually
        # exclusive by construction. previous_state is the field that proves
        # the registry saw the channel, and it comes back in the body.
        worker = f"worker-{uuid_module.uuid4().hex[:8]}"
        heartbeat = RedisKeys.worker_heartbeat(worker)
        self.redis.setex(heartbeat, 30, "1")
        self.addCleanup(self.redis.delete, heartbeat)
        self._seed_metadata(**{
            ChannelMetadataField.STATE: ChannelState.ACTIVE,
            ChannelMetadataField.OWNER: worker,
        })

        result = self._stop()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["previous_state"], {"state": ChannelState.ACTIVE})

    def test_a_channel_whose_owner_stopped_heartbeating_is_cleaned_as_a_zombie(self):
        # No heartbeat key for the named owner: server.py:915-931 calls it a
        # zombie and _clean_zombie_channel deletes its keys.
        self._seed_metadata(**{
            ChannelMetadataField.STATE: ChannelState.ACTIVE,
            ChannelMetadataField.OWNER: "worker-that-died",
        })

        self.assertEqual(self._stop()["status"], "error")
        self.assertFalse(
            self._metadata_exists(), "the zombie's metadata key must be gone"
        )

    def test_a_zombie_with_clients_still_attached_is_cleaned(self):
        # The scard > 0 arm of the same branch (server.py:922-928): the
        # comment there reserves ownership takeover for the future and
        # cleans up "to be safe" today. Pinned as it is, per spec D5.
        self._seed_metadata(**{
            ChannelMetadataField.STATE: ChannelState.ACTIVE,
            ChannelMetadataField.OWNER: "worker-that-died",
        })
        self.redis.sadd(RedisKeys.clients(self.identifier), "client_ghost")

        self.assertEqual(self._stop()["status"], "error")
        self.assertFalse(self._metadata_exists())

    def test_a_channel_in_a_terminal_state_is_reported_absent(self):
        # server.py:932-935: stopped/error mean "clean up and reinitialize",
        # and unlike the zombie branch this one leaves the metadata alone.
        self._seed_metadata(**{
            ChannelMetadataField.STATE: ChannelState.STOPPED,
            ChannelMetadataField.OWNER: "anyone",
        })

        self.assertEqual(self._stop()["status"], "error")

    def test_a_channel_stuck_in_an_unrecognised_state_becomes_a_zombie(self):
        # server.py:936-947. The age is derived from the threshold in the
        # code, never written as a wall-clock literal.
        self._seed_metadata(**{
            ChannelMetadataField.STATE: "a-state-no-constant-defines",
            ChannelMetadataField.STATE_CHANGED_AT: str(
                time.time() - (STALE_STATE_SECONDS + 1)
            ),
        })

        self.assertEqual(self._stop()["status"], "error")
        self.assertFalse(self._metadata_exists())

    def test_a_channel_recently_moved_to_an_unrecognised_state_is_reported_present(self):
        # The other side of the same branch (server.py:949-950): still in
        # progress, so check_if_channel_exists answers True and the stop
        # proceeds. previous_state carries the state it saw -- which is the
        # only thing that distinguishes this from the stale case, since the
        # stop then deletes the hash either way (server.py:1831).
        self._seed_metadata(**{
            ChannelMetadataField.STATE: "a-state-no-constant-defines",
            ChannelMetadataField.STATE_CHANGED_AT: str(time.time()),
        })

        result = self._stop()
        self.assertEqual(result["status"], "success")
        self.assertEqual(
            result["previous_state"], {"state": "a-state-no-constant-defines"}
        )

    def test_orphaned_keys_without_metadata_are_cleaned_up(self):
        # server.py:951-967 -> _clean_redis_keys (:2391-2426). A clients
        # set with no metadata hash is the shape a half-finished teardown
        # leaves behind.
        clients_key = RedisKeys.clients(self.identifier)
        self.redis.sadd(clients_key, "client_orphan")

        self.assertEqual(self._stop()["status"], "error")
        self.assertFalse(self.redis.exists(clients_key))

    def test_an_identifier_nothing_knows_about_is_reported_absent(self):
        self.assertEqual(self._stop()["status"], "error")
