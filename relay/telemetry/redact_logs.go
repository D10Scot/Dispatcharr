package telemetry

import (
	"context"

	"go.opentelemetry.io/otel/attribute"
	sdklog "go.opentelemetry.io/otel/sdk/log"
)

// redactingLogExporter is the authoritative second pass for OTLP logs (D9).
// It runs on every record: the attributes are cleaned by the same rules
// SafeHandler applies, and the body is scrubbed best effort. That covers a
// record that reached the logger provider without passing SafeHandler.
type redactingLogExporter struct {
	inner sdklog.Exporter
	rules Rules
}

func newRedactingLogExporter(inner sdklog.Exporter, rules Rules) *redactingLogExporter {
	return &redactingLogExporter{inner: inner, rules: rules}
}

func (e *redactingLogExporter) Export(ctx context.Context, records []sdklog.Record) error {
	out := make([]sdklog.Record, 0, len(records))
	for i := range records {
		out = append(out, e.redact(&records[i]))
	}
	return e.inner.Export(ctx, out)
}

func (e *redactingLogExporter) redact(r *sdklog.Record) sdklog.Record {
	c := r.Clone()
	var kept []attribute.KeyValue
	c.WalkAttributes(func(kv attribute.KeyValue) bool {
		if e.rules.classifyExported(string(kv.Key), fromAttribute(kv.Value)) {
			kept = append(kept, kv)
		}
		return true
	})
	c.SetAttributes(kept...)
	body := c.Body()
	if body.Type() == attribute.STRING {
		c.SetBody(attribute.StringValue(scrub(body.AsString())))
	} else {
		c.SetBody(attribute.StringValue(""))
	}
	return c
}

func (e *redactingLogExporter) Shutdown(ctx context.Context) error   { return e.inner.Shutdown(ctx) }
func (e *redactingLogExporter) ForceFlush(ctx context.Context) error { return e.inner.ForceFlush(ctx) }

func fromAttribute(v attribute.Value) val {
	switch v.Type() {
	case attribute.INT64:
		return val{k: vInt, i: v.AsInt64()}
	case attribute.BOOL:
		return val{k: vBool, b: v.AsBool()}
	case attribute.STRING:
		return val{k: vStr, s: v.AsString()}
	default:
		return val{}
	}
}
