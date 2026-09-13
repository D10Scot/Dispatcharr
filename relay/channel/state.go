package channel

// State is a channel's lifecycle state, spelled exactly as
// apps/proxy/live_proxy/constants.py's ChannelState spells it, because these
// strings reach a client through the status endpoints' `state` field and a
// rename is a wire change.
//
// The full Python vocabulary is eight values. Four of them belong to
// behaviour later PRs bring: Connecting is set by the transcode path
// (2c-4), Buffering only ever by the ffmpeg stderr reader (2c-4, and
// parity-matrix row 29 pins that the Proxy architecture never enters it),
// and Stopping by the coordinated teardown (2c-8). They are declared here
// anyway, so that the vocabulary has one home and a later PR adds a
// transition rather than a constant.
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
