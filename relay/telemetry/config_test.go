package telemetry

import (
	"bytes"
	"log/slog"
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
	tel, err := build(Config{SamplerRatio: 0.25}, &options{})
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
