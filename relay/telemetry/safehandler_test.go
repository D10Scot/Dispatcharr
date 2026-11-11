package telemetry

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"strings"
	"testing"
	"time"
)

const (
	sentinel = "S3NT1NEL-pw-9d2f"
	chanUUID = "5e171e10-0000-4000-8000-00000000d2f0"
)

// testRules is deliberately NOT DefaultRules: it names the hostile-value
// cases' keys, and "reason" lists a UUID in its enum so UUID rejection is the
// only thing that can stop it.
func testRules() Rules {
	return Rules{
		Keys: map[string]Rule{
			"trigger": {Class: ClassEnum, Enum: TriggerValues},
			"reason":  {Class: ClassEnum, Enum: []string{"degraded_failover", chanUUID}},
			"format":  {Class: ClassProfileKey},
			"stream":  {Class: ClassInt},
			"count":   {Class: ClassInt},
			"ok":      {Class: ClassBool},
			"took":    {Class: ClassDuration},
			"channel": {Class: ClassChannel},
			"error":   {Class: ClassError},
			"err":     {Class: ClassError},
		},
		Groups: map[string]bool{"upstream": true},
	}
}

func testIDs() *ChannelIDs {
	ids := &ChannelIDs{}
	ids.Set(chanUUID, 42)
	return ids
}

// tee sends every record to a raw control handler and a SafeHandler, so a test
// can first assert that the control SAW the secret: a call that never logs
// cannot make a leak test pass.
func tee(rules Rules) (*slog.Logger, *bytes.Buffer, *bytes.Buffer) {
	var raw, safe bytes.Buffer
	h := Fanout(
		slog.NewJSONHandler(&raw, nil),
		NewSafeHandler(slog.NewJSONHandler(&safe, nil), rules, testIDs()),
	)
	return slog.New(h), &raw, &safe
}

// check reports every failed assertion, not just the first.
func check(t *testing.T, safe string, mustHave, mustNotHave []string) {
	t.Helper()
	for _, want := range mustHave {
		if !strings.Contains(safe, want) {
			t.Errorf("POLICY: missing %s in %s", want, safe)
		}
	}
	for _, bad := range mustNotHave {
		if strings.Contains(safe, bad) {
			t.Errorf("LEAK: %q reached the sink: %s", bad, safe)
		}
	}
}

type valuer struct{ v any }

func (l valuer) LogValue() slog.Value { return slog.AnyValue(l.v) }

func TestHostileValuesUnderAllowedKeysAreDropped(t *testing.T) {
	log, raw, safe := tee(testRules())
	log.Info("hostile",
		"trigger", sentinel,
		"format", "mpegts:"+sentinel,
		"format", "mpegts:p9223372036854775808", // one past int64
		"format", "mpegts:p0",
		"format", "mpegts:p01",
		"format", "mpegts:p-1",
		"format", "mpegts:p"+strings.Repeat("9", 20),
		"format", "avi:p3",
		"stream", sentinel, // a string under an int key
		"channel", sentinel, // not a UUID
		"count", "7", // a string under an int key
		"reason", chanUUID, // the enum wrongly lists it
	)
	for _, s := range []string{sentinel, chanUUID} {
		if !strings.Contains(raw.String(), s) {
			t.Fatalf("the control never saw %q: the test proves nothing", s)
		}
	}
	check(t, safe.String(), nil, []string{sentinel, chanUUID, "p9223372036854775808", "p01", "p-1", "avi", `"count"`, `"stream"`, `"trigger"`, `"reason"`, "channel_id"})
}

func TestAllowedValuesAreKept(t *testing.T) {
	log, _, safe := tee(testRules())
	log.Info("fine",
		"format", "mpegts:p3",
		"reason", "degraded_failover",
		"trigger", "health_monitor",
		"count", 7,
		"stream", uint64(9),
		"ok", true,
		"took", 1500*1000*1000, // an int under a duration key: dropped below
	)
	log.Info("durations", "took", tick)
	check(t, safe.String(),
		[]string{`"format":"mpegts:p3"`, `"reason":"degraded_failover"`, `"trigger":"health_monitor"`, `"count":7`, `"stream":9`, `"ok":true`, `"took":1000000000`},
		nil)
}

func TestProfileKeyDomain(t *testing.T) {
	for _, ok := range []string{"mpegts", "fmp4", "hls", "mpegts:p3", "mpegts:p999999999", "mpegts:p1000000000", "mpegts:p9223372036854775807", "hls:p12"} {
		log, _, safe := tee(testRules())
		log.Info("x", "format", ok)
		if !strings.Contains(safe.String(), `"format":"`+ok+`"`) {
			t.Errorf("POLICY: %q was dropped, want kept: %s", ok, safe)
		}
	}
	for _, bad := range []string{"mpegts:p9223372036854775808", "mpegts:p0", "mpegts:p01", "mpegts:p-1", "mpegts:p" + strings.Repeat("1", 20), "avi:p3", "mpegts:" + sentinel, ""} {
		log, _, safe := tee(testRules())
		log.Info("x", "format", bad)
		if strings.Contains(safe.String(), `"format"`) {
			t.Errorf("LEAK: %q was kept: %s", bad, safe)
		}
	}
}

func TestTheChannelClassEmitsTheNumericID(t *testing.T) {
	log, raw, safe := tee(testRules())
	log.Info("channel", "channel", chanUUID)
	if !strings.Contains(raw.String(), chanUUID) {
		t.Fatal("the control never saw the UUID")
	}
	check(t, safe.String(), []string{`"channel_id":"42"`}, []string{chanUUID, `"channel":`})

	// A channel the relay does not know is channel_id "0", never its UUID.
	log, _, safe = tee(testRules())
	log.Info("channel", "channel", "11111111-2222-4333-8444-555555555555")
	check(t, safe.String(), []string{`"channel_id":"0"`}, []string{"11111111"})
}

func TestComputedKeysAStructALogValuerAndWithAreHandled(t *testing.T) {
	log, raw, safe := tee(testRules())
	type carrier struct{ S string }
	log.Info("shapes",
		sentinel+"-key", 1, // a computed key with no rule
		"x", carrier{S: sentinel}, // a nested struct
		"count", valuer{7}, // resolves to a kept int
		"stream", valuer{sentinel}, // resolves to a string under an int key
		"trigger", valuer{valuer{"buffering_timeout"}}, // a chain of valuers
		"error", carrier{S: sentinel}, // a non-error KindAny under an error key
		"m", map[string]string{"k": sentinel},
		"slice", []string{sentinel},
	)
	// With, as a package outside relay/ would call it.
	other := log.With("channel", chanUUID, "bogus", sentinel)
	other.Info("with")
	if !strings.Contains(raw.String(), sentinel) {
		t.Fatal("the control never saw the sentinel")
	}
	check(t, safe.String(),
		[]string{`"count":7`, `"trigger":"buffering_timeout"`, `"channel_id":"42"`},
		[]string{sentinel, chanUUID})
}

func TestGroupsRecurseAndOnlyListedGroupsSurvive(t *testing.T) {
	log, _, safe := tee(testRules())
	log.Info("groups",
		slog.Group("upstream", "count", 7, "stream", sentinel, "channel", chanUUID),
		slog.Group("evil", "count", 8),
		slog.Group("upstream"), // empty
	)
	log.WithGroup("evil").Info("scoped", "count", 9)
	log.WithGroup("upstream").Info("scoped", "count", 10, "stream", sentinel)
	check(t, safe.String(),
		[]string{`"upstream":{"count":7,"channel_id":"42"}`, `"upstream":{"count":10}`},
		[]string{sentinel, chanUUID, `"evil"`, `"count":8`, `"count":9`})
}

func TestAnErrorBecomesItsInnermostTypeNeverItsText(t *testing.T) {
	failing := roundTripFunc(func(*http.Request) (*http.Response, error) { return nil, errors.New("boom") })
	client := &http.Client{Transport: failing}
	_, err := client.Get("http://provider.example/live/user/" + sentinel + "/1.ts?password=" + sentinel) //nolint:noctx,bodyclose // a stub transport
	if err == nil {
		t.Fatal("the stub transport did not fail")
	}
	log, raw, safe := tee(testRules())
	log.Error("fetch failed", "error", err, "err", fmt.Errorf("wrapped: %w", err))
	log.Error("untyped", "other", err) // a key with no error rule
	if !strings.Contains(raw.String(), sentinel) {
		t.Fatal("the control never saw the URL in the error text")
	}
	check(t, safe.String(),
		[]string{`"error.type":"*errors.errorString"`, `"err.type":"*errors.errorString"`},
		[]string{sentinel, "provider.example", `"other`})
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestTheMessageIsScrubbedBestEffort(t *testing.T) {
	log, _, safe := tee(testRules())
	log.Info("fetching http://user:pw@host:8080/live/u/p/1.ts?password=x for " + chanUUID)
	check(t, safe.String(), []string{"http://host:8080/[redacted]", "[uuid]"}, []string{"pw@", "?password", chanUUID})
}

func TestEnabledAndWithAttrsOnADroppedGroupAreInert(t *testing.T) {
	var buf bytes.Buffer
	h := NewSafeHandler(slog.NewJSONHandler(&buf, &slog.HandlerOptions{Level: slog.LevelWarn}), testRules(), testIDs())
	if h.Enabled(context.Background(), slog.LevelInfo) {
		t.Fatal("Enabled must follow the inner handler")
	}
	g := h.WithGroup("evil").WithAttrs([]slog.Attr{slog.Int("count", 1)}).WithGroup("upstream")
	if err := g.Handle(context.Background(), slog.NewRecord(zeroTime, slog.LevelError, "m", 0)); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(buf.String(), "count") {
		t.Fatalf("attrs under an unlisted group leaked: %s", buf.String())
	}
	if h.WithGroup("") != slog.Handler(h) {
		t.Fatal(`WithGroup("") must return the receiver`)
	}
}

func TestUint64PastInt64IsDropped(t *testing.T) {
	log, _, safe := tee(testRules())
	log.Info("big", "count", uint64(1<<63), "stream", uint64(5), "took", 3.5, "ok", url.Values{})
	check(t, safe.String(), []string{`"stream":5`}, []string{`"count"`, `"took"`, `"ok"`})
}

const tick = time.Second

var zeroTime time.Time
