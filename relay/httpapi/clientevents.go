package httpapi

import (
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
)

// The two client transitions' bodies live on the channel (channel/
// clientevents.go) since Phase 4a-1b, because an HLS session's client entry is
// dropped -- and its client_disconnect owed -- by code the channel runs, not
// by the handler that served it. These stay as the handlers' one spelling, so
// no TS or fMP4 call site moved.

// emitClientConnect is client_connect, raised for every client type.
func emitClientConnect(ch *channel.Channel, client *channel.Client) {
	ch.EmitClientConnect(client)
}

// emitClientDisconnect is client_disconnect. See channel.EmitClientDisconnect
// for why an fMP4 viewer raises none and an HLS session raises one.
func emitClientDisconnect(ch *channel.Channel, client *channel.Client, at time.Time) {
	ch.EmitClientDisconnect(client, at)
}
