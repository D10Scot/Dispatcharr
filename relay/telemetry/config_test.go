package telemetry

import (
	"bytes"
	"context"
	"log/slog"
	"os"
	"strings"
	"testing"
)

func env(m map[string]string) func(string) string { return func(k string) string { return m[k] } }

func capture() (*slog.Logger, *bytes.Buffer) {
	var buf bytes.Buffer
	return slog.New(slog.NewTextHandler(&buf, nil)), &buf
}

func TestOTLPIsOffUnlessAnEndpointIsSet(t *testing.T) {
	for name, m := range map[string]map[string]string{
		"nothing set":     {},
		"blank endpoint":  {envEndpoint: "   "},
		"sdk disabled":    {envEndpoint: "http://c:4318", envSDKDisabled: "true"},
		"signal override": {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://c:4318"},
	} {
		log, _ := capture()
		if cfg := LoadConfig(env(m), log); cfg.OTLP || cfg.Traces || cfg.Metrics || cfg.Logs {
			t.Errorf("%s: OTLP enabled: %+v", name, cfg)
		}
	}
}

func TestAnEndpointEnablesAllThreeSignalsUnlessNone(t *testing.T) {
	log, buf := capture()
	cfg := LoadConfig(env(map[string]string{envEndpoint: "http://c:4318", "OTEL_METRICS_EXPORTER": "none", "OTEL_TRACES_EXPORTER": "otlp"}), log)
	if !cfg.OTLP || !cfg.Traces || cfg.Metrics || !cfg.Logs {
		t.Fatalf("config = %+v", cfg)
	}
	if buf.Len() != 0 {
		t.Fatalf("unexpected warning: %s", buf)
	}
}

func TestProtocolOtherThanHTTPProtobufStaysOff(t *testing.T) {
	for _, name := range []string{
		"OTEL_EXPORTER_OTLP_PROTOCOL",
		"OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
		"OTEL_EXPORTER_OTLP_METRICS_PROTOCOL",
		"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL",
	} {
		log, buf := capture()
		cfg := LoadConfig(env(map[string]string{envEndpoint: "http://c:4318", name: "grpc"}), log)
		if cfg.OTLP {
			t.Errorf("%s=grpc left OTLP on", name)
		}
		if got := buf.String(); strings.Count(got, "level=WARN") != 1 || !strings.Contains(got, name) || !strings.Contains(got, protocolHTTPProtobuf) {
			t.Errorf("%s: warning = %q, want one naming the variable and the supported value", name, got)
		}
	}
	log, buf := capture()
	if cfg := LoadConfig(env(map[string]string{envEndpoint: "http://c:4318", envProtocol: "http/protobuf"}), log); !cfg.OTLP || buf.Len() != 0 {
		t.Fatalf("http/protobuf must be accepted silently: %+v %s", cfg, buf)
	}
}

func TestSamplerArg(t *testing.T) {
	for _, tc := range []struct {
		arg      string
		want     float64
		warnings int
	}{
		{"", 1.0, 0},
		{"0.25", 0.25, 0},
		{"0", 0, 0},
		{"x", 1.0, 1},
		{"1.5", 1.0, 1},
		{"-0.1", 1.0, 1},
		{"NaN", 1.0, 1},
	} {
		log, buf := capture()
		cfg := LoadConfig(env(map[string]string{envSamplerArg: tc.arg}), log)
		if cfg.SamplerRatio != tc.want {
			t.Errorf("arg %q: ratio = %v, want %v", tc.arg, cfg.SamplerRatio, tc.want)
		}
		if got := strings.Count(buf.String(), "level=WARN"); got != tc.warnings {
			t.Errorf("arg %q: %d warnings, want %d (%s)", tc.arg, got, tc.warnings, buf)
		}
		if tc.arg == "x" && strings.Contains(buf.String(), "x\"") {
			t.Errorf("the warning echoed the value: %s", buf)
		}
	}
}

func TestTheSamplerIsParentBasedOverTheRatio(t *testing.T) {
	tel, err := build(context.Background(), Config{SamplerRatio: 0.25}, &options{})
	if err != nil {
		t.Fatal(err)
	}
	d := tel.sampler.Description()
	if !strings.Contains(d, "ParentBased") || !strings.Contains(d, "TraceIDRatioBased{0.25}") {
		t.Fatalf("sampler = %s", d)
	}
}

func TestLogFormat(t *testing.T) {
	for _, tc := range []struct {
		v        string
		want     string
		warnings int
	}{
		{"", LogFormatText, 0},
		{"text", LogFormatText, 0},
		{"json", LogFormatJSON, 0},
		{"JSON-sekret", LogFormatText, 1},
	} {
		log, buf := capture()
		cfg := LoadConfig(env(map[string]string{envLogFormat: tc.v}), log)
		if cfg.LogFormat != tc.want {
			t.Errorf("%q: format = %q, want %q", tc.v, cfg.LogFormat, tc.want)
		}
		if got := strings.Count(buf.String(), "level=WARN"); got != tc.warnings {
			t.Errorf("%q: %d warnings, want %d", tc.v, got, tc.warnings)
		}
		if strings.Contains(buf.String(), "sekret") {
			t.Errorf("the warning echoed the value: %s", buf)
		}
		if tc.warnings == 1 && !strings.Contains(buf.String(), "length=11") {
			t.Errorf("the warning should carry only the length: %s", buf)
		}
	}
}

func TestLoadConfigDefaultsToTheProcessEnvironment(t *testing.T) {
	t.Setenv(envEndpoint, "http://c:4318")
	if cfg := LoadConfig(nil, nil); !cfg.OTLP {
		t.Fatalf("os.Getenv was not consulted: %+v", cfg)
	}
}

func TestTheTracesAndLogsSignalsCanEachBeSwitchedOff(t *testing.T) {
	for _, tc := range []struct {
		name                  string
		traces, metrics, logs bool
	}{
		{"OTEL_TRACES_EXPORTER", false, true, true},
		{"OTEL_LOGS_EXPORTER", true, true, false},
		{"OTEL_METRICS_EXPORTER", true, false, true},
	} {
		log, _ := capture()
		cfg := LoadConfig(env(map[string]string{envEndpoint: "http://c:4318", tc.name: "none"}), log)
		if !cfg.OTLP || cfg.Traces != tc.traces || cfg.Metrics != tc.metrics || cfg.Logs != tc.logs {
			t.Errorf("%s=none: config = %+v", tc.name, cfg)
		}
	}
}

func TestSDKDisabledIsTrimmedAndCaseInsensitiveAsInPython(t *testing.T) {
	for _, v := range []string{"true", "TRUE", " True "} {
		log, _ := capture()
		if cfg := LoadConfig(env(map[string]string{envEndpoint: "http://c:4318", envSDKDisabled: v}), log); cfg.OTLP {
			t.Errorf("OTEL_SDK_DISABLED=%q left OTLP on", v)
		}
	}
	log, _ := capture()
	if cfg := LoadConfig(env(map[string]string{envEndpoint: "http://c:4318", envSDKDisabled: "false"}), log); !cfg.OTLP {
		t.Error("OTEL_SDK_DISABLED=false turned OTLP off")
	}
}

// Round-3 finding 1. The trace and metric exporters print a value they refuse
// to stderr through OTel's internal logger, out of reach of every handler. So
// LoadConfig refuses it first: OTLP stays off, and one warning names the
// variable and never the value.
func TestAMalformedOTLPVariableKeepsOTLPOffAndIsNamedNeverEchoed(t *testing.T) {
	missing := t.TempDir() + "/" + sentinel + ".pem"
	for name, v := range map[string]string{
		"OTEL_EXPORTER_OTLP_HEADERS":                    "Authorization: Bearer " + sentinel,
		"OTEL_EXPORTER_OTLP_TRACES_HEADERS":             "Authorization=Bearer%zz" + sentinel,
		"OTEL_EXPORTER_OTLP_METRICS_HEADERS":            "Author ization=" + sentinel,
		"OTEL_EXPORTER_OTLP_LOGS_HEADERS":               "a=b," + sentinel,
		"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT":            "http://user:" + sentinel + "@c:port%zz/",
		"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT":           "http://user:" + sentinel + "@c:port%zz/",
		"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT":              "http://user:" + sentinel + "@c:port%zz/",
		"OTEL_EXPORTER_OTLP_TIMEOUT":                    sentinel,
		"OTEL_EXPORTER_OTLP_METRICS_TIMEOUT":            "1.5",
		"OTEL_EXPORTER_OTLP_CERTIFICATE":                missing,
		"OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE":         missing,
		"OTEL_METRIC_EXPORT_INTERVAL":                   sentinel,
		"OTEL_METRIC_EXPORT_TIMEOUT":                    "-5",
		"OTEL_EXPORTER_OTLP_METRICS_CLIENT_CERTIFICATE": missing,
	} {
		m := map[string]string{envEndpoint: "http://c:4318", name: v}
		if name == "OTEL_EXPORTER_OTLP_METRICS_CLIENT_CERTIFICATE" {
			m["OTEL_EXPORTER_OTLP_METRICS_CLIENT_KEY"] = os.Args[0] // readable: the certificate is the bad half
		}
		log, buf := capture()
		cfg := LoadConfig(env(m), log)
		if cfg.OTLP {
			t.Errorf("%s: a malformed value left OTLP on", name)
		}
		if got := buf.String(); strings.Count(got, "level=WARN") != 1 || !strings.Contains(got, "variable="+name+"\n") {
			t.Errorf("%s: warning = %q, want one naming the variable", name, got)
		}
		if strings.Contains(buf.String(), sentinel) {
			t.Errorf("LEAK: %s's value was echoed: %s", name, buf)
		}
	}
	// The endpoint itself, which also enables OTLP.
	log, buf := capture()
	if cfg := LoadConfig(env(map[string]string{envEndpoint: "http://user:" + sentinel + "@c:port%zz/"}), log); cfg.OTLP || strings.Contains(buf.String(), sentinel) || !strings.Contains(buf.String(), envEndpoint) {
		t.Errorf("a malformed %s: OTLP=%v, warning %q", envEndpoint, cfg.OTLP, buf)
	}
}

// The values the exporters accept are accepted silently, so the
// pre-validation never switches off a working configuration.
func TestWellFormedOTLPVariablesAreAccepted(t *testing.T) {
	readable := os.Args[0]
	log, buf := capture()
	cfg := LoadConfig(env(map[string]string{
		envEndpoint:                                  " http://c:4318/base ",
		"OTEL_EXPORTER_OTLP_HEADERS":                 " Authorization=Bearer%20abc , x-tenant = t1 ",
		"OTEL_EXPORTER_OTLP_TRACES_HEADERS":          "k=",
		"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT":         "https://c:4318/v1/traces",
		"OTEL_EXPORTER_OTLP_TIMEOUT":                 "10000",
		"OTEL_EXPORTER_OTLP_CERTIFICATE":             readable,
		"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE":      readable,
		"OTEL_EXPORTER_OTLP_CLIENT_KEY":              readable,
		"OTEL_EXPORTER_OTLP_LOGS_CLIENT_CERTIFICATE": "/nonexistent/without/its/key",
		"OTEL_METRIC_EXPORT_INTERVAL":                "60000",
		"OTEL_METRIC_EXPORT_TIMEOUT":                 "30000",
	}), log)
	if !cfg.OTLP || buf.Len() != 0 {
		t.Fatalf("a well-formed configuration was refused: %+v %s", cfg, buf)
	}
}
