import type { ApiClient } from './api';
import type { ChannelStatus } from './types';

/**
 * Read `/proxy/ts/status/<id>`.
 *
 * This is G4's primary assertion surface. It is admin-only, so it goes
 * through the `api` fixture rather than `streamClient`.
 *
 * Use the per-channel form, never the bare collection endpoint: `GET
 * /proxy/ts/status` broadcasts a `channel_stats` WebSocket event as a side
 * effect of being polled, which would perturb any test waiting on the socket.
 */
export async function readChannelStatus(
  api: ApiClient,
  channelId: number
): Promise<ChannelStatus> {
  const res = await api.get(`/proxy/ts/status/${channelId}`);
  return api.json<ChannelStatus>(res, `channel status for ${channelId}`);
}
