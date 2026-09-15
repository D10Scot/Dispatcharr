package control

import (
	"context"
	"encoding/json"
	"fmt"
)

// ReleaseRequest is the body of POST /api/relay/channels/<id>/release,
// apps/proxy/serializers.py's ReleaseRequestSerializer: three optional
// integers, every one of which apps/proxy/control_plane.py:236-240's
// release_source sends as an explicit key, null when unknown. Pointers
// without omitempty reproduce that: the key is always on the wire.
//
// stream_id and m3u_profile_id are what Django's release_source falls back
// to for a channel deleted mid-playback (apps/proxy/next_source.py:961-1011);
// the Python relay reads them out of its own metadata hash
// (live_proxy/server.py:2364-2367) and this relay reads them off the channel's
// SourceInfo. channel_pk is the Channel's numeric primary key, which is on no
// contract field, so this relay never sends it -- the Python relay's normal
// stop path sends it from the hash, and Django uses it only in that same
// deleted-channel fallback, to delete a key it would otherwise leave behind
// (CLAUDE.md § Known defects, #190). Recorded as a stated divergence.
type ReleaseRequest struct {
	StreamID     *int `json:"stream_id"`
	M3UProfileID *int `json:"m3u_profile_id"`
	ChannelPK    *int `json:"channel_pk"`
}

// Release gives a reserved provider slot back. It returns Django's own
// `released` flag, and the same error classes NextSource returns: a Refused
// for a 4xx, an Unavailable for an outage. There is no 404 mapping here --
// control_plane.release_source has none either: a release for an unknown
// identifier is a refusal the caller logs and moves on from
// (live_proxy/server.py:2374-2385).
func (c *Client) Release(ctx context.Context, identifier string, req ReleaseRequest) (bool, error) {
	path := "/api/relay/channels/" + identifier + "/release"
	body, err := json.Marshal(req)
	if err != nil {
		return false, fmt.Errorf("encoding the release request: %w", err) // credential-logging: ok - encoding/json reports a TYPE it cannot encode, never a field's value
	}
	raw, _, err := c.post(ctx, path, body)
	if err != nil {
		return false, err
	}
	var answer struct {
		Released bool `json:"released"`
	}
	if err := json.Unmarshal(raw, &answer); err != nil {
		return false, &Unavailable{Path: path, Reason: "2xx body did not decode as a release answer", Err: err}
	}
	return answer.Released, nil
}
