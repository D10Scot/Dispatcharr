package httpapi

import (
	"math"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
)

// userAgentEventLimit is the cut both generators apply before the user agent
// reaches an event: `self.client_user_agent[:100]`, at
// output/ts/generator.py:138 (client_connect) and :658 (client_disconnect),
// and output/fmp4/generator.py:120 (client_connect, the only event that file
// raises).
const userAgentEventLimit = 100

// clientEventDetails is the four details both client transitions carry
// (output/ts/generator.py:132-144, output/fmp4/generator.py:114-126):
// client_ip, client_id, a user agent cut at 100 characters, and the user id
// with an empty one sent as null.
//
// TWO STATED DIVERGENCES, both in the value rather than the shape:
//
//   - user_agent is the CLIENT REGISTRY's value, which identify() already
//     defaults to "unknown" (client_manager.py:236). Python's generators read
//     the raw request header instead, so a client that sent none puts null on
//     this event there and "unknown" here -- while both registries carry
//     "unknown", which is the value every status surface renders.
//   - user_id is `self.user_id or None` there over a value the view resolved;
//     here it is the registry's, which identify() defaults to the string "0"
//     (client_manager.py:241). "0" is falsy in neither language's sense the
//     same way, so it is mapped to null explicitly rather than left to a
//     truthiness rule that does not exist in Go.
func clientEventDetails(client *channel.Client) map[string]any {
	details := map[string]any{
		"client_ip": client.IPAddress,
		"client_id": client.ID,
	}
	agent := client.UserAgent
	if len(agent) > userAgentEventLimit {
		agent = agent[:userAgentEventLimit]
	}
	if agent != "" {
		details["user_agent"] = agent
	} else {
		details["user_agent"] = nil
	}
	if client.UserID != "" && client.UserID != "0" {
		details["user_id"] = client.UserID
	} else {
		details["user_id"] = nil
	}
	return details
}

// emitClientConnect is client_connect, raised for BOTH client types
// (Amendment A6.5): output/ts/generator.py:132-144 for a TS client and
// output/fmp4/generator.py:114-126 for an fMP4 one, each at the point its
// setup has succeeded and before its first byte of media.
func emitClientConnect(ch *channel.Channel, client *channel.Client) {
	ch.Emit("client_connect", clientEventDetails(client))
}

// emitClientDisconnect is client_disconnect, raised for a TS client ONLY.
//
// THE ASYMMETRY IS PYTHON'S AND IS REPRODUCED RATHER THAN EVENED OUT:
// output/ts/generator.py:652-666 raises it in the generator's cleanup, and
// output/fmp4/generator.py raises no disconnect at all -- `emit_event`
// appears once in that file, at :114. An fMP4 viewer's departure is therefore
// invisible to Connect and to the SystemEvent log in both relays.
//
// duration is round(elapsed, 2) over the client's own connection
// (generator.py:610, :659) and bytes_sent is the counter clientstats.go
// keeps.
func emitClientDisconnect(ch *channel.Channel, client *channel.Client, at time.Time) {
	details := clientEventDetails(client)
	details["duration"] = math.Round(at.Sub(client.ConnectedAt).Seconds()*100) / 100
	details["bytes_sent"] = client.Stats(at).BytesSent
	ch.Emit("client_disconnect", details)
}
