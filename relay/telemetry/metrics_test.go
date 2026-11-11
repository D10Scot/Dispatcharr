package telemetry_test

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"regexp"
	"runtime"
	"slices"
	"sort"
	"strings"
	"testing"

	"go.opentelemetry.io/otel"

	"github.com/D10Scot/Dispatcharr/relay/procstat"
	"github.com/D10Scot/Dispatcharr/relay/telemetry"
	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

const sentinel = "S3NT1NEL-pw-9d2f"

// fakeProc is a one-process /proc: group 500, 2 CPU-seconds, 10 pages.
type fakeProc struct{}

func (fakeProc) Snapshot() ([]procstat.Proc, error) {
	return []procstat.Proc{{PID: 500, PGrp: 500, Start: 1, CPUTicks: 200, RSSPages: 10}}, nil
}
func (fakeProc) TicksPerSecond() float64 { return 100 }
func (fakeProc) PageSize() int           { return 4096 }

// installEverything records every catalogue instrument once.
func installEverything(t *testing.T) *telemetrytest.Recorder {
	t.Helper()
	reg := procstat.NewRegistry(fakeProc{})
	reg.Track(500, procstat.Labels{ChannelID: 7, Kind: procstat.KindSource})
	rec := telemetrytest.Install(t, telemetry.WithProcRegistry(reg))
	rec.T.ObserveChannels(func() map[string]int { return map[string]int{"active": 2, "nonsense": 9} })
	rec.T.ObserveClients(func() []telemetry.ClientCount {
		return []telemetry.ClientCount{{ChannelID: 7, Format: "mpegts", ProfileID: 0, N: 3}, {ChannelID: 7, Format: "avi", N: 1}}
	})
	rec.T.ObserveHLSSessions(func() int { return 4 })
	rec.T.ObserveRewind(func() int64 { return 1024 }, func() (int64, bool) { return 4096, true })
	rec.T.ClientSent(context.Background(), 7, "mpegts", 188)
	rec.T.Failover(context.Background(), 7, telemetry.TriggerHealthMonitor, telemetry.OutcomeSwitched)
	return rec
}

func scrape(t *testing.T, h http.Handler) string {
	t.Helper()
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	resp, err := http.Get(srv.URL) //nolint:noctx // a local test server
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	b, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

var seriesLabels = regexp.MustCompile(`^([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\}`)

// families reads a scrape into family -> {type, label keys}.
func families(body string) map[string][2]string {
	out := map[string][2]string{}
	types := map[string]string{}
	keys := map[string]map[string]bool{}
	sc := bufio.NewScanner(strings.NewReader(body))
	for sc.Scan() {
		line := sc.Text()
		if f := strings.Fields(line); len(f) == 4 && f[0] == "#" && f[1] == "TYPE" {
			types[f[2]] = f[3]
			continue
		}
		if m := seriesLabels.FindStringSubmatch(line); m != nil {
			if keys[m[1]] == nil {
				keys[m[1]] = map[string]bool{}
			}
			for _, kv := range strings.Split(m[2], ",") {
				if k, _, ok := strings.Cut(kv, "="); ok {
					keys[m[1]][k] = true
				}
			}
		}
	}
	for fam, typ := range types {
		var ks []string
		for k := range keys[fam] {
			ks = append(ks, k)
		}
		sort.Strings(ks)
		out[fam] = [2]string{typ, strings.Join(ks, ",")}
	}
	return out
}

func TestExpositionMatchesTheCatalogue(t *testing.T) {
	rec := installEverything(t)
	got := families(scrape(t, rec.T.Metrics()))

	want := map[string][2]string{}
	for _, row := range telemetry.CatalogueGo {
		ls := slices.Clone(row.Labels)
		sort.Strings(ls)
		want[row.Family] = [2]string{row.Type, strings.Join(ls, ",")}
	}
	var problems []string
	for fam, w := range want {
		g, ok := got[fam]
		switch {
		case !ok:
			problems = append(problems, fmt.Sprintf("missing family %s", fam))
		case g != w:
			problems = append(problems, fmt.Sprintf("family %s is %v, want %v", fam, g, w))
		}
	}
	for fam := range got {
		if _, ok := want[fam]; !ok {
			problems = append(problems, fmt.Sprintf("unexpected family %s", fam))
		}
	}
	sort.Strings(problems)
	if len(problems) > 0 {
		t.Fatalf("/metrics differs from the catalogue:\n%s", strings.Join(problems, "\n"))
	}
	if len(got) != 9 {
		t.Errorf("%d families, want the nine Go rows M1-M9", len(got))
	}
}

func TestOutOfSetObservationsAreNotExported(t *testing.T) {
	rec := installEverything(t)
	body := scrape(t, rec.T.Metrics())
	for _, bad := range []string{`state="nonsense"`, `format="avi"`} {
		if strings.Contains(body, bad) {
			t.Errorf("%s reached /metrics", bad)
		}
	}
	for _, want := range []string{
		`mino_relay_channels{state="active"} 2`,
		`mino_relay_clients{channel_id="7",format="mpegts",profile_id="0"} 3`,
		`mino_relay_hls_sessions 4`,
		`mino_relay_rewind_disk_usage_bytes 1024`,
		`mino_relay_rewind_disk_limit_bytes 4096`,
		`mino_relay_process_cpu_seconds_total{channel_id="7",kind="source",profile_id="0"} 2`,
		`mino_relay_process_memory_rss_bytes{channel_id="7",kind="source",profile_id="0"} 40960`,
		`mino_relay_client_sent_bytes_total{channel_id="7",format="mpegts"} 188`,
	} {
		if !strings.Contains(body, want) {
			t.Errorf("missing series %q in:\n%s", want, body)
		}
	}
}

func TestAnUnsetRewindCapIsNotObserved(t *testing.T) {
	rec := telemetrytest.Install(t)
	rec.T.ObserveRewind(func() int64 { return 5 }, func() (int64, bool) { return 0, false })
	body := scrape(t, rec.T.Metrics())
	if strings.Contains(body, "rewind_disk_limit") || !strings.Contains(body, "rewind_disk_usage_bytes 5") {
		t.Fatalf("unexpected exposition:\n%s", body)
	}
}

func TestMetricsEndpointCarriesNoResource(t *testing.T) {
	t.Setenv("OTEL_RESOURCE_ATTRIBUTES", "evil.key="+sentinel)
	rec := installEverything(t)
	body := scrape(t, rec.T.Metrics())
	if !strings.Contains(body, "mino_relay_channels") {
		t.Fatalf("empty scrape: %s", body)
	}
	if strings.Contains(body, sentinel) {
		t.Error("LEAK: the sentinel from OTEL_RESOURCE_ATTRIBUTES reached /metrics")
	}
	if strings.Contains(body, "target_info") {
		t.Error("POLICY: a target_info family is exposed")
	}
	if strings.Contains(body, "otel_scope_") {
		t.Error("POLICY: an otel_scope_ label is exposed")
	}
}

func TestExemplarsOff(t *testing.T) {
	rec := telemetrytest.Install(t)
	r := tuneRequest(false, false)
	ctx, tune := telemetry.StartTune(r.Context(), r, false) // sampled: AlwaysSample
	defer tune.End()
	rec.T.ClientSent(ctx, 7, "mpegts", 188)
	rec.T.Failover(ctx, 7, telemetry.TriggerHealthMonitor, telemetry.OutcomeSwitched)
	if got := rec.Sum("mino_relay_client_sent"); got != 188 {
		t.Fatalf("M3 = %v, want 188: nothing was recorded", got)
	}
	if n := rec.Exemplars("mino_relay_client_sent") + rec.Exemplars("mino_relay_failovers"); n != 0 {
		t.Fatalf("%d exemplars exported inside a sampled span, want none", n)
	}
}

func TestOTLPOffInstallsNoProvider(t *testing.T) {
	runtime.GC()
	providerBefore := otel.GetTracerProvider()
	before := runtime.NumGoroutine()

	cfg := telemetry.LoadConfig(func(string) string { return "" }, slog.New(slog.NewTextHandler(io.Discard, nil)))
	tel, err := telemetry.Init(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = tel.Shutdown(context.Background()) })

	if otel.GetTracerProvider() != providerBefore {
		t.Error("Init installed a global tracer provider with OTLP off")
	}
	_, span := otel.GetTracerProvider().Tracer("x").Start(context.Background(), "probe")
	if span.IsRecording() {
		t.Error("the global tracer records with OTLP off")
	}
	r := tuneRequest(false, false)
	ctx, tune := telemetry.StartTune(r.Context(), r, false)
	h := http.Header{}
	telemetry.InjectTraceparent(ctx, h)
	tune.End()
	if h.Get("traceparent") != "" {
		t.Errorf("traceparent injected with OTLP off: %q", h.Get("traceparent"))
	}
	if after := runtime.NumGoroutine(); after != before {
		t.Errorf("goroutines %d -> %d: something started with OTLP off", before, after)
	}
	if body := scrape(t, tel.Metrics()); !strings.Contains(body, "# TYPE") && strings.Contains(body, "mino_") {
		t.Error("the Prometheus handler answered something that is not an exposition")
	}
}

func TestProtocolOtherThanHTTPProtobufStartsNothing(t *testing.T) {
	runtime.GC()
	before := runtime.NumGoroutine()
	cfg := telemetry.LoadConfig(func(k string) string {
		return map[string]string{
			"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:1",
			"OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
		}[k]
	}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	tel, err := telemetry.Init(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = tel.Shutdown(context.Background()) })
	if cfg.OTLP || runtime.NumGoroutine() != before {
		t.Fatalf("OTLP=%v goroutines %d -> %d", cfg.OTLP, before, runtime.NumGoroutine())
	}
}
