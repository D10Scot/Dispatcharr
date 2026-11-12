package channel

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/telemetry"
	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

// A channel UUID: a secret (CLAUDE.md § Auth). The relay's log calls name a
// channel by it, so every telemetry carrier must map it to the numeric id.
const telUUID = "9b2d4c1e-7a3f-4e0b-8c55-1f6e2d9a0c37"

// rawCapture is a plain JSON handler beside the relay's own: the control that
// proves the real log call did carry the UUID, so a sink without it is clean
// because of the mapping and not because the call never named it.
type rawCapture struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (r *rawCapture) Write(p []byte) (int, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.buf.Write(p)
}

func (r *rawCapture) String() string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.buf.String()
}

// installLogSinks installs telemetry with the JSON format and a recording OTLP
// log sink, and puts a raw control handler beside the relay's handler.
func installLogSinks(t *testing.T) (*telemetrytest.Recorder, *telemetrytest.SyncBuffer, *rawCapture) {
	t.Helper()
	rec, jsonOut := telemetrytest.InstallJSONLogs(t)
	raw := &rawCapture{}
	slog.SetDefault(slog.New(telemetry.Fanout(slog.NewJSONHandler(raw, nil), slog.Default().Handler())))
	return rec, jsonOut, raw
}

// assertMapped finds msg in both sinks with channel_id=pk and no UUID
// anywhere, after checking the control saw the UUID on that very record.
func assertMapped(t *testing.T, rec *telemetrytest.Recorder, jsonOut *telemetrytest.SyncBuffer, raw *rawCapture, msg string, pk int) {
	t.Helper()
	if !strings.Contains(raw.String(), msg) || !strings.Contains(raw.String(), telUUID) {
		t.Fatalf("control: the raw handler did not see %q with the UUID; the test proves nothing:\n%s", msg, raw.String())
	}

	var found bool
	for _, line := range strings.Split(strings.TrimSpace(jsonOut.String()), "\n") {
		var rec map[string]any
		if err := json.Unmarshal([]byte(line), &rec); err != nil {
			t.Fatalf("JSON sink line is not JSON: %v: %s", err, line)
		}
		if rec["msg"] == msg {
			found = true
			if rec["channel_id"] != fmt.Sprint(pk) {
				t.Errorf("JSON sink: %q has channel_id %v, want %d", msg, rec["channel_id"], pk)
			}
		}
	}
	if !found {
		t.Errorf("JSON sink has no %q:\n%s", msg, jsonOut.String())
	}
	if strings.Contains(jsonOut.String(), telUUID) {
		t.Errorf("LEAK: the JSON sink carries the channel UUID:\n%s", jsonOut.String())
	}

	found = false
	for _, r := range rec.Logs() {
		if r.Body == msg {
			found = true
			if r.Attrs["channel_id"] != fmt.Sprint(pk) {
				t.Errorf("OTLP sink: %q has channel_id %v, want %d", msg, r.Attrs["channel_id"], pk)
			}
		}
		if strings.Contains(r.Body, telUUID) {
			t.Errorf("LEAK: OTLP record body %q carries the channel UUID", r.Body)
		}
		for k, v := range r.Attrs {
			if strings.Contains(fmt.Sprint(v), telUUID) {
				t.Errorf("LEAK: OTLP record %q attribute %s carries the channel UUID", r.Body, k)
			}
		}
	}
	if !found {
		t.Errorf("OTLP sink has no %q: %+v", msg, rec.Logs())
	}
}

// A real failover with no resolver: its ERROR names the channel by UUID, and
// both the JSON and the OTLP sink carry channel_id instead (D9). The same
// failover counts M4 once, outcome no_resolver, labelled by the numeric id,
// and its span is relay.failover with that outcome.
func TestAFailoverWithNoResolverIsLoggedAndCountedByNumericID(t *testing.T) {
	rec, jsonOut, raw := installLogSinks(t)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	ch, release, err := m.Attach(telUUID, testClient("a"), func() (Started, error) {
		return Started{Source: failingSource{runs: &int32Counter{}}, Tuning: testTuning(), ChannelPK: 42,
			Info: SourceInfo{URL: "http://provider.invalid/primary.ts", StreamID: 1, M3UProfileID: 1}}, nil
	})
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	defer release()
	<-ch.Done()

	assertMapped(t, rec, jsonOut, raw, "no alternate stream available: this channel has no resolver", 42)

	points := rec.Points("mino_relay_failovers")
	if len(points) != 1 || points[0].Value != 1 {
		t.Fatalf("M4 = %+v, want one point of 1", points)
	}
	for k, want := range map[string]string{"channel_id": "42", "trigger": telemetry.TriggerMaxRetries, "outcome": "no_resolver"} {
		if got := points[0].Attrs[k]; got != want {
			t.Errorf("M4 %s = %v, want %s", k, got, want)
		}
	}
	span, ok := rec.Span("relay.failover")
	if !ok || !span.Ended || span.Attrs["mino.outcome"] != "no_resolver" || span.Attrs["mino.channel_id"] != int64(42) {
		t.Errorf("relay.failover = %+v, %v", span, ok)
	}
	for _, s := range rec.Spans() {
		for k, v := range s.Attrs {
			if strings.Contains(fmt.Sprint(v), telUUID) {
				t.Errorf("LEAK: span %q attribute %s carries the channel UUID", s.Name, k)
			}
		}
	}
}

// Each failover outcome M4 can record, through the real failover path.
func TestEveryFailoverOutcomeIsCounted(t *testing.T) {
	for _, tc := range []struct {
		outcome  string
		resolver Resolver
	}{
		{"no_alternate", &fakeResolver{}},
		{"unresolved", &fakeResolver{err: fmt.Errorf("control plane down for %s", telUUID)}},
		{"same_url", &fakeResolver{answers: []Resolved{{Source: flowingSource{}, Info: SourceInfo{URL: "http://provider.invalid/primary.ts", StreamID: 7}}}}},
		{"switched", &fakeResolver{answers: []Resolved{{Source: flowingSource{}, Info: SourceInfo{URL: "http://provider.invalid/alt.ts", StreamID: 7}}}}},
	} {
		t.Run(tc.outcome, func(t *testing.T) {
			rec, jsonOut, _ := installLogSinks(t)
			m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
			t.Cleanup(m.StopAll)
			ch, release, err := m.Attach(telUUID, testClient("a"), func() (Started, error) {
				return Started{Source: failingSource{runs: &int32Counter{}}, Tuning: testTuning(), ChannelPK: 42, Resolver: tc.resolver,
					Info: SourceInfo{URL: "http://provider.invalid/primary.ts", StreamID: 1, M3UProfileID: 1}}, nil
			})
			if err != nil {
				t.Fatalf("Attach: %v", err)
			}
			defer release()
			if tc.outcome == "switched" {
				waitFor(t, "the switch to stream 7", 10*time.Second, func() bool { return ch.Source().StreamID == 7 })
			} else {
				<-ch.Done()
			}
			var got []telemetrytest.Point
			for _, p := range rec.Points("mino_relay_failovers") {
				if p.Attrs["outcome"] == tc.outcome {
					got = append(got, p)
				}
			}
			if len(got) != 1 || got[0].Value < 1 || got[0].Attrs["channel_id"] != "42" {
				t.Fatalf("M4 with outcome %s = %+v (all: %+v)", tc.outcome, got, rec.Points("mino_relay_failovers"))
			}
			if strings.Contains(jsonOut.String(), telUUID) {
				t.Errorf("LEAK: the JSON sink carries the channel UUID:\n%s", jsonOut.String())
			}
		})
	}
}
