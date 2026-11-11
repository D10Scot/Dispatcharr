package telemetry

import (
	"context"
	"regexp"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

var routePattern = regexp.MustCompile(`^(?:[A-Z]+ )?/[A-Za-z0-9_{}./$~-]{0,200}$`)

// redactingSpanExporter is D9's Go span boundary. Span names come from a
// closed set; attributes are the span catalogue's typed keys, each validated
// again here; events carry exception.type only; the status description is
// replaced by that type; links keep their span context and lose their
// attributes. No otelhttp is used: two XC routes carry the password in the
// path.
type redactingSpanExporter struct {
	inner sdktrace.SpanExporter
}

func newRedactingSpanExporter(inner sdktrace.SpanExporter) *redactingSpanExporter {
	return &redactingSpanExporter{inner: inner}
}

func (e *redactingSpanExporter) ExportSpans(ctx context.Context, spans []sdktrace.ReadOnlySpan) error {
	out := make([]sdktrace.ReadOnlySpan, 0, len(spans))
	for _, s := range spans {
		out = append(out, redactSpan(s))
	}
	return e.inner.ExportSpans(ctx, out)
}

func (e *redactingSpanExporter) Shutdown(ctx context.Context) error { return e.inner.Shutdown(ctx) }

func redactSpan(s sdktrace.ReadOnlySpan) sdktrace.ReadOnlySpan {
	stub := tracetest.SpanStubFromReadOnlySpan(s)

	if !in(spanNames, stub.Name) {
		stub.Name = stub.InstrumentationScope.Name
	}

	attrs := make([]attribute.KeyValue, 0, len(stub.Attributes))
	for _, kv := range stub.Attributes {
		if validSpanAttr(kv) {
			attrs = append(attrs, kv)
		}
	}
	stub.Attributes = attrs

	var excType string
	events := make([]sdktrace.Event, 0, len(stub.Events))
	for _, ev := range stub.Events {
		if ev.Name != "exception" {
			continue
		}
		for _, kv := range ev.Attributes {
			if string(kv.Key) == attrExcType && kv.Value.Type() == attribute.STRING && validTypeName(kv.Value.AsString()) {
				excType = kv.Value.AsString()
				events = append(events, sdktrace.Event{
					Name:       "exception",
					Attributes: []attribute.KeyValue{kv},
					Time:       ev.Time,
				})
				break
			}
		}
	}
	stub.Events = events

	links := make([]sdktrace.Link, len(stub.Links))
	for i, l := range stub.Links {
		links[i] = sdktrace.Link{SpanContext: l.SpanContext}
	}
	stub.Links = links

	// The code is kept. The description is the exception type or nothing.
	stub.Status = sdktrace.Status{Code: stub.Status.Code}
	if stub.Status.Code == codes.Error {
		stub.Status.Description = excType
	}
	return stub.Snapshot()
}

func validTypeName(s string) bool {
	return typeNamePattern.MatchString(s) && !uuidPattern.MatchString(s)
}

// validSpanAttr is the Go allowlist: the key must be one of the catalogue's
// and the value must match that key's rule. A value that fails is dropped,
// never rewritten.
func validSpanAttr(kv attribute.KeyValue) bool {
	v := kv.Value
	switch string(kv.Key) {
	case AttrChannelID:
		return v.Type() == attribute.INT64 && v.AsInt64() >= 0
	case AttrOutputFormat:
		return v.Type() == attribute.STRING && in(formats, v.AsString())
	case AttrTuneJoined:
		return v.Type() == attribute.BOOL
	case AttrOutcome:
		return v.Type() == attribute.STRING && in(outcomes, v.AsString())
	case AttrReason:
		return v.Type() == attribute.STRING && in(reasons, v.AsString())
	case AttrTrigger:
		return v.Type() == attribute.STRING && in(triggers, v.AsString())
	case AttrRoute:
		// The mux pattern: placeholders, never captured values. Code, not input.
		return v.Type() == attribute.STRING && routePattern.MatchString(v.AsString()) && !uuidPattern.MatchString(v.AsString())
	case AttrStatusCode:
		return v.Type() == attribute.INT64 && v.AsInt64() >= 100 && v.AsInt64() <= 599
	}
	return false
}
