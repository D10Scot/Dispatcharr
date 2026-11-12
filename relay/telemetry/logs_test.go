package telemetry_test

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/telemetry"
	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

func jsonTelemetry(t *testing.T) (*telemetry.Telemetry, *bytes.Buffer, *slog.Logger) {
	t.Helper()
	ids := &telemetry.ChannelIDs{}
	ids.Set(chanUUID, 42)
	rec := telemetrytest.Install(t, telemetry.WithChannelIDs(ids))
	var buf bytes.Buffer
	h := jsonHandler(rec.T, &buf)
	return rec.T, &buf, slog.New(h)
}

// jsonHandler asks the Telemetry for the JSON shape regardless of its config.
func jsonHandler(t *telemetry.Telemetry, w *bytes.Buffer) slog.Handler {
	return telemetry.NewSafeHandler(telemetry.NewJSONHandler(w, slog.LevelInfo), telemetry.DefaultRules, t.ChannelIDs())
}

func TestTheJSONHandlerKeys(t *testing.T) {
	_, buf, log := jsonTelemetry(t)

	// No span: no trace_id, never an empty one.
	log.Info("plain", "channel", chanUUID, "format", "mpegts:p3", "bogus", sentinel)
	var plain map[string]any
	if err := json.Unmarshal(buf.Bytes(), &plain); err != nil {
		t.Fatalf("not JSON: %v: %s", err, buf)
	}
	for _, k := range []string{"time", "level", "msg", "service.name", "mino.program", "channel_id", "format"} {
		if _, ok := plain[k]; !ok {
			t.Errorf("POLICY: key %q missing from %v", k, plain)
		}
	}
	if plain["service.name"] != "mino-relay" || plain["mino.program"] != "relay-go" || plain["channel_id"] != "42" {
		t.Errorf("record = %v", plain)
	}
	for _, k := range []string{"trace_id", "span_id", "logger", "bogus", "channel"} {
		if _, ok := plain[k]; ok {
			t.Errorf("key %q must be absent: %v", k, plain)
		}
	}
	if strings.Contains(buf.String(), sentinel) || strings.Contains(buf.String(), chanUUID) {
		t.Errorf("LEAK: %s", buf)
	}

	// A span in the record's context: lower-case hex ids.
	buf.Reset()
	r := tuneRequest(false, false)
	ctx, tune := telemetry.StartTune(r.Context(), r, false)
	defer tune.End()
	log.InfoContext(ctx, "traced")
	var traced map[string]any
	if err := json.Unmarshal(buf.Bytes(), &traced); err != nil {
		t.Fatal(err)
	}
	tid, _ := traced["trace_id"].(string)
	sid, _ := traced["span_id"].(string)
	if len(tid) != 32 || len(sid) != 16 || tid != strings.ToLower(tid) {
		t.Errorf("trace_id=%q span_id=%q", tid, sid)
	}
}

func TestLogHandlerFormats(t *testing.T) {
	var buf bytes.Buffer
	text := slog.NewTextHandler(&buf, nil)

	// text, OTLP logs off: the existing handler, untouched and unwrapped.
	tel, err := telemetry.Init(context.Background(), telemetry.Config{SamplerRatio: 1, LogFormat: telemetry.LogFormatText})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = tel.Shutdown(context.Background()) })
	if got := tel.LogHandler(&buf, text); got != slog.Handler(text) {
		t.Fatalf("text format wrapped the handler: %T", got)
	}

	// json: SafeHandler in front of the JSON handler.
	tel2, err := telemetry.Init(context.Background(), telemetry.Config{SamplerRatio: 1, LogFormat: telemetry.LogFormatJSON})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = tel2.Shutdown(context.Background()) })
	buf.Reset()
	slog.New(tel2.LogHandler(&buf, text)).Info("hello", "channel", chanUUID)
	if !strings.Contains(buf.String(), `"msg":"hello"`) || strings.Contains(buf.String(), chanUUID) || !strings.Contains(buf.String(), `"channel_id":"0"`) {
		t.Fatalf("json output = %s", buf.String())
	}
}

func TestBodyPolicyPerPatternClass(t *testing.T) {
	// Policy tests, not proofs (R-Q17): each class is removed from a body that
	// holds it. A bare secret that matches no class is NOT asserted absent,
	// because no class targets it.
	token := "v1." + strings.Repeat("A", 22) + "." + strings.Repeat("b", 43)
	for name, tc := range map[string]struct{ body, secret string }{
		"absolute URL":     {"open http://u:pw@h:80/live/u/pw/1.ts?token=zz", "pw@"},
		"URL path":         {"open http://h:80/live/user/hunter2/1.ts", "hunter2"},
		"scheme-less path": {"read /proxy/ts/stream/hunter2/x", "hunter2"},
		"UUID":             {"channel " + chanUUID + " gone", chanUUID},
		"HLS token":        {"session " + token + " idle", token},
		"long hex":         {"digest " + strings.Repeat("ab12", 10), strings.Repeat("ab12", 10)},
		"password=":        {"login password=hunter2 failed", "hunter2"},
		"token=":           {"login token=hunter2&x=1 failed", "hunter2"},
	} {
		var buf bytes.Buffer
		h := telemetry.NewSafeHandler(slog.NewJSONHandler(&buf, nil), telemetry.DefaultRules, nil)
		r := slog.NewRecord(time.Time{}, slog.LevelInfo, tc.body, 0)
		if err := h.Handle(context.Background(), r); err != nil {
			t.Fatal(err)
		}
		if strings.Contains(buf.String(), tc.secret) {
			t.Errorf("%s: %q survived: %s", name, tc.secret, buf.String())
		}
		if !strings.Contains(buf.String(), `"msg"`) {
			t.Errorf("%s: no message: %s", name, buf.String())
		}
	}
}

func TestChannelIDsLifecycle(t *testing.T) {
	var ids telemetry.ChannelIDs
	if ids.Get(chanUUID) != 0 || ids.Len() != 0 {
		t.Fatal("the zero value is not empty")
	}
	ids.Set(chanUUID, 5)
	if ids.Get(chanUUID) != 5 || ids.Len() != 1 {
		t.Fatal("Set did not record")
	}
	ids.Delete(chanUUID)
	if ids.Get(chanUUID) != 0 || ids.Len() != 0 {
		t.Fatal("Delete did not forget")
	}
}
