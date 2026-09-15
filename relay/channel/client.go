package channel

import "time"

// Client is one reader attached to a channel.
//
// IN PROCESS MEMORY, which is the whole of what spec D2's "Client registry"
// key-family row buys: live:channel:{id}:clients (a SET with a TTL),
// live:channel:{id}:clients:{cid} (a hash with the same TTL), the per-channel
// heartbeat thread that refreshed both, and ClientManager.remove_ghost_clients
// are DELETED rather than ported.
//
// WHY THE TTL AND THE GHOST SWEEP DISSOLVE, stated because it is the one place
// a reviewer could reasonably expect a port. Those three mechanisms exist for
// one failure: a uWSGI worker dies holding clients, and its Redis keys outlive
// it, so a SET entry with no live reader has to be swept
// (client_manager.py:446-482) and a hash with no heartbeat has to expire
// (CLIENT_RECORD_TTL, apps/proxy/config.py:110). With one relay process and
// the registry in its own memory, a client entry cannot outlive the goroutine
// that made it: serveClient's deferred release runs on every return path
// including a panic, and if the process dies there is no registry left to
// sweep. A TTL here would be a timer with nothing to catch.
//
// WHAT DOES NOT DISSOLVE and is 2c-5's: a client whose TCP peer vanished with
// no FIN is held until its socket write fails or the kernel gives up. Python
// holds such a client just as long -- its heartbeat thread refreshes the TTL
// for every id in self.clients regardless of whether that client is making
// progress ("Only refresh TTL - do NOT update last_active",
// client_manager.py:143), and last_active is refreshed by the client's own
// yield path (output/ts/generator.py:517), so the ghost sweep never fires for
// a locally-attached client either. The behaviours match; neither disconnects
// such a client, and _is_timeout is gated on a health flag only 2c-5 lowers.
type Client struct {
	// ID is the client id, from X-Relay-Client when the authorize hop set
	// it, minted here otherwise. Unique per channel: a second attach with an
	// id already registered is refused, which is client_manager.py:218-221's
	// _registered_clients guard (parity-matrix row 13, first half).
	ID string

	// UserID is the X-Relay-User string, or "0". A STRING on the wire, not
	// an int: RelayChannelClientSerializer declares CharField
	// (apps/proxy/relay_serializers.py:31) and relay_client.live_connections
	// int()s it itself (apps/proxy/relay_client.py:274).
	UserID string

	// IPAddress is the viewer's address, from X-Relay-Client-IP when the hop
	// resolved it (parity-matrix row 17), the peer address otherwise.
	IPAddress string

	// UserAgent is the viewer's User-Agent, or "unknown"
	// (client_manager.py:236).
	UserAgent string

	// OutputFormat is what this relay is actually serving. Always "mpegts"
	// in 2c-3: a tune asking for anything else is refused 501 rather than
	// served MPEG-TS under a format label that is not true.
	OutputFormat string

	// OutputProfileID is nil in 2c-3. Always PRESENT on the wire, as null --
	// channel_status.py:579-582 sets the key on both branches, so it is the
	// one client field that is never absent.
	OutputProfileID *int

	// ConnectedAt is when the client attached.
	ConnectedAt time.Time

	// meter is this client's transfer counters (clientstats.go), installed
	// by addClient and shared with every value copy ClientSnapshot hands
	// out. Unexported so nothing outside this package can build a Client
	// that reports counters nobody is writing.
	meter *clientMeter

	// stop is closed by StopClient: the in-memory form of
	// live:channel:{id}:clients:{cid}:stop, the key
	// ChannelService.stop_client SETEXes and the generator's loop polls
	// (services/channel_service.py:665-673). Installed by addClient, so a
	// Client that was never registered has a nil channel and Stopped()
	// blocks for ever -- which is the correct answer for a client nothing
	// can stop.
	stop chan struct{}
}

// Stopped is closed when an admin has asked for this client to go away.
// serveClient and serveFMP4 derive their context from it.
func (c Client) Stopped() <-chan struct{} { return c.stop }
