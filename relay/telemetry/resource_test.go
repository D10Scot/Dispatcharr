package telemetry

import (
	"context"
	"regexp"
	"testing"

	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

func TestOurResourceAttributesWinOverTheEnvironmentAndTheRestPassThrough(t *testing.T) {
	t.Setenv("OTEL_RESOURCE_ATTRIBUTES", "service.name=evil,mino.program=evil,service.instance.id=evil,foo=bar")
	t.Setenv("OTEL_SERVICE_NAME", "evil2")

	sr := tracetest.NewSpanRecorder()
	// WithResource merges resource.Environment() underneath what it is given.
	tp := sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(sr), sdktrace.WithResource(buildResource()))
	t.Cleanup(func() { _ = tp.Shutdown(context.Background()) })
	_, s := tp.Tracer("x").Start(context.Background(), "probe")
	s.End()

	got := map[string]string{}
	for _, kv := range sr.Ended()[0].Resource().Attributes() {
		got[string(kv.Key)] = kv.Value.String()
	}
	if got["service.name"] != ServiceName || got["mino.program"] != Program {
		t.Errorf("fixed attributes lost to the environment: %v", got)
	}
	if got["foo"] != "bar" {
		t.Errorf("OTEL_RESOURCE_ATTRIBUTES (trusted configuration, R-Q18) did not pass through: %v", got)
	}
	if !regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`).MatchString(got["service.instance.id"]) {
		t.Errorf("service.instance.id = %q, want a random v4 UUID", got["service.instance.id"])
	}
}

func TestEachProcessGetsItsOwnInstanceID(t *testing.T) {
	first, second := instanceID(), instanceID()
	if first == second {
		t.Fatal("two calls returned the same instance id")
	}
}
