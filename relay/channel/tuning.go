package channel

import "time"

// Tuning is the channel-start-time settings a channel runs on, already
// resolved from the control plane's proxy_settings into Go types.
//
// A plain struct of durations and ints rather than the wire object, so this
// package never imports the wire package: httpapi resolves proxy_settings once
// per tune and hands the result down, and 2c-4's ffmpeg source is handed the
// same struct. Every field names its source, because a value with no named
// source is the second copy Amendment A1.4 exists to stop.
//
// THREE FIELDS, NOT SIX. An earlier draft of this struct also carried a client
// timeout, a keepalive interval and a keepalive cap. All three are 2c-5's,
// because in Python all three are gated on a health flag only the failover
// machinery lowers: _should_send_keepalive returns False unless
// stream_manager.healthy is false (output/ts/generator.py:549-551) and
// _is_timeout returns False unless the same flag is false (:592). A channel
// this PR serves is either running or finished, so neither gate ever opens,
// and a field with no reader is a stale duplicate of the truth waiting to
// happen.
type Tuning struct {
	// ChunkBytes is the ring's write unit, from BUFFER_CHUNK_SIZE.
	ChunkBytes int

	// Retention is how far back the ring reaches, from redis_chunk_ttl. The
	// key keeps its Redis-era name on the wire because D5 is strict parity
	// and renaming a settings key is a change the settings UI can see.
	Retention time.Duration

	// JoinBehind is how far behind live a new client starts, from
	// new_client_behind_seconds. Zero means start at the live head, which is
	// what the setting's own 0 means (output/ts/generator.py:296-302).
	JoinBehind time.Duration

	// ShutdownDelay is how long a channel with no clients stays up, from
	// channel_shutdown_delay. 2c-3 supplies it; see the plan's Ruling R4.
	ShutdownDelay time.Duration
}
