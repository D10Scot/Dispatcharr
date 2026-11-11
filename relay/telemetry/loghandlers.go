package telemetry

import (
	"context"
	"io"
	"log/slog"

	"go.opentelemetry.io/otel/trace"
)

// Resource values the relay's log lines and spans carry (D13).
const (
	ServiceName = "mino-relay"
	Program     = "relay-go"
	// ScopeName is the instrumentation scope of the relay's spans and metrics.
	ScopeName = "mino/relay"
)

// ContextHandler adds service.name and mino.program to every record, and
// trace_id and span_id when the record's context holds a valid span (D8). Most
// relay log calls take no context, so most lines carry no trace id. The time
// is UTC, as the Python half emits it.
//
// It keeps the groups opened on it itself rather than opening them on the
// inner handler, so the fields it adds stay at the top level of the record
// even when a caller logs under a group.
type ContextHandler struct {
	inner  slog.Handler
	frames []frame // groups opened on this handler, outermost first
}

// frame is one open group and the attributes attached inside it.
type frame struct {
	name  string
	attrs []slog.Attr
}

// NewContextHandler wraps inner.
func NewContextHandler(inner slog.Handler) *ContextHandler { return &ContextHandler{inner: inner} }

// Enabled reports whether the inner handler is.
func (h *ContextHandler) Enabled(ctx context.Context, l slog.Level) bool {
	return h.inner.Enabled(ctx, l)
}

// Handle nests the record's attributes in the open groups, adds the fixed and
// the trace fields at the top level, then delegates.
func (h *ContextHandler) Handle(ctx context.Context, r slog.Record) error {
	out := slog.NewRecord(r.Time.UTC(), r.Level, r.Message, r.PC)
	attrs := make([]slog.Attr, 0, r.NumAttrs())
	r.Attrs(func(a slog.Attr) bool {
		attrs = append(attrs, a)
		return true
	})
	for i := len(h.frames) - 1; i >= 0; i-- {
		f := h.frames[i]
		members := append(append([]slog.Attr{}, f.attrs...), attrs...)
		attrs = []slog.Attr{{Key: f.name, Value: slog.GroupValue(members...)}}
	}
	out.AddAttrs(attrs...)
	out.AddAttrs(slog.String("service.name", ServiceName), slog.String("mino.program", Program))
	if sc := trace.SpanContextFromContext(ctx); sc.IsValid() {
		out.AddAttrs(slog.String("trace_id", sc.TraceID().String()), slog.String("span_id", sc.SpanID().String()))
	}
	return h.inner.Handle(ctx, out)
}

// WithAttrs attaches attrs to the innermost open group, or to the inner
// handler when none is open.
func (h *ContextHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	if len(attrs) == 0 {
		return h
	}
	if len(h.frames) == 0 {
		return &ContextHandler{inner: h.inner.WithAttrs(attrs)}
	}
	frames := make([]frame, len(h.frames))
	copy(frames, h.frames)
	last := &frames[len(frames)-1]
	last.attrs = append(append([]slog.Attr{}, last.attrs...), attrs...)
	return &ContextHandler{inner: h.inner, frames: frames}
}

// WithGroup opens a group that only this handler's records are nested in.
func (h *ContextHandler) WithGroup(name string) slog.Handler {
	if name == "" {
		return h
	}
	frames := append(append([]frame{}, h.frames...), frame{name: name})
	return &ContextHandler{inner: h.inner, frames: frames}
}

// NewJSONHandler is the JSON handler of D8: slog's JSONHandler on w behind a
// ContextHandler. It is NOT safe by itself: LogHandler puts SafeHandler in
// front of it.
func NewJSONHandler(w io.Writer, level slog.Leveler) slog.Handler {
	return NewContextHandler(slog.NewJSONHandler(w, &slog.HandlerOptions{Level: level}))
}

// fanout sends each record to every handler.
type fanout []slog.Handler

func (f fanout) Enabled(ctx context.Context, l slog.Level) bool {
	for _, h := range f {
		if h.Enabled(ctx, l) {
			return true
		}
	}
	return false
}

func (f fanout) Handle(ctx context.Context, r slog.Record) error {
	var first error
	for _, h := range f {
		if h.Enabled(ctx, r.Level) {
			if err := h.Handle(ctx, r.Clone()); err != nil && first == nil {
				first = err
			}
		}
	}
	return first
}

func (f fanout) WithAttrs(attrs []slog.Attr) slog.Handler {
	out := make(fanout, len(f))
	for i, h := range f {
		out[i] = h.WithAttrs(attrs)
	}
	return out
}

func (f fanout) WithGroup(name string) slog.Handler {
	out := make(fanout, len(f))
	for i, h := range f {
		out[i] = h.WithGroup(name)
	}
	return out
}

// Fanout combines handlers; a record goes to each one that is enabled.
func Fanout(handlers ...slog.Handler) slog.Handler { return fanout(handlers) }
