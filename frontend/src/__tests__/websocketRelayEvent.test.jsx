import { describe, expect, it, vi, beforeEach } from 'vitest';
import { handleRelayEvent } from '../WebSocket';
import useChannelsStore from '../store/channels';

describe('handleRelayEvent', () => {
  beforeEach(() => {
    useChannelsStore.setState({ relayEvents: {} });
  });

  it('routes a relay_event payload into the channels store', () => {
    handleRelayEvent({
      type: 'relay_event',
      event: 'channel_failover',
      channel_id: 'uuid-a',
      stream_id: 7,
      reason: 'dead_air',
      timestamp: 1234,
    });

    expect(useChannelsStore.getState().relayEvents['uuid-a']).toEqual({
      event: 'channel_failover',
      streamId: 7,
      clientId: null,
      reason: 'dead_air',
      timestamp: 1234,
    });
  });

  it('ignores a payload with no channel id rather than throwing', () => {
    const spy = vi.spyOn(useChannelsStore.getState(), 'applyRelayEvent');
    handleRelayEvent({ type: 'relay_event', event: 'stream_switch' });
    expect(spy).toHaveBeenCalled();
    expect(useChannelsStore.getState().relayEvents).toEqual({});
  });
});
