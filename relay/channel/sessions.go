package channel

import (
	"errors"
)

// Phase 4a-1b: an HLS viewer is a client in the registry exactly while its
// session is live (Phase 4 spec, § Presence and lifecycle). The session table
// itself is relay/session; this file is everything the channel package owes
// it, and the one seam between them. relay/channel never imports relay/
// session -- the table imports the channel, for *Channel and *Client -- so the
// manager reaches it through SessionEnder.

// ErrChannelAbsent is a resume that found no running channel under the
// session's channel: it was stopped, or stopped and started again under the
// same id (a different *Channel). A resume never starts one.
var ErrChannelAbsent = errors.New("channel: the channel is not running")

// ErrChannelEnding is an HLS attach that arrived after the channel's outputs
// were stopped: the channel is on its way out, and a pipeline registered now
// would be one nothing will ever stop.
var ErrChannelEnding = errors.New("channel: the channel is ending")

// StoppedClient is an HLS session's client entry that the session table has
// just marked STOPPED: the caller drops it without running a release.
type StoppedClient struct {
	ClientID string
	// Connected is true when client_connect was emitted for the session's
	// current attachment, so client_disconnect is owed.
	Connected bool
}

// SessionEnder is the HLS session table as the manager sees it.
//
// StopChannel marks every session of c STOPPED and returns the client entries
// those sessions held. It must take no lock the channel or manager holds while
// calling it: the table's own mutex is the innermost in the process.
type SessionEnder interface {
	StopChannel(c *Channel) []StoppedClient
}

// dropHLSClients deletes the named entries under c.mu and, after unlocking,
// emits client_disconnect for each one whose client_connect was emitted. It
// never calls Manager.release: the goroutine that stops the channel is the one
// calling it, or the one that then asks the manager whether the channel is
// idle (Manager.EndHLSSessions).
func (c *Channel) dropHLSClients(stopped []StoppedClient) {
	if len(stopped) == 0 {
		return
	}
	var disconnects []Client
	c.mu.Lock()
	for _, s := range stopped {
		cl, held := c.clients[s.ClientID]
		if !held {
			continue
		}
		delete(c.clients, s.ClientID)
		if len(c.clients) == 0 {
			c.idleSince = c.now()
		}
		if s.Connected {
			disconnects = append(disconnects, *cl)
		}
	}
	c.mu.Unlock()
	if len(disconnects) == 0 {
		return
	}
	at := c.now()
	for i := range disconnects {
		c.EmitClientDisconnect(&disconnects[i], at)
	}
}
