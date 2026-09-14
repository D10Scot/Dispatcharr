package control

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// The batch reaches Django in RelayEventBatchSerializer's shape, signed with
// both internal headers, and the identity keys ride at the top level the way
// emit_event puts them there.
func TestPostEventsSendsTheBatchDjangoAccepts(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{})
	t.Cleanup(cp.Close)
	client := testClient(t, cp)
	streamID := 41
	err := client.PostEvents(context.Background(), []Event{
		{Type: "stream_switch", ChannelID: "c-1", ChannelName: "BBC One", StreamID: &streamID, Details: map[string]any{"new_url": "http://host/[redacted]", "stream_id": 41}},
		{Type: "channel_buffering", ChannelID: "c-1", Details: map[string]any{"speed": 0.8}},
	})
	if err != nil {
		t.Fatalf("PostEvents: %v", err)
	}
	seen := cp.RequestsTo("/events")
	if len(seen) != 1 || seen[0].Method != http.MethodPost {
		t.Fatalf("the fake saw %+v, want one POST to /api/relay/events", seen)
	}
	if seen[0].Header.Get(HeaderInternal) == "" || seen[0].Header.Get(HeaderInternalRequest) == "" {
		t.Fatal("the batch was not signed with both internal headers")
	}
	var body struct {
		Events []map[string]any `json:"events"`
	}
	if err := json.Unmarshal(seen[0].Body, &body); err != nil || len(body.Events) != 2 {
		t.Fatalf("body = %s", seen[0].Body)
	}
	if body.Events[0]["stream_id"] != 41.0 || body.Events[0]["channel_name"] != "BBC One" || body.Events[0]["type"] != "stream_switch" {
		t.Fatalf("the first event lost its identity keys: %v", body.Events[0])
	}
	if _, present := body.Events[1]["stream_id"]; present {
		t.Fatal("an event with no stream id carried the key")
	}
	if got := cp.Events(); len(got) != 2 || got[0].Details["new_url"] != "http://host/[redacted]" {
		t.Fatalf("the fake recorded %+v", got)
	}
}

// A batch over the route's limit is refused before it is sent: a 400 from
// Django would refuse every event in it.
func TestABatchOverTheRoutesLimitIsRefusedLocally(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{})
	t.Cleanup(cp.Close)
	batch := make([]Event, MaxEventsPerBatch+1)
	for i := range batch {
		batch[i] = Event{Type: "channel_buffering"}
	}
	if err := testClient(t, cp).PostEvents(context.Background(), batch); err == nil {
		t.Fatal("a batch of 201 events was sent")
	}
	if len(cp.Requests()) != 0 {
		t.Fatal("the oversized batch reached the control plane")
	}
	if MaxEventsPerBatch != 200 {
		t.Errorf("MaxEventsPerBatch = %d, want 200 (apps/proxy/serializers.py:272's max_length)", MaxEventsPerBatch)
	}
}

// logCapture keeps every line an slog handler writes.
type logCapture struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (c *logCapture) Write(p []byte) (int, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.buf.Write(p)
}

func (c *logCapture) count(substr string) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return strings.Count(c.buf.String(), substr)
}

// THE OUTAGE FLAG (control_plane.py:255-329): three batches failing during
// an outage log ONE warning, not three; the batch that succeeds afterwards
// logs one recovery line; and the events raised during the outage are lost,
// not delivered late (CLAUDE.md § Operationally).
func TestTheEmitterLogsOnceIntoAnOutageAndOnceOutOfIt(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{})
	t.Cleanup(cp.Close)
	logs := &logCapture{}
	emitter := NewEmitter(testClient(t, cp), slog.New(slog.NewTextHandler(logs, &slog.HandlerOptions{Level: slog.LevelDebug})))
	// Small enough that each Emit is its own batch: the worker is idle
	// between them.
	emitter.timeout = 2 * time.Second

	cp.SetStatus(http.StatusServiceUnavailable)
	for i := 0; i < 3; i++ {
		emitter.Emit(Event{Type: "channel_buffering", ChannelID: "c-1"})
		// Wait for the worker to have posted it before the next, so three
		// batches are posted rather than one batch of three.
		deadline := time.Now().Add(5 * time.Second)
		for len(cp.RequestsTo("/events")) < 2*(i+1) && time.Now().Before(deadline) {
			time.Sleep(10 * time.Millisecond)
		}
	}
	if !emitter.Down() {
		t.Fatal("the emitter does not report the outage")
	}
	// The handler captures DEBUG too, so count the WARN line alone: the
	// later batches are logged at DEBUG, which is the whole point.
	if got := logs.count("level=WARN msg=\"could not post relay events\""); got != 1 {
		t.Fatalf("the outage was logged at WARN %d times, want once on the transition", got)
	}

	cp.SetStatus(0)
	emitter.Emit(Event{Type: "channel_failover", ChannelID: "c-1"})
	emitter.Close()
	if emitter.Down() {
		t.Fatal("the emitter still reports the outage after a successful batch")
	}
	if got := logs.count("level=INFO msg=\"relay events reachable again"); got != 1 {
		t.Fatalf("the recovery was logged %d times, want once", got)
	}
	// Six failed posts (three batches, each retried once), then one that
	// landed: only the last event is in the fake's log.
	if got := cp.EventsOfType("channel_buffering"); len(got) != 0 {
		t.Fatalf("%d events raised during the outage were delivered; they must be lost, not queued", len(got))
	}
	if got := cp.EventsOfType("channel_failover"); len(got) != 1 {
		t.Fatalf("the event raised after recovery was not delivered: %+v", got)
	}
}

// A refusal is logged as an error, once, and not retried.
func TestARefusedEventsRouteIsLoggedOnceAndNotRetried(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: http.StatusForbidden})
	t.Cleanup(cp.Close)
	logs := &logCapture{}
	emitter := NewEmitter(testClient(t, cp), slog.New(slog.NewTextHandler(logs, nil)))
	emitter.Emit(Event{Type: "channel_buffering"})
	emitter.Emit(Event{Type: "channel_buffering"})
	emitter.Close()
	if got := logs.count("relay events refused"); got != 1 {
		t.Fatalf("the refusal was logged %d times, want once", got)
	}
	if n := len(cp.RequestsTo("/events")); n < 1 || n > 2 {
		t.Fatalf("the fake saw %d event posts, want one or two batches and no retries of a 403", n)
	}
}

// Emit never blocks: a full queue drops with a warning rather than stalling
// the caller. The worker is held in a post that will time out while the
// queue is filled past its depth.
func TestEmitNeverBlocksOnAFullQueue(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Delay: 500 * time.Millisecond})
	t.Cleanup(cp.Close)
	logs := &logCapture{}
	client := testClient(t, cp)
	client.HTTP = &http.Client{Timeout: 100 * time.Millisecond}
	emitter := NewEmitter(client, slog.New(slog.NewTextHandler(logs, nil)))
	emitter.timeout = 100 * time.Millisecond
	t.Cleanup(emitter.Close)

	emitter.Emit(Event{Type: "channel_buffering"})
	deadline := time.Now().Add(2 * time.Second)
	for len(cp.RequestsTo("/events")) == 0 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		for i := 0; i < EmitterQueueDepth+50; i++ {
			emitter.Emit(Event{Type: "channel_buffering"})
		}
	}()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Emit blocked on a full queue")
	}
	if logs.count("events queue is full") == 0 {
		t.Fatal("no drop was logged")
	}
}

var _ = errors.Is
