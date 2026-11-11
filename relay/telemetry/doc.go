// Package telemetry is the relay's only OpenTelemetry code (observability
// spec D2, ADR 0011). Every other package records through the typed API here
// and never imports go.opentelemetry.io; depguard holds that line.
//
// What it provides:
//
//   - Config from the environment (D12) and Init, which builds the meter
//     provider with the always-on Prometheus reader, and, only when OTLP is
//     enabled, the tracer and logger providers and the OTLP/HTTP exporters,
//     each behind a redacting boundary (D9);
//   - typed recorders for the catalogue's Go instruments, M1 to M9;
//   - the relay's spans (D11): StartTune, StartAuthorize, StartNextSource,
//     StartFailover and StartStreamSwitch, the opaque Span and SpanRef, and
//     FirstWriteWriter, which ends the tune span at the first byte a viewer is
//     sent and counts M3;
//   - the log handlers (D8, D9): ContextHandler, the JSON handler and
//     SafeHandler, the closed-inventory field filter.
//
// With OTLP off the global tracer provider stays the API's no-op, no exporter
// goroutine starts and no connection is opened; /metrics is served either way.
package telemetry
