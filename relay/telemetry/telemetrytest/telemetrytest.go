// Package telemetrytest is the test-only recording side of relay/telemetry
// (observability spec D11, finding 7). Tests in relay/httpapi, relay/channel
// and relay/control import it and the standard library, never OpenTelemetry,
// so depguard's otel-confined rule holds for test files too. It sits inside
// that rule's exempt path and is never linked into the binary.
package telemetrytest

import (
	"context"
	"fmt"
	"sort"
	"testing"
	"time"

	"go.opentelemetry.io/otel/attribute"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"

	"github.com/D10Scot/Dispatcharr/relay/procstat"
	"github.com/D10Scot/Dispatcharr/relay/telemetry"
)

// Span is a recorded span in stdlib types.
type Span struct {
	Name         string
	TraceID      string
	SpanID       string
	ParentSpanID string
	// Links holds the span id of each linked span.
	Links       []string
	Attrs       map[string]any
	Status      string // "unset", "error" or "ok"
	Description string
	Ended       bool
}

// Point is one metric data point.
type Point struct {
	Name  string
	Attrs map[string]any
	Value float64
	// Start and Time bound the point; a cumulative series' Start says when the
	// counter epoch began.
	Start, Time time.Time
}

// Recorder holds what an installed telemetry recorded.
type Recorder struct {
	T      *telemetry.Telemetry
	tb     testing.TB
	spans  *tracetest.SpanRecorder
	reader *sdkmetric.ManualReader
}

// Install installs a recording tracer provider and a manual metric reader as
// telemetry.Current for the test's duration. Extra options (a procstat
// registry, a ChannelIDs) are passed to telemetry.Init.
//
// It is NOT parallel-safe: telemetry.Current and the OTel error handler are
// process globals, so two tests that call Install under t.Parallel() would
// record each other's spans and points.
func Install(t testing.TB, opts ...telemetry.Option) *Recorder {
	t.Helper()
	sr := tracetest.NewSpanRecorder()
	tp := sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(sr), sdktrace.WithSampler(sdktrace.AlwaysSample()))
	reader := sdkmetric.NewManualReader()
	all := append([]telemetry.Option{telemetry.WithTracerProvider(tp), telemetry.WithMetricReader(reader)}, opts...)
	tel, err := telemetry.Init(context.Background(), telemetry.Config{SamplerRatio: 1, LogFormat: telemetry.LogFormatText}, all...)
	if err != nil {
		t.Fatalf("telemetrytest: Init: %v", err)
	}
	t.Cleanup(func() {
		_ = tel.Shutdown(context.Background())
		_ = tp.Shutdown(context.Background())
	})
	return &Recorder{T: tel, tb: t, spans: sr, reader: reader}
}

// Spans returns every span started, ended or not, in start order.
func (r *Recorder) Spans() []Span {
	ended := map[string]bool{}
	for _, s := range r.spans.Ended() {
		ended[s.SpanContext().SpanID().String()] = true
	}
	var out []Span
	for _, s := range r.spans.Started() {
		sp := Span{
			Name:         s.Name(),
			TraceID:      s.SpanContext().TraceID().String(),
			SpanID:       s.SpanContext().SpanID().String(),
			ParentSpanID: "",
			Attrs:        map[string]any{},
			Status:       "unset",
			Ended:        ended[s.SpanContext().SpanID().String()],
		}
		if p := s.Parent(); p.IsValid() {
			sp.ParentSpanID = p.SpanID().String()
		}
		for _, l := range s.Links() {
			sp.Links = append(sp.Links, l.SpanContext.SpanID().String())
		}
		for _, kv := range s.Attributes() {
			sp.Attrs[string(kv.Key)] = kv.Value.AsInterface()
		}
		switch s.Status().Code.String() {
		case "Error":
			sp.Status = "error"
		case "Ok":
			sp.Status = "ok"
		}
		sp.Description = s.Status().Description
		out = append(out, sp)
	}
	return out
}

// Span returns the first span named name, or ok=false.
func (r *Recorder) Span(name string) (Span, bool) {
	for _, s := range r.Spans() {
		if s.Name == name {
			return s, true
		}
	}
	return Span{}, false
}

// Points collects the manual reader and returns the data points of the
// instrument called name (the OTel name, e.g. "mino_relay_client_sent"). A
// failed collection fails the test: an empty result must mean "nothing was
// recorded", never "nothing could be read", or an oracle such as M3 = 0 would
// pass on a broken reader.
func (r *Recorder) Points(name string) []Point {
	rm, ok := r.collect()
	if !ok {
		return nil
	}
	var out []Point
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			if m.Name != name {
				continue
			}
			switch d := m.Data.(type) {
			case metricdata.Sum[int64]:
				for _, p := range d.DataPoints {
					out = append(out, point(name, p.Attributes, float64(p.Value), p.StartTime, p.Time))
				}
			case metricdata.Sum[float64]:
				for _, p := range d.DataPoints {
					out = append(out, point(name, p.Attributes, p.Value, p.StartTime, p.Time))
				}
			case metricdata.Gauge[int64]:
				for _, p := range d.DataPoints {
					out = append(out, point(name, p.Attributes, float64(p.Value), p.StartTime, p.Time))
				}
			case metricdata.Gauge[float64]:
				for _, p := range d.DataPoints {
					out = append(out, point(name, p.Attributes, p.Value, p.StartTime, p.Time))
				}
			}
		}
	}
	sort.Slice(out, func(i, j int) bool { return attrKey(out[i].Attrs) < attrKey(out[j].Attrs) })
	return out
}

// Exemplars returns how many exemplars the collected points of name carry.
func (r *Recorder) Exemplars(name string) int {
	rm, ok := r.collect()
	if !ok {
		return -1
	}
	n := 0
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			if m.Name != name {
				continue
			}
			switch d := m.Data.(type) {
			case metricdata.Sum[int64]:
				for _, p := range d.DataPoints {
					n += len(p.Exemplars)
				}
			case metricdata.Sum[float64]:
				for _, p := range d.DataPoints {
					n += len(p.Exemplars)
				}
			}
		}
	}
	return n
}

// collect reads the manual reader once, failing the test on an error.
func (r *Recorder) collect() (metricdata.ResourceMetrics, bool) {
	r.tb.Helper()
	var rm metricdata.ResourceMetrics
	if err := r.reader.Collect(context.Background(), &rm); err != nil {
		r.tb.Errorf("telemetrytest: collecting metrics failed, so no figure can be read: %v", err)
		return rm, false
	}
	return rm, true
}

// Sum is the total value of name's points. Like Points, it fails the test
// when the collection fails.
func (r *Recorder) Sum(name string) float64 {
	var total float64
	for _, p := range r.Points(name) {
		total += p.Value
	}
	return total
}

// TuneCompletions is how many times a Tune's completion path ran (round 5):
// the span record cannot be the oracle because the SDK's End is idempotent.
func (r *Recorder) TuneCompletions() int { return int(r.T.Completions()) }

// Traceparent builds a W3C traceparent header value for a sampled span.
func Traceparent(traceID, spanID string) string { return "00-" + traceID + "-" + spanID + "-01" }

// NewProcRegistry returns an empty registry over src for WithProcRegistry.
func NewProcRegistry(src procstat.Source) *procstat.Registry { return procstat.NewRegistry(src) }

func point(name string, set attribute.Set, v float64, start, at time.Time) Point {
	attrs := map[string]any{}
	for _, kv := range set.ToSlice() {
		attrs[string(kv.Key)] = kv.Value.AsInterface()
	}
	return Point{Name: name, Attrs: attrs, Value: v, Start: start, Time: at}
}

func attrKey(m map[string]any) string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	s := ""
	for _, k := range keys {
		s += k + "=" + toString(m[k]) + ";"
	}
	return s
}

func toString(v any) string {
	if x, ok := v.(string); ok {
		return x
	}
	return fmt.Sprint(v)
}
