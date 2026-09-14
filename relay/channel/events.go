package channel

// Event is one transition this package reports, the domain half of what
// control.Event puts on the wire: httpapi adapts one to the other so this
// package keeps not importing the wire package (tuning.go's own rule).
//
// The identity keys mirror apps/proxy/control_plane.py:296-311's emit_event:
// channel_id and channel_name from the channel, and stream_id lifted out of
// Details to the top level when the transition carries one -- and LEFT in
// Details too, as emit_event leaves it, because core/relay_events.py:
// _apply_stream_stats is written around that shape.
type Event struct {
	Type        string
	ChannelID   string
	ChannelName string
	ClientID    string
	StreamID    *int
	Details     map[string]any
}

// EventSink receives events. Emit must never block the caller: the byte
// path calls it, and a slow control plane must cost a queued event, not a
// stalled stream (control_plane.py:311-313).
type EventSink interface {
	Emit(Event)
}

// discardEvents is the sink a Manager built with no Events uses.
type discardEvents struct{}

func (discardEvents) Emit(Event) {}

// emit builds and sends one event for this channel.
func (c *Channel) emit(typ string, details map[string]any) {
	if details == nil {
		details = map[string]any{}
	}
	event := Event{Type: typ, ChannelID: c.id, ChannelName: c.channelName, Details: details}
	if id, ok := details["stream_id"].(int); ok {
		event.StreamID = &id
	}
	c.events.Emit(event)
}
