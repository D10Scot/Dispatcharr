"""ChannelState.PRE_ACTIVE contains the correct states and is immutable.

This file used to carry two halves. The other one, StreamManagerFinallyBlockTests,
drove StreamManager.run()'s finally block and asserted the arbitration between
two uWSGI workers -- which worker holds the owner key, whether a new owner took
over, whether the state guard writes ERROR. Phase 2 stage 2d-4 deleted it with
apps/proxy/live_proxy/: spec D2 gives the Go relay one process and no ownership
lease at all, so there is nothing left to arbitrate. The state OUTCOMES it
asserted are pinned on the Go side by
relay/channel/manager_test.go::TestAnUpstreamFailurePutsTheChannelInError and
relay/channel/failover_test.go::TestAnExhaustedChannelEndsInErrorNamingTheCount,
which is the direct analogue of its test_error_message_includes_stream_count.
There is no Go analogue of the lease half and there cannot be one.

What survives is a shape pin on a constant stage 2d-1 relocated into
apps/proxy/constants.py. Its last production reader went with the package, so
this is deliberately a pin on a constant nothing currently reads -- kept rather
than deleted with it, because the frozenset is four lines and re-deriving it
for Phase 3 would cost more than carrying it. Recorded in the 2d-4 plan's
ruling R7 so it is a decision rather than an oversight.
"""
from django.test import TestCase

from apps.proxy.constants import ChannelState


class PreActiveStateTests(TestCase):
    """Verify PRE_ACTIVE contains the correct states and is immutable."""

    def test_initializing_in_pre_active(self):
        self.assertIn(ChannelState.INITIALIZING, ChannelState.PRE_ACTIVE)

    def test_connecting_in_pre_active(self):
        self.assertIn(ChannelState.CONNECTING, ChannelState.PRE_ACTIVE)

    def test_buffering_in_pre_active(self):
        self.assertIn(ChannelState.BUFFERING, ChannelState.PRE_ACTIVE)

    def test_waiting_for_clients_in_pre_active(self):
        self.assertIn(ChannelState.WAITING_FOR_CLIENTS, ChannelState.PRE_ACTIVE)

    def test_active_not_in_pre_active(self):
        self.assertNotIn(ChannelState.ACTIVE, ChannelState.PRE_ACTIVE)

    def test_error_not_in_pre_active(self):
        self.assertNotIn(ChannelState.ERROR, ChannelState.PRE_ACTIVE)

    def test_pre_active_is_frozenset(self):
        self.assertIsInstance(ChannelState.PRE_ACTIVE, frozenset)
