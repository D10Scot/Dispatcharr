package control

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// Event is one relay transition, the shape apps/proxy/serializers.py's
// RelayEventSerializer accepts and apps/proxy/control_plane.py:296-311's
// emit_event builds: the type, the channel's id and name, and the two
// identity keys emit_event copies out of details to the top level when
// present (client_id, stream_id). Details is everything else, and it keeps
// its own copy of those two keys exactly as emit_event leaves them there.
//
// A PROVIDER URL NEVER CROSSES HERE UNREDACTED. input/manager.py's
// stream_switch and channel_error carry a URL in details -- through
// redact_url and truncated to 100 characters -- and core/relay_events.py's
// WebSocket push is a field whitelist that drops details entirely. The relay's
// half of that contract is that whatever it puts in details went through
// redact.Line first, and that is the PRODUCERS' job, not this type's or
// channel.emit's: the two sites in package channel that put a URL in
// details (failover's stream_switch, run's channel_error) each call
// redact.Line before building the map. A third site would have to too.
type Event struct {
	Type        string         `json:"type"`
	ChannelID   string         `json:"channel_id,omitempty"`
	ChannelName string         `json:"channel_name,omitempty"`
	ClientID    string         `json:"client_id,omitempty"`
	StreamID    *int           `json:"stream_id,omitempty"`
	Details     map[string]any `json:"details"`
}

// MaxEventsPerBatch is RelayEventBatchSerializer's max_length
// (apps/proxy/serializers.py:272): a larger batch is a 400, which would
// refuse every event in it.
const MaxEventsPerBatch = 200

// PostEvents posts one batch. Unlike NextSource and Release it is the
// caller's job to decide whether a failure matters: Emitter below is the
// fire-and-forget caller, and it never lets an error reach the byte path.
func (c *Client) PostEvents(ctx context.Context, events []Event) error {
	if len(events) == 0 {
		return nil
	}
	if len(events) > MaxEventsPerBatch {
		return fmt.Errorf("control: a batch of %d events exceeds the route's limit of %d", len(events), MaxEventsPerBatch)
	}
	body, err := json.Marshal(struct {
		Events []Event `json:"events"`
	}{events})
	if err != nil {
		return fmt.Errorf("encoding the events batch: %w", err) // credential-logging: ok - encoding/json reports a TYPE it cannot encode, never a field's value
	}
	_, _, err = c.post(ctx, "/api/relay/events", body)
	return err
}

// Emitter is the port of apps/proxy/control_plane.py:255-329's post_events
// and emit_event: transitions are posted without blocking the caller, an
// outage is logged once on the way in and once on the way out (the
// _events_down flag, module-level there and per-emitter here), and an event
// raised while the control plane is down is LOST, not queued for retry --
// CLAUDE.md § Operationally records that as measured behaviour, and this
// keeps it.
//
// ONE WORKER AND A QUEUE, where Python spawns one greenlet per event. The
// difference is deliberate and in the safe direction: a relay whose control
// plane is slow would otherwise accumulate one blocked goroutine per
// transition for the length of the outage, and the events route accepts up
// to MaxEventsPerBatch per call, so whatever has queued while one batch was
// in flight goes as the next batch. Order is preserved, which the greenlets
// did not guarantee. A full queue drops the newest event with a warning
// rather than blocking: a stall on the byte path is the one cost this
// design exists to refuse (control_plane.py:311-313's own reasoning).
type Emitter struct {
	client *Client
	log    *slog.Logger
	// timeout bounds one batch's post. Zero means the client's own worst
	// case, two attempts of ConnectTimeout+ReadTimeout plus the retry delay.
	timeout time.Duration

	queue chan Event
	done  chan struct{}

	mu   sync.Mutex
	down bool
}

// EmitterQueueDepth is how many events may wait for the worker. At one
// transition per failover and one stats flush per thirty seconds per channel
// (the Python relay's cadence), a thousand is hours of backlog, not seconds.
const EmitterQueueDepth = 1024

// NewEmitter starts the worker. Close stops it.
func NewEmitter(client *Client, log *slog.Logger) *Emitter {
	if log == nil {
		log = slog.Default()
	}
	e := &Emitter{
		client:  client,
		log:     log,
		timeout: 2*(ConnectTimeout+ReadTimeout) + RetryDelay,
		queue:   make(chan Event, EmitterQueueDepth),
		done:    make(chan struct{}),
	}
	go e.run()
	return e
}

// Emit queues one event. It never blocks and never fails: a full queue is
// logged and the event dropped.
func (e *Emitter) Emit(event Event) {
	select {
	case e.queue <- event:
	default:
		e.log.Warn("relay event dropped: the events queue is full", "type", event.Type, "channel", event.ChannelID)
	}
}

// Close stops the worker once the queue has drained. It is what the SIGTERM
// drain (2c-8) will call; tests call it to know every posted batch has been
// recorded by the fake.
func (e *Emitter) Close() {
	close(e.queue)
	<-e.done
}

// Down reports whether the last batch failed: post_events' _events_down.
func (e *Emitter) Down() bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.down
}

func (e *Emitter) run() {
	defer close(e.done)
	for first := range e.queue {
		batch := []Event{first}
		// Whatever else is already waiting goes in the same batch, up to
		// the route's limit.
	drain:
		for len(batch) < MaxEventsPerBatch {
			select {
			case next, ok := <-e.queue:
				if !ok {
					break drain
				}
				batch = append(batch, next)
			default:
				break drain
			}
		}
		e.post(batch)
	}
}

// post is post_events' disposition (control_plane.py:265-329), one log line
// per transition into and out of an outage rather than one per batch.
func (e *Emitter) post(batch []Event) {
	ctx, cancel := context.WithTimeout(context.Background(), e.timeout)
	defer cancel()
	err := e.client.PostEvents(ctx, batch)

	e.mu.Lock()
	defer e.mu.Unlock()

	var refused *Refused
	var misconfigured *ErrNotConfigured
	switch {
	case err == nil:
		if e.down {
			e.log.Info("relay events reachable again after an outage")
			e.down = false
		}
	case errors.As(err, &refused):
		if e.down {
			e.log.Debug("relay events refused", "status", refused.Status, "events", len(batch))
		} else {
			e.log.Error("relay events refused", "status", refused.Status, "events", len(batch))
			e.down = true
		}
	case errors.As(err, &misconfigured):
		// The variable name only, never the value: control_plane.py:297-315's
		// own rule, for the same reason -- the value can carry userinfo.
		if e.down {
			e.log.Debug("could not post relay events: the control-plane address is misconfigured", "variable", misconfigured.Variable, "events", len(batch))
		} else {
			e.log.Error("could not post relay events: the control-plane address is misconfigured", "variable", misconfigured.Variable, "events", len(batch))
			e.down = true
		}
	default:
		if e.down {
			e.log.Debug("could not post relay events", "events", len(batch), "error", redact.Error(err))
		} else {
			e.log.Warn("could not post relay events", "events", len(batch), "error", redact.Error(err))
			e.down = true
		}
	}
}
