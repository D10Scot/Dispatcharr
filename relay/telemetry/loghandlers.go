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
// relay log calls take no context, so most lines carry no trace id.
type ContextHandler struct {
	inner slog.Handler
}

// NewContextHandler wraps inner.
func NewContextHandler(inner slog.Handler) *ContextHandler { return &ContextHandler{inner: inner} }

// Enabled reports whether the inner handler is.
func (h *ContextHandler) Enabled(ctx context.Context, l slog.Level) bool {
	return h.inner.Enabled(ctx, l)
}

// Handle adds the fixed and the trace fields, then delegates.
func (h *ContextHandler) Handle(ctx context.Context, r slog.Record) error {
	r.AddAttrs(slog.String("service.name", ServiceName), slog.String("mino.program", Program))
	if sc := trace.SpanContextFromContext(ctx); sc.IsValid() {
		r.AddAttrs(slog.String("trace_id", sc.TraceID().String()), slog.String("span_id", sc.SpanID().String()))
	}
	return h.inner.Handle(ctx, r)
}

// WithAttrs delegates.
func (h *ContextHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return &ContextHandler{inner: h.inner.WithAttrs(attrs)}
}

// WithGroup delegates.
func (h *ContextHandler) WithGroup(name string) slog.Handler {
	return &ContextHandler{inner: h.inner.WithGroup(name)}
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
