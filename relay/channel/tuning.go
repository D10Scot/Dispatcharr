package channel

import "time"

// Tuning is the channel-start-time settings a channel runs on, already
// resolved from the control plane's proxy_settings into Go types.
//
// A plain struct of durations and ints rather than the wire object, so this
// package never imports the wire package: httpapi resolves proxy_settings once
// per tune and hands the result down, and the ffmpeg source is handed the
// same struct. Every field names its source, because a value with no named
// source is the second copy Amendment A1.4 exists to stop.
//
// SIXTEEN FIELDS, and every one snapshotted at channel start (parity-matrix
// row 5). 2c-5 added the last ten: the failover thresholds
// StreamManager.__init__ reads once (input/manager.py:50-52, :76-78) and the
// three client-loop values 2c-2 deferred to the health flag they are gated
// on (output/ts/generator.py:387-405, :549-551, :583-604). Python reads
// STREAM_TIMEOUT, FAILOVER_GRACE_PERIOD, KEEPALIVE_INTERVAL and
// MAX_KEEPALIVE_DURATION per call rather than once, but they are class
// attributes no running process ever changes, so a start-time snapshot is
// the same value.
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

	// BufferingSpeed is buffering_speed: the ffmpeg-reported speed below
	// which a transcode channel is buffering. Read by TranscodeSource's
	// detector and by nothing on the Proxy path -- parity-matrix row 29,
	// the detector is ffmpeg-exclusive.
	BufferingSpeed float64

	// BufferingTimeout is buffering_timeout: how long buffering may last
	// before the detector gives up on the source.
	BufferingTimeout time.Duration

	// ConnectionTimeout is CONNECTION_TIMEOUT: how long without data before
	// the health monitor marks the stream unhealthy, once the ring holds a
	// chunk (input/manager.py:1547-1551, parity-matrix row 2).
	ConnectionTimeout time.Duration

	// HealthCheckInterval is HEALTH_CHECK_INTERVAL: the health monitor's
	// tick (input/manager.py:78, :1609).
	HealthCheckInterval time.Duration

	// InitGracePeriod is channel_init_grace_period: the inactivity threshold
	// while a connection is up but the ring is still empty
	// (input/manager.py:1549-1550).
	InitGracePeriod time.Duration

	// MaxRetries is MAX_RETRIES: consecutive connection failures before the
	// source is exhausted (input/manager.py:50, :534-537, row 3).
	MaxRetries int

	// RetryWindow is RETRY_WINDOW_SECONDS: a gap since the last failure
	// longer than this resets the counter (input/manager.py:183-193, row 3).
	RetryWindow time.Duration

	// StableThreshold is STABLE_CONNECTION_THRESHOLD: a connection that ran
	// this long resets the switch rotation (input/manager.py:52, :508-513).
	StableThreshold time.Duration

	// MaxStreamSwitches is MAX_STREAM_SWITCHES: the main loop's bound on
	// switches (input/manager.py:388-402), which the buffering path does
	// not consult (row 6).
	MaxStreamSwitches int

	// ClientTimeout is STREAM_TIMEOUT + FAILOVER_GRACE_PERIOD, the sum
	// _is_timeout computes (output/ts/generator.py:585-587): how long a
	// client may go without a yielded chunk on an UNHEALTHY channel before
	// it is dropped.
	ClientTimeout time.Duration

	// KeepaliveInterval is KEEPALIVE_INTERVAL: the gap between keepalive
	// packets sent to a client waiting at the head of an unhealthy channel
	// (output/ts/generator.py:405).
	KeepaliveInterval time.Duration

	// MaxKeepalive is MAX_KEEPALIVE_DURATION: the wall-clock cap on those
	// keepalives before the client is dropped (output/ts/generator.py:
	// 371-380).
	MaxKeepalive time.Duration
}
