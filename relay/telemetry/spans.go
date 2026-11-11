package telemetry

import (
	"context"
	"net/http"
	"sync"
	"sync/atomic"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/trace"
)

// SpanRef is an opaque span context, stored on a channel when it is published
// so a later failover or operator switch can link back to the tune that
// started it (D11). The zero value is "no span".
type SpanRef struct{ sc trace.SpanContext }

// Valid reports whether the reference names a span.
func (r SpanRef) Valid() bool { return r.sc.IsValid() }

// Span is an opaque, nil-safe handle on one relay span. Its setters take
// typed values and ignore any that is outside the span catalogue's closed
// sets, so a caller cannot put free text on a span.
type Span struct {
	s trace.Span
}

func newSpan(s trace.Span) *Span { return &Span{s: s} }

func (s *Span) set(kv attribute.KeyValue) {
	if s != nil && validSpanAttr(kv) {
		s.s.SetAttributes(kv)
	}
}

// SetChannelID sets mino.channel_id (the numeric id, never the UUID).
func (s *Span) SetChannelID(id int) { s.set(attribute.Int(AttrChannelID, id)) }

// SetOutcome sets mino.outcome.
func (s *Span) SetOutcome(o string) { s.set(attribute.String(AttrOutcome, o)) }

// SetStatusCode sets http.response.status_code.
func (s *Span) SetStatusCode(code int) { s.set(attribute.Int(AttrStatusCode, code)) }

// SetTrigger sets mino.failover.trigger.
func (s *Span) SetTrigger(trigger string) { s.set(attribute.String(AttrTrigger, trigger)) }

// SetError records that the operation failed. Only the innermost error's type
// leaves the process: as the exception event's exception.type and as the
// status description. The error's text is never read.
func (s *Span) SetError(err error) {
	if s == nil || err == nil {
		return
	}
	typ := innermostType(err)
	s.s.AddEvent("exception", trace.WithAttributes(attribute.String(attrExcType, typ)))
	s.s.SetStatus(codes.Error, typ)
}

// Ref returns the span's context for a later link.
func (s *Span) Ref() SpanRef {
	if s == nil {
		return SpanRef{}
	}
	return SpanRef{sc: s.s.SpanContext()}
}

// End ends the span. It is safe to call twice.
func (s *Span) End() {
	if s != nil {
		s.s.End()
	}
}

func (t *Telemetry) start(ctx context.Context, name string, opts ...trace.SpanStartOption) (context.Context, trace.Span) {
	return t.tracer.Start(ctx, name, opts...)
}

// StartAuthorize starts relay.authorize, a client span around Authorize.
func StartAuthorize(ctx context.Context) (context.Context, *Span) {
	ctx, s := Current().start(ctx, SpanAuthorize, trace.WithSpanKind(trace.SpanKindClient))
	return ctx, newSpan(s)
}

// StartNextSource starts relay.next_source, a client span around NextSource.
// reason is one of ReasonTune, ReasonFailover and ReasonResume.
func StartNextSource(ctx context.Context, reason string) (context.Context, *Span) {
	ctx, s := Current().start(ctx, SpanNextSource, trace.WithSpanKind(trace.SpanKindClient))
	sp := newSpan(s)
	sp.set(attribute.String(AttrReason, reason))
	return ctx, sp
}

// StartFailover starts relay.failover as a new root, linked to the tune that
// published the channel when link is valid.
func StartFailover(ctx context.Context, link SpanRef) (context.Context, *Span) {
	opts := []trace.SpanStartOption{trace.WithNewRoot(), trace.WithSpanKind(trace.SpanKindInternal)}
	if link.Valid() {
		opts = append(opts, trace.WithLinks(trace.Link{SpanContext: link.sc}))
	}
	ctx, s := Current().start(ctx, SpanFailover, opts...)
	return ctx, newSpan(s)
}

// StartStreamSwitch starts relay.stream_switch under whatever span ctx holds
// (the caller extracts a trusted traceparent first, with ExtractTraceparent),
// linked to the channel's tune.
func StartStreamSwitch(ctx context.Context, link SpanRef) (context.Context, *Span) {
	opts := []trace.SpanStartOption{trace.WithSpanKind(trace.SpanKindServer)}
	if link.Valid() {
		opts = append(opts, trace.WithLinks(trace.Link{SpanContext: link.sc}))
	}
	ctx, s := Current().start(ctx, SpanStreamSwitch, opts...)
	return ctx, newSpan(s)
}

// InjectTraceparent writes ctx's span context into h as a W3C traceparent.
// It writes nothing when ctx holds no valid span. With OTLP off that is the
// case unless the tune adopted a trusted X-Relay-Traceparent: the no-op tracer
// carries the remote parent's context, and forwarding it is harmless.
func InjectTraceparent(ctx context.Context, h http.Header) {
	propagation.TraceContext{}.Inject(ctx, propagation.HeaderCarrier(h))
}

// ExtractTraceparent returns ctx carrying the remote span context in h's
// traceparent header. Call it ONLY for a request that is already
// authenticated: a client must never be able to choose a trace id.
func ExtractTraceparent(ctx context.Context, h http.Header) context.Context {
	return propagation.TraceContext{}.Extract(ctx, propagation.HeaderCarrier(h))
}

// Tune is the relay.tune span of one request, owned by StreamHandler (D11).
//
// FirstByte, Fail and End share one sync.Once, so whichever comes first is
// terminal and the span completes exactly once. FirstByte ends it as
// streaming with status 200; Fail records the outcome a failure branch chose;
// a deferred End ends it as abandoned if nothing else did.
type Tune struct {
	t    *Telemetry
	span trace.Span
	ctx  context.Context

	once    sync.Once
	chanID  atomic.Int64
	mu      sync.Mutex
	format  string
	joined  *bool
	route   string
	outcome string
	status  int
}

// StartTune starts relay.tune as a server span. trusted must be the result of
// control.IsRelayTrusted for r: only then is X-Relay-Traceparent the parent. A
// bare traceparent on a public route is never extracted, so an untrusted tune
// is a root.
func StartTune(ctx context.Context, r *http.Request, trusted bool) (context.Context, *Tune) {
	t := Current()
	parent := ctx
	if trusted {
		if v := r.Header.Get(HeaderRelayTraceparent); v != "" {
			parent = propagation.TraceContext{}.Extract(ctx, propagation.MapCarrier{"traceparent": v})
		}
	}
	ctx, span := t.start(parent, SpanTune, trace.WithSpanKind(trace.SpanKindServer))
	return ctx, &Tune{t: t, span: span, ctx: ctx}
}

// Ref returns the tune's span context, for a channel to store.
func (u *Tune) Ref() SpanRef { return SpanRef{sc: u.span.SpanContext()} }

// SetChannelID records the channel's numeric id once it is known.
func (u *Tune) SetChannelID(id int) { u.chanID.Store(int64(id)) }

// SetOutputFormat records mpegts, fmp4 or hls.
func (u *Tune) SetOutputFormat(f string) {
	u.mu.Lock()
	u.format = f
	u.mu.Unlock()
}

// SetJoined records whether the tune joined a running channel.
func (u *Tune) SetJoined(joined bool) {
	u.mu.Lock()
	u.joined = &joined
	u.mu.Unlock()
}

// SetRoute records the mux pattern that matched.
func (u *Tune) SetRoute(pattern string) {
	u.mu.Lock()
	u.route = pattern
	u.mu.Unlock()
}

func (u *Tune) labels() (int, string) {
	u.mu.Lock()
	defer u.mu.Unlock()
	return int(u.chanID.Load()), u.format
}

// FirstByte ends the span as streaming with status 200. It is terminal.
func (u *Tune) FirstByte() { u.finish(OutcomeStreaming, http.StatusOK) }

// Fail ends the span with the outcome and status a failure branch chose. It is
// terminal, and a no-op after FirstByte.
func (u *Tune) Fail(outcome string, status int) { u.finish(outcome, status) }

// End ends the span as abandoned if nothing else did. Defer it.
func (u *Tune) End() { u.finish(OutcomeAbandoned, 0) }

func (u *Tune) finish(outcome string, status int) {
	u.once.Do(func() {
		u.mu.Lock()
		u.outcome, u.status = outcome, status
		u.mu.Unlock()
		u.complete()
	})
}

// complete is the one function every terminal path reaches. The completion
// count is taken BEFORE span.End: the SDK's End is idempotent, so a second
// completion could not be seen on the span record.
func (u *Tune) complete() {
	u.t.completion.Add(1)
	u.mu.Lock()
	defer u.mu.Unlock()
	set := func(kv attribute.KeyValue) {
		if validSpanAttr(kv) {
			u.span.SetAttributes(kv)
		}
	}
	if id := int(u.chanID.Load()); id > 0 {
		set(attribute.Int(AttrChannelID, id))
	}
	if u.format != "" {
		set(attribute.String(AttrOutputFormat, u.format))
	}
	if u.joined != nil {
		set(attribute.Bool(AttrTuneJoined, *u.joined))
	}
	if u.route != "" {
		set(attribute.String(AttrRoute, u.route))
	}
	set(attribute.String(AttrOutcome, u.outcome))
	if u.status > 0 {
		set(attribute.Int(AttrStatusCode, u.status))
	}
	u.span.End()
}

// FirstWriteWriter wraps an http.ResponseWriter to end the tune span at the
// first byte a viewer is sent and to count M3 (D11).
//
// It starts DISARMED: while disarmed it only delegates, so an error body
// written before setup succeeded neither ends the span as streaming nor counts
// as media. Arm is called immediately before the first media-path write.
// Once armed, every Write adds its returned n to M3, a partial write
// included, and the first Write with n > 0 calls FirstByte, even when it also
// returns an error because n bytes were accepted. It changes no byte, header
// or status, and exposes Unwrap so http.ResponseController keeps working.
type FirstWriteWriter struct {
	http.ResponseWriter
	tune  *Tune
	t     *Telemetry
	armed atomic.Bool

	mu     sync.Mutex
	set    bool
	chanID int
	format string
}

// NewFirstWriteWriter wraps w. tune may be nil (the HLS handler counts M3
// without a tune span); then SetLabels supplies the M3 labels.
func NewFirstWriteWriter(w http.ResponseWriter, tune *Tune) *FirstWriteWriter {
	return &FirstWriteWriter{ResponseWriter: w, tune: tune, t: Current()}
}

// SetLabels sets the channel id and format M3 is recorded under, overriding
// the tune's.
func (w *FirstWriteWriter) SetLabels(channelID int, format string) {
	w.mu.Lock()
	w.set, w.chanID, w.format = true, channelID, format
	w.mu.Unlock()
}

// Arm marks setup as succeeded.
func (w *FirstWriteWriter) Arm() { w.armed.Store(true) }

// Write delegates, and once armed records what was accepted.
func (w *FirstWriteWriter) Write(p []byte) (int, error) {
	n, err := w.ResponseWriter.Write(p)
	if n > 0 && w.armed.Load() {
		ctx := context.Background()
		id, format := w.labelsNow()
		if w.tune != nil {
			ctx = w.tune.ctx
			w.tune.FirstByte()
		}
		w.t.ClientSent(ctx, id, format, n)
	}
	return n, err
}

func (w *FirstWriteWriter) labelsNow() (int, string) {
	w.mu.Lock()
	set, id, format := w.set, w.chanID, w.format
	w.mu.Unlock()
	if !set && w.tune != nil {
		return w.tune.labels()
	}
	return id, format
}

// Unwrap returns the wrapped writer.
func (w *FirstWriteWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }

// Completions is how many times a Tune's completion path has run on this
// Telemetry. telemetrytest exposes it; production pays one atomic add per tune.
func (t *Telemetry) Completions() int64 { return t.completion.Load() }
