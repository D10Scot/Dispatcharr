package telemetry_test

import (
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/telemetry"
)

func TestEndpointForLogKeepsOnlySchemeHostAndPort(t *testing.T) {
	for raw, want := range map[string]string{
		"http://collector:4318": "http://collector:4318",
		" https://user:" + sentinel + "@otel.example:443/v1?k=" + sentinel + "#f ": "https://otel.example:443",
		"http://otel.example/prefix/" + sentinel:                                   "http://otel.example",
		"http://[::1]:4318":                                                        "http://[::1]:4318",
		"collector:4318":                                                           "(unparseable)",
		"":                                                                         "(unparseable)",
		"http://%zz":                                                               "(unparseable)",
	} {
		got := telemetry.EndpointForLog(func(name string) string {
			if name == "OTEL_EXPORTER_OTLP_ENDPOINT" {
				return raw
			}
			return ""
		})
		if got != want {
			t.Errorf("EndpointForLog(%q) = %q, want %q", raw, got, want)
		}
	}
}
