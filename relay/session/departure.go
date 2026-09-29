package session

import "github.com/D10Scot/Dispatcharr/relay/channel"

// Departure is what an ended session still owes the process: the
// client_disconnect its connect earned, and the two releases it held. It is
// taken under the table's lock and run after it is released.
type Departure struct {
	table     *Table
	session   *Session
	owner     Owner
	client    *channel.Client
	connected bool
	releases  Releases
	// idle is true for a departure the sweep (or a lazy expiry) made: the
	// session stays in the table as DEPARTED and settles when the departure
	// has run. A leave or an admin stop removed its session already.
	idle bool
}

// Run performs the departure: client_disconnect when the session's connect
// was emitted, then the pipeline reference, then the registry entry -- which,
// as the last client, may stop the channel -- and finally, for an idle
// departure, the settle that makes the session resumable.
//
// The disconnect comes FIRST so it names a client the registry still lists,
// and the entry is released LAST because its release is what can end the
// channel and wait for it.
func (d *Departure) Run() {
	if d.connected && d.owner != nil {
		d.owner.EmitClientDisconnect(d.client, d.table.now())
	}
	if d.releases.Output != nil {
		d.releases.Output()
	}
	if d.releases.BeforeClient != nil {
		d.releases.BeforeClient()
	}
	if d.releases.Client != nil {
		d.releases.Client()
	}
	if d.idle {
		d.table.log.Info("an HLS session departed idle", "client", d.client.ID)
		d.table.settle(d.session)
	}
}
