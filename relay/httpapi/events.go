package httpapi

import (
	"context"
	"log/slog"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// EventSink adapts control.Emitter to channel.EventSink, field for field.
// The two types exist so package channel never imports the wire package;
// this is the whole of the seam between them.
func EventSink(emitter *control.Emitter) channel.EventSink {
	return eventSink{emitter}
}

type eventSink struct{ emitter *control.Emitter }

func (s eventSink) Emit(e channel.Event) {
	s.emitter.Emit(control.Event{
		Type:        e.Type,
		ChannelID:   e.ChannelID,
		ChannelName: e.ChannelName,
		ClientID:    e.ClientID,
		StreamID:    e.StreamID,
		Details:     e.Details,
	})
}

// ReleaseVia is the manager's Release hook over the control client: the
// port of live_proxy/server.py:2335-2385's _release_stream_resources,
// called once per channel when its source goroutine returns. A refusal or
// an outage is logged and the slot "stays counted", exactly as there; the
// call is bounded by the client's own worst case, since a channel's
// teardown must not wait on a hung control plane.
func ReleaseVia(client *control.Client, log *slog.Logger) func(id string, info channel.SourceInfo) {
	if log == nil {
		log = slog.Default()
	}
	return func(id string, info channel.SourceInfo) {
		ctx, cancel := context.WithTimeout(context.Background(), tuneBudget)
		defer cancel()
		req := control.ReleaseRequest{}
		if info.StreamID != 0 {
			streamID := info.StreamID
			req.StreamID = &streamID
		}
		if info.M3UProfileID != 0 {
			profileID := info.M3UProfileID
			req.M3UProfileID = &profileID
		}
		released, err := client.Release(ctx, id, req)
		switch {
		case err != nil:
			log.Warn("could not release the provider slot; it stays counted", "channel", id, "error", redact.Error(err))
		case !released:
			log.Debug("the control plane found no slot to release", "channel", id)
		}
	}
}
