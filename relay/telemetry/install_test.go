package telemetry_test

import (
	"bytes"
	"context"
	"encoding/json"
	"log"
	"log/slog"
	"strings"
	"sync"
	"testing"
	"time"

	sdklog "go.opentelemetry.io/otel/sdk/log"

	"github.com/D10Scot/Dispatcharr/relay/telemetry"
	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

// keepLogGlobals restores slog.Default and package log's output, flags and
// prefix when the test ends: the install helpers change all four. The
// returned func abandons the restore, for a test that found logging
// deadlocked: package log's lock is then held for good and restoring would
// hang the cleanup instead of failing the test.
func keepLogGlobals(t *testing.T) (abandon func()) {
	t.Helper()
	prev, out, flags, prefix := slog.Default(), log.Writer(), log.Flags(), log.Prefix()
	var skip bool
	t.Cleanup(func() {
		if skip {
			return
		}
		slog.SetDefault(prev)
		log.SetOutput(out)
		log.SetFlags(flags)
		log.SetPrefix(prefix)
	})
	return func() { skip = true }
}

func env(m map[string]string) func(string) string { return func(k string) string { return m[k] } }

// bodies is an sdklog.Exporter keeping each record's body.
type bodies struct {
	mu  sync.Mutex
	got []string
}

func (b *bodies) Export(_ context.Context, rs []sdklog.Record) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	for i := range rs {
		b.got = append(b.got, rs[i].Body().AsString())
	}
	return nil
}
func (*bodies) Shutdown(context.Context) error   { return nil }
func (*bodies) ForceFlush(context.Context) error { return nil }

func (b *bodies) all() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return strings.Join(b.got, "\n")
}

// With the text format the early logger changes nothing; with JSON, slog and
// package log both write cleaned JSON with no "relay-go: " prefix in msg.
func TestInstallEarlyLogger(t *testing.T) {
	keepLogGlobals(t)
	log.SetPrefix("relay-go: ")
	before := slog.Default()
	var buf bytes.Buffer

	telemetry.InstallEarlyLogger(env(map[string]string{}), &buf)
	telemetry.InstallEarlyLogger(env(map[string]string{"MINO_LOG_FORMAT": "text"}), &buf)
	if slog.Default() != before || log.Prefix() != "relay-go: " {
		t.Fatal("the text format changed the default logger")
	}

	telemetry.InstallEarlyLogger(env(map[string]string{"MINO_LOG_FORMAT": "json"}), &buf)
	slog.Info("tuned", "channel", chanUUID, "bogus", sentinel)
	log.Printf("starting on port %d", 5658)
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("lines = %q, want two JSON records", lines)
	}
	var printed map[string]any
	if err := json.Unmarshal([]byte(lines[1]), &printed); err != nil {
		t.Fatalf("log.Printf did not reach the JSON handler: %v: %s", err, lines[1])
	}
	if printed["msg"] != "starting on port 5658" || printed["mino.program"] != "relay-go" {
		t.Errorf("log.Printf record = %v", printed)
	}
	if strings.Contains(buf.String(), chanUUID) || strings.Contains(buf.String(), sentinel) {
		t.Errorf("LEAK before Init: %s", buf.String())
	}
}

// Text with no OTLP logs: the default handler is left exactly as it was.
func TestInstallLoggerTextWithoutOTLPChangesNothing(t *testing.T) {
	keepLogGlobals(t)
	rec := telemetrytest.Install(t)
	before, out := slog.Default().Handler(), log.Writer()
	rec.T.InstallLogger(&bytes.Buffer{})
	if slog.Default().Handler() != before {
		t.Fatal("InstallLogger replaced the text handler with no OTLP log signal on")
	}
	if log.Writer() != out {
		t.Fatal("InstallLogger moved package log's output with no OTLP log signal on")
	}
}

// Text with OTLP logs: slog lines reach both the unchanged text output and the
// bridge (cleaned), package log keeps today's text on w and does not deadlock.
func TestInstallLoggerTextWithOTLPFansOut(t *testing.T) {
	abandon := keepLogGlobals(t)
	sink := &bodies{}
	ids := &telemetry.ChannelIDs{}
	ids.Set(chanUUID, 42)
	rec := telemetrytest.Install(t, telemetry.WithLogExporter(sink), telemetry.WithChannelIDs(ids))
	var buf bytes.Buffer
	log.SetOutput(&buf)
	log.SetFlags(0)
	log.SetPrefix("relay-go: ")

	rec.T.InstallLogger(&buf)
	done := make(chan struct{})
	go func() {
		defer close(done)
		slog.Info("channel started", "channel", chanUUID)
		log.Printf("received %s, draining", "terminated")
	}()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		abandon()
		t.Fatal("logging deadlocked after InstallLogger: package log still writes through the new slog default, whose text handler writes through package log")
	}
	text := buf.String()
	for _, want := range []string{"relay-go: INFO channel started channel=" + chanUUID, "relay-go: received terminated, draining"} {
		if !strings.Contains(text, want) {
			t.Errorf("text output lacks %q (it must stay byte-identical):\n%s", want, text)
		}
	}
	if got := sink.all(); got != "channel started" {
		t.Errorf("OTLP bodies = %q, want only the slog record (log.Printf bypasses the bridge)", got)
	}
}

// JSON: InstallLogger replaces the early handler with the Telemetry's own,
// whose channel id map Init owns.
func TestInstallLoggerJSONUsesTheChannelIDs(t *testing.T) {
	keepLogGlobals(t)
	ids := &telemetry.ChannelIDs{}
	ids.Set(chanUUID, 42)
	tel, err := telemetry.Init(context.Background(), telemetry.Config{SamplerRatio: 1, LogFormat: telemetry.LogFormatJSON}, telemetry.WithChannelIDs(ids))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = tel.Shutdown(context.Background()) })
	var buf bytes.Buffer
	tel.InstallLogger(&buf)
	log.Printf("plain")
	slog.Info("tuned", "channel", chanUUID)
	if !strings.Contains(buf.String(), `"channel_id":"42"`) || strings.Contains(buf.String(), chanUUID) {
		t.Errorf("JSON output = %s", buf.String())
	}
	if strings.Contains(buf.String(), "relay-go: ") {
		t.Errorf("the prefix reached msg: %s", buf.String())
	}
}
