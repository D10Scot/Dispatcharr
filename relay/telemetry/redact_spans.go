package telemetry

import (
	"context"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

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

// redacted is a ReadOnlySpan whose name, attributes, events, links and status
// are the redacted ones. It embeds the original for everything else (the span
// context, times, resource and scope), so production code does not need the
// SDK's tracetest package.
type redacted struct {
	sdktrace.ReadOnlySpan
	name   string
	attrs  []attribute.KeyValue
	events []sdktrace.Event
	links  []sdktrace.Link
	status sdktrace.Status
}

func (r redacted) Name() string                     { return r.name }
func (r redacted) Attributes() []attribute.KeyValue { return r.attrs }
func (r redacted) Events() []sdktrace.Event         { return r.events }
func (r redacted) Links() []sdktrace.Link           { return r.links }
func (r redacted) Status() sdktrace.Status          { return r.status }
func (r redacted) DroppedAttributes() int           { return 0 }
func (r redacted) DroppedEvents() int               { return 0 }
func (r redacted) DroppedLinks() int                { return 0 }

func redactSpan(s sdktrace.ReadOnlySpan) sdktrace.ReadOnlySpan {
	out := redacted{ReadOnlySpan: s, name: s.Name()}

	if !in(spanNames, out.name) {
		out.name = s.InstrumentationScope().Name
	}

	out.attrs = make([]attribute.KeyValue, 0, len(s.Attributes()))
	for _, kv := range s.Attributes() {
		if validSpanAttr(kv) {
			out.attrs = append(out.attrs, kv)
		}
	}

	var excType string
	out.events = make([]sdktrace.Event, 0, len(s.Events()))
	for _, ev := range s.Events() {
		if ev.Name != "exception" {
			continue
		}
		for _, kv := range ev.Attributes {
			if string(kv.Key) == attrExcType && kv.Value.Type() == attribute.STRING && validTypeName(kv.Value.AsString()) {
				excType = kv.Value.AsString()
				out.events = append(out.events, sdktrace.Event{
					Name:       "exception",
					Attributes: []attribute.KeyValue{kv},
					Time:       ev.Time,
				})
				break
			}
		}
	}

	out.links = make([]sdktrace.Link, len(s.Links()))
	for i, l := range s.Links() {
		out.links[i] = sdktrace.Link{SpanContext: l.SpanContext}
	}

	// The code is kept. The description is the exception type or nothing.
	out.status = sdktrace.Status{Code: s.Status().Code}
	if out.status.Code == codes.Error {
		out.status.Description = excType
	}
	return out
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
		// A member of the closed set of registered mux patterns, nothing else.
		return v.Type() == attribute.STRING && in(routes, v.AsString())
	case AttrStatusCode:
		return v.Type() == attribute.INT64 && v.AsInt64() >= 100 && v.AsInt64() <= 599
	}
	return false
}
