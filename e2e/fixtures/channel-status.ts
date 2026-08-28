import type { ApiClient } from './api';
import type { ChannelStatus } from './types';

/**
 * Read `/proxy/ts/status/<channel_id>`.
 *
 * This is G4's primary assertion surface. It is admin-only, so it goes
 * through the `api` fixture rather than `streamClient`.
 *
 * Every `live_proxy` endpoint — this one and `/proxy/ts/stream/<channel_id>`
 * alike — is keyed by the channel's **UUID string**, never its numeric DB
 * id. `channel_status` (`apps/proxy/live_proxy/views.py`) passes the URL
 * segment straight into `ChannelStatus.get_detailed_channel_info`, which
 * reads `RedisKeys.channel_metadata(channel_id)` with no DB lookup and no
 * id/uuid translation — so the same identifier used to open the stream is
 * the only one this endpoint recognises. Passing the numeric id 404s for
 * every channel, always; it is not a race. (The product's own XC playback
 * path confirms UUID is canonical: it resolves a `Channel` and then calls
 * `stream_ts` with `str(channel.uuid)`, never the numeric id.)
 *
 * Use the per-channel form, never the bare collection endpoint: `GET
 * /proxy/ts/status` broadcasts a `channel_stats` WebSocket event as a side
 * effect of being polled, which would perturb any test waiting on the socket.
 */
export async function readChannelStatus(
  api: ApiClient,
  channelUuid: string
): Promise<ChannelStatus> {
  const res = await api.get(`/proxy/ts/status/${channelUuid}`);
  return api.json<ChannelStatus>(res, `channel status for ${channelUuid}`);
}
