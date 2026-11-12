package output

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/telemetry"
	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

const telUUID = "3e8a1f02-5c6d-4b7e-9f10-a2b3c4d5e6f7"

type lockedBuffer struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *lockedBuffer) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}

func (l *lockedBuffer) String() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.String()
}

// A real fMP4 remux that exits at once logs "the remux ended" through a
// logger built with the channel's UUID (fmp4.go's log.With). The control
// handler sees the UUID; the JSON and the OTLP sink carry channel_id instead
// and the UUID nowhere (D9). The remux's process group is labelled by the
// channel's numeric id, never the UUID.
func TestTheRemuxEndedLineCarriesTheNumericIDInEverySink(t *testing.T) {
	ids := &telemetry.ChannelIDs{}
	ids.Set(telUUID, 42)
	rec, jsonOut := telemetrytest.InstallJSONLogs(t, telemetry.WithChannelIDs(ids))
	raw := &lockedBuffer{}
	slog.SetDefault(slog.New(telemetry.Fanout(slog.NewJSONHandler(raw, nil), slog.Default().Handler())))

	p, err := Start(t.Context(), Config{
		ChannelID: telUUID,
		ChannelPK: 42,
		Source:    sourceRing(t, 64),
		Retention: time.Minute,
		Remux:     Remux{Command: "sh", Argv: []string{"-c", "exit 0"}},
	})
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	t.Cleanup(p.Stop)
	select {
	case <-p.Done():
	case <-time.After(10 * time.Second):
		t.Fatal("the remux did not end")
	}

	const msg = "the remux ended"
	if out := raw.String(); !strings.Contains(out, msg) || !strings.Contains(out, telUUID) {
		t.Fatalf("control: the raw handler did not see %q with the UUID; the test proves nothing:\n%s", msg, out)
	}

	var found bool
	for _, line := range strings.Split(strings.TrimSpace(jsonOut.String()), "\n") {
		var r map[string]any
		if err := json.Unmarshal([]byte(line), &r); err != nil {
			t.Fatalf("JSON sink line is not JSON: %v: %s", err, line)
		}
		if r["msg"] == msg {
			found = true
			if r["channel_id"] != "42" || r["format"] != FormatFMP4 {
				t.Errorf("JSON sink record = %v, want channel_id 42 and format %s", r, FormatFMP4)
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
			if r.Attrs["channel_id"] != "42" {
				t.Errorf("OTLP sink: %q has channel_id %v, want 42", msg, r.Attrs["channel_id"])
			}
		}
		if strings.Contains(r.Body, telUUID) || strings.Contains(fmt.Sprint(r.Attrs), telUUID) {
			t.Errorf("LEAK: OTLP record %+v carries the channel UUID", r)
		}
	}
	if !found {
		t.Errorf("OTLP sink has no %q: %+v", msg, rec.Logs())
	}
}
