package telemetry

import (
	"context"

	"go.opentelemetry.io/otel/attribute"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
)

// redactingMetricExporter validates each data point's attribute values against
// the catalogue's rules before the OTLP exporter sees them. Values are typed
// at the recording call already, so this is the second, authoritative check:
// a point whose attribute fails is dropped, and so is any aggregation the
// catalogue has no instrument for.
type redactingMetricExporter struct {
	sdkmetric.Exporter
}

func newRedactingMetricExporter(inner sdkmetric.Exporter) *redactingMetricExporter {
	return &redactingMetricExporter{Exporter: inner}
}

func (e *redactingMetricExporter) Export(ctx context.Context, rm *metricdata.ResourceMetrics) error {
	out := &metricdata.ResourceMetrics{Resource: rm.Resource}
	for _, sm := range rm.ScopeMetrics {
		kept := metricdata.ScopeMetrics{Scope: sm.Scope}
		for _, m := range sm.Metrics {
			if nm, ok := redactMetric(m); ok {
				kept.Metrics = append(kept.Metrics, nm)
			}
		}
		if len(kept.Metrics) > 0 {
			out.ScopeMetrics = append(out.ScopeMetrics, kept)
		}
	}
	return e.Exporter.Export(ctx, out)
}

func redactMetric(m metricdata.Metrics) (metricdata.Metrics, bool) {
	if !in(metricNames, m.Name) {
		return m, false // D14: the catalogue is the whole list
	}
	switch d := m.Data.(type) {
	case metricdata.Gauge[int64]:
		d.DataPoints = filterPoints(d.DataPoints)
		m.Data = d
	case metricdata.Gauge[float64]:
		d.DataPoints = filterPoints(d.DataPoints)
		m.Data = d
	case metricdata.Sum[int64]:
		d.DataPoints = filterPoints(d.DataPoints)
		m.Data = d
	case metricdata.Sum[float64]:
		d.DataPoints = filterPoints(d.DataPoints)
		m.Data = d
	default:
		return m, false
	}
	return m, true
}

type anyPoint[N int64 | float64] = metricdata.DataPoint[N]

func filterPoints[N int64 | float64](in []anyPoint[N]) []anyPoint[N] {
	out := in[:0:0]
	for _, p := range in {
		if validMetricAttrs(p.Attributes) {
			p.Exemplars = nil // exemplars are off; never forward one
			out = append(out, p)
		}
	}
	return out
}

// overflowKey is the attribute sdk/metric puts on the overflow data point
// (sdk/metric/internal/aggregate/limit.go).
const overflowKey = "otel.metric.overflow"

func validMetricAttrs(set attribute.Set) bool {
	for _, kv := range set.ToSlice() {
		v := kv.Value
		// The SDK's cardinality-limit overflow series (D7 names it in the
		// docs) carries this one boolean attribute and nothing else.
		if string(kv.Key) == overflowKey {
			if v.Type() != attribute.BOOL || !v.AsBool() {
				return false
			}
			continue
		}
		if v.Type() != attribute.STRING {
			return false
		}
		s := v.AsString()
		switch string(kv.Key) {
		case "channel_id", "profile_id":
			if !digits.MatchString(s) {
				return false
			}
		case "kind":
			if !in(kinds, s) {
				return false
			}
		case "format":
			if !in(formats, s) {
				return false
			}
		case "trigger":
			if !in(triggers, s) {
				return false
			}
		case "outcome":
			if !in(failoverOutcomes, s) {
				return false
			}
		case "state":
			if !in(channelStates, s) {
				return false
			}
		default:
			return false
		}
	}
	return true
}
