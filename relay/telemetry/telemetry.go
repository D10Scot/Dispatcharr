package telemetry

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"runtime/debug"
	"sync"
	"sync/atomic"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/prometheus/otlptranslator"
	"go.opentelemetry.io/contrib/bridges/otelslog"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	otelprom "go.opentelemetry.io/otel/exporters/prometheus"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/propagation"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/exemplar"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
	"go.opentelemetry.io/otel/trace/noop"

	"github.com/D10Scot/Dispatcharr/relay/procstat"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// Telemetry is the relay's observability state: the instruments, the span
// factory and the shutdown hooks. Obtain one with Init; Current returns the
// installed one, or an inert one when none is installed.
type Telemetry struct {
	cfg Config

	tracer  trace.Tracer
	ids     *ChannelIDs
	metrics http.Handler

	clientSent metric.Int64Counter
	failovers  metric.Int64Counter

	// Observers set by the packages that own the numbers. The instruments'
	// callbacks read them, so a gauge can be observed before its owner exists.
	channels   atomic.Pointer[func() map[string]int]
	clients    atomic.Pointer[func() []ClientCount]
	hls        atomic.Pointer[func() int]
	rewindUse  atomic.Pointer[func() int64]
	rewindCap  atomic.Pointer[func() (int64, bool)]
	procs      *procstat.Registry
	completion atomic.Int64

	res      *resource.Resource
	mp       *sdkmetric.MeterProvider
	sampler  sdktrace.Sampler
	logs     *sdklog.LoggerProvider
	rules    Rules
	shutdown []func(context.Context) error
	once     sync.Once
}

// ClientCount is one M2 observation: the clients of one channel on one output
// format and profile.
type ClientCount struct {
	ChannelID int
	Format    string
	ProfileID int
	N         int
}

var current atomic.Pointer[Telemetry]

var inert = sync.OnceValue(func() *Telemetry {
	t, err := build(context.Background(), Config{SamplerRatio: 1}, &options{tp: noop.NewTracerProvider()})
	if err != nil { // building against noop providers cannot fail
		panic(err)
	}
	return t
})

// Current returns the Telemetry Init installed, or an inert one whose
// recorders do nothing observable and whose spans are non-recording.
func Current() *Telemetry {
	if t := current.Load(); t != nil {
		return t
	}
	return inert()
}

// Option adjusts Init. The tests in telemetrytest use them; production passes
// none.
type Option func(*options)

type options struct {
	tp      trace.TracerProvider
	readers []sdkmetric.Reader
	procs   *procstat.Registry
	ids     *ChannelIDs
	rules   *Rules
}

// WithTracerProvider makes spans use tp and skips building an OTLP tracer
// provider AND the OTLP metric reader (it is a test seam, not a production
// option). The caller owns tp's shutdown.
func WithTracerProvider(tp trace.TracerProvider) Option { return func(o *options) { o.tp = tp } }

// WithMetricReader adds a reader to the meter provider, beside the Prometheus one.
func WithMetricReader(r sdkmetric.Reader) Option {
	return func(o *options) { o.readers = append(o.readers, r) }
}

// WithProcRegistry replaces procstat.Default as the source of M8 and M9.
func WithProcRegistry(r *procstat.Registry) Option { return func(o *options) { o.procs = r } }

// WithChannelIDs supplies the UUID to numeric id map; the default is empty.
func WithChannelIDs(ids *ChannelIDs) Option { return func(o *options) { o.ids = ids } }

// WithLogRules replaces DefaultRules.
func WithLogRules(r Rules) Option { return func(o *options) { o.rules = &r } }

// Init builds the telemetry for cfg and installs it as Current.
//
// The meter provider always carries the Prometheus reader. The tracer and
// logger providers, the OTLP metric reader and every exporter exist only when
// cfg.OTLP is set; with it unset no goroutine starts, no connection opens and
// the global tracer provider stays the API's no-op.
func Init(ctx context.Context, cfg Config, opts ...Option) (*Telemetry, error) {
	var o options
	for _, opt := range opts {
		opt(&o)
	}

	// Installed before anything is built, so no SDK error reaches the default
	// handler, which prints the error's text. The previous handler is
	// deliberately not restored on a failed Init or in Shutdown: this one logs
	// only the error's type, which is strictly safer than the SDK's default, so
	// leaving it installed can only help.
	otel.SetErrorHandler(otel.ErrorHandlerFunc(handleOTelError))

	t, err := build(ctx, cfg, &o)
	if err != nil {
		return nil, err
	}
	if cfg.OTLP {
		if err := t.startOTLP(ctx, &o); err != nil {
			// Stop what build and the first half of startOTLP started: the
			// meter provider's periodic reader above all.
			_ = t.Shutdown(ctx)
			return nil, err
		}
	}
	current.Store(t)
	return t, nil
}

// handleOTelError is the OTel error handler. Only the type leaves, whatever
// handler is installed: the text of an SDK export error carries the collector
// URL, query string included. The record's context keeps it out of the OTLP
// log sink, so a failing log export does not queue a record about itself.
func handleOTelError(err error) {
	slog.Default().ErrorContext(withoutOTLPLogs(context.Background()), "otel error", "error.type", innermostType(err))
}

func build(ctx context.Context, cfg Config, o *options) (*Telemetry, error) {
	t := &Telemetry{cfg: cfg, ids: o.ids, procs: o.procs, rules: DefaultRules}
	if o.rules != nil {
		t.rules = *o.rules
	}
	if t.ids == nil {
		t.ids = &ChannelIDs{}
	}
	if t.procs == nil {
		t.procs = procstat.Default
	}
	ratio := cfg.SamplerRatio
	if ratio == 0 && !cfg.OTLP {
		ratio = 1
	}
	t.sampler = sdktrace.ParentBased(sdktrace.TraceIDRatioBased(ratio))

	res := buildResource()
	t.res = res

	reg := prometheus.NewRegistry()
	exp, err := otelprom.New(
		otelprom.WithRegisterer(reg),
		otelprom.WithTranslationStrategy(otlptranslator.UnderscoreEscapingWithSuffixes),
		otelprom.WithoutTargetInfo(),
		otelprom.WithoutScopeInfo(),
	)
	if err != nil {
		return nil, fmt.Errorf("telemetry: building the Prometheus exporter: %w", redact.Error(err))
	}
	t.metrics = promhttp.HandlerFor(reg, promhttp.HandlerOpts{})

	mpOpts := []sdkmetric.Option{
		sdkmetric.WithReader(exp),
		sdkmetric.WithResource(res),
		sdkmetric.WithExemplarFilter(exemplar.AlwaysOffFilter),
	}
	for _, r := range o.readers {
		mpOpts = append(mpOpts, sdkmetric.WithReader(r))
	}
	if o.tp == nil && cfg.OTLP && cfg.Metrics {
		mexp, err := otlpmetrichttp.New(ctx)
		if err != nil {
			return nil, fmt.Errorf("telemetry: building the OTLP metric exporter: %w", redact.Error(err))
		}
		mpOpts = append(mpOpts, sdkmetric.WithReader(sdkmetric.NewPeriodicReader(newRedactingMetricExporter(mexp))))
	}
	mp := sdkmetric.NewMeterProvider(mpOpts...)
	t.mp = mp
	t.shutdown = append(t.shutdown, mp.Shutdown)

	if o.tp != nil {
		t.tracer = o.tp.Tracer(ScopeName)
	} else {
		t.tracer = noop.NewTracerProvider().Tracer(ScopeName)
	}
	if err := t.instruments(mp.Meter(ScopeName)); err != nil {
		return nil, err
	}
	return t, nil
}

// startOTLP builds the tracer and logger providers behind the redacting
// exporters. It is called only when OTLP is enabled.
func (t *Telemetry) startOTLP(ctx context.Context, o *options) error {
	res := t.res // the one resource of this Init: one service.instance.id across all signals
	var tp *sdktrace.TracerProvider
	if o.tp == nil && t.cfg.Traces {
		texp, err := otlptracehttp.New(ctx)
		if err != nil {
			return fmt.Errorf("telemetry: building the OTLP trace exporter: %w", redact.Error(err))
		}
		tp = sdktrace.NewTracerProvider(
			sdktrace.WithBatcher(newRedactingSpanExporter(texp)),
			sdktrace.WithResource(res),
			sdktrace.WithSampler(t.sampler),
		)
		t.shutdown = append(t.shutdown, tp.Shutdown)
	}
	if t.cfg.Logs {
		lexp, err := newOTLPLogExporter(ctx)
		if err != nil {
			return fmt.Errorf("telemetry: building the OTLP log exporter: %w", redact.Error(err))
		}
		t.logs = sdklog.NewLoggerProvider(
			sdklog.WithProcessor(sdklog.NewBatchProcessor(newRedactingLogExporter(lexp, t.rules))),
			sdklog.WithResource(res),
		)
		t.shutdown = append(t.shutdown, t.logs.Shutdown)
	}
	// The globals are set only once nothing else can fail, so a failed Init
	// leaves the global tracer provider as it found it.
	if tp != nil {
		otel.SetTracerProvider(tp)
		otel.SetTextMapPropagator(propagation.TraceContext{})
		t.tracer = tp.Tracer(ScopeName)
	}
	return nil
}

// newOTLPLogExporter is otlploghttp.New; a test replaces it to make the last
// step of startOTLP fail.
var newOTLPLogExporter = func(ctx context.Context) (sdklog.Exporter, error) { return otlploghttp.New(ctx) }

// Shutdown flushes and stops everything Init started. The relay calls it with
// a two-second context after the drain.
func (t *Telemetry) Shutdown(ctx context.Context) error {
	var err error
	t.once.Do(func() {
		var errs []error
		for i := len(t.shutdown) - 1; i >= 0; i-- {
			if e := t.shutdown[i](ctx); e != nil {
				errs = append(errs, e)
			}
		}
		current.CompareAndSwap(t, nil)
		err = errors.Join(errs...)
	})
	return err
}

// Metrics is the /metrics handler (D4).
func (t *Telemetry) Metrics() http.Handler { return t.metrics }

// ChannelIDs is the map the relay fills when a channel is published.
func (t *Telemetry) ChannelIDs() *ChannelIDs { return t.ids }

// Config returns the configuration Init was given.
func (t *Telemetry) Config() Config { return t.cfg }

// LogHandler builds the relay's slog handler (D8, D9). text is the existing
// text handler, which is left untouched. For JSON the handler is SafeHandler
// in front of the JSON handler; when the OTLP log signal is on, the otelslog
// bridge is a second sink behind the same SafeHandler. For text, only the
// bridge (when on) sits behind SafeHandler, beside the untouched text handler.
// Either way the bridge is inside SafeHandler, so an OTLP log record carries
// the same channel_id mapping and classification as the JSON line.
func (t *Telemetry) LogHandler(w io.Writer, text slog.Handler) slog.Handler {
	var bridge slog.Handler
	if t.logs != nil {
		bridge = skipMarked{otelslog.NewHandler(ScopeName, otelslog.WithLoggerProvider(t.logs))}
	}
	if t.cfg.LogFormat == LogFormatJSON {
		sinks := []slog.Handler{NewJSONHandler(w, slog.LevelInfo)}
		if bridge != nil {
			sinks = append(sinks, bridge)
		}
		return NewSafeHandler(Fanout(sinks...), t.rules, t.ids)
	}
	if bridge == nil {
		return text
	}
	return Fanout(text, NewSafeHandler(bridge, t.rules, t.ids))
}

type noOTLPLogsKey struct{}

// withoutOTLPLogs marks ctx so a record logged with it skips the OTLP log sink.
func withoutOTLPLogs(ctx context.Context) context.Context {
	return context.WithValue(ctx, noOTLPLogsKey{}, true)
}

// skipMarked drops the records whose context withoutOTLPLogs marked.
type skipMarked struct{ inner slog.Handler }

func (h skipMarked) Enabled(ctx context.Context, l slog.Level) bool {
	return ctx.Value(noOTLPLogsKey{}) == nil && h.inner.Enabled(ctx, l)
}

func (h skipMarked) Handle(ctx context.Context, r slog.Record) error {
	if ctx.Value(noOTLPLogsKey{}) != nil {
		return nil
	}
	return h.inner.Handle(ctx, r)
}

func (h skipMarked) WithAttrs(attrs []slog.Attr) slog.Handler {
	return skipMarked{h.inner.WithAttrs(attrs)}
}

func (h skipMarked) WithGroup(name string) slog.Handler { return skipMarked{h.inner.WithGroup(name)} }

func buildResource() *resource.Resource {
	attrs := []attribute.KeyValue{
		attribute.String("service.name", ServiceName),
		attribute.String("mino.program", Program),
		attribute.String("service.instance.id", instanceID()),
	}
	if bi, ok := debug.ReadBuildInfo(); ok && bi.Main.Version != "" && bi.Main.Version != "(devel)" {
		attrs = append(attrs, attribute.String("service.version", bi.Main.Version))
	}
	// Schemaless, so merging over the SDK's environment resource never
	// conflicts on a schema URL. The SDK's WithResource puts the environment
	// (OTEL_RESOURCE_ATTRIBUTES, trusted operator configuration) underneath
	// these, so ours win.
	return resource.NewSchemaless(attrs...)
}

// instanceID is a random UUID per process; it is not configuration and carries
// nothing.
func instanceID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "unknown"
	}
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	h := hex.EncodeToString(b[:])
	return h[0:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:]
}
