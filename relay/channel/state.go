package channel

// State is a channel's lifecycle state, spelled exactly as
// apps/proxy/live_proxy/constants.py's ChannelState spells it, because these
// strings reach a client through the status endpoints' `state` field and a
// rename is a wire change.
//
// The full Python vocabulary is eight values. Buffering is entered only by
// the ffmpeg stderr reader (2c-4's TranscodeSource; parity-matrix row 29
// pins that the Proxy architecture never enters it) and Stopping by the
// coordinated teardown (2c-8). Connecting is NOT transcode-specific, which
// 2c-2's version of this comment said: input/manager.py:1905-1963 sets it on
// BOTH paths, for the window after a connection is up and before the ring
// holds INITIAL_BEHIND_CHUNKS (4) chunks, and promote_channel_when_buffer_
// ready moves it on. That window is not ported -- promoteOnFirstChunk is the
// one promotion mechanism here and it fires on the first chunk, not the
// fourth -- so Connecting is declared and never entered, and a later PR
// that wants it adds a transition rather than a constant.
type State string

// The eight states. Only Initializing, WaitingForClients, Active, Error and
// Stopped are reachable in 2c-2.
const (
	StateInitializing      State = "initializing"
	StateConnecting        State = "connecting"
	StateWaitingForClients State = "waiting_for_clients"
	StateActive            State = "active"
	StateBuffering         State = "buffering"
	StateError             State = "error"
	StateStopping          State = "stopping"
	StateStopped           State = "stopped"
)
