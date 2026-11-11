package telemetry

import (
	"log/slog"
	"math"
	"os"
	"strconv"
	"strings"
)

// The environment contract of observability spec D12 and D8.
const (
	envEndpoint    = "OTEL_EXPORTER_OTLP_ENDPOINT"
	envProtocol    = "OTEL_EXPORTER_OTLP_PROTOCOL"
	envSDKDisabled = "OTEL_SDK_DISABLED"
	envSamplerArg  = "OTEL_TRACES_SAMPLER_ARG"
	envLogFormat   = "MINO_LOG_FORMAT"

	protocolHTTPProtobuf = "http/protobuf"

	// LogFormatText and LogFormatJSON are the two values MINO_LOG_FORMAT takes.
	LogFormatText = "text"
	LogFormatJSON = "json"
)

// Config is what the process environment says about telemetry.
type Config struct {
	// OTLP is true when OTLP export is enabled: OTEL_EXPORTER_OTLP_ENDPOINT is
	// set and non-empty, OTEL_SDK_DISABLED is not "true", and no protocol
	// variable names anything but http/protobuf.
	OTLP bool
	// Traces, Metrics and Logs say which signals OTLP exports. They are false
	// when OTLP is off and when OTEL_<SIGNAL>_EXPORTER is "none".
	Traces, Metrics, Logs bool
	// SamplerRatio is OTEL_TRACES_SAMPLER_ARG, 1.0 when unset or invalid.
	SamplerRatio float64
	// LogFormat is LogFormatText or LogFormatJSON.
	LogFormat string
}

// LoadConfig reads the environment through getenv (os.Getenv when nil) and
// writes each warning once to log (slog.Default() when nil). Warnings name the
// variable, never a value that could be a credential.
func LoadConfig(getenv func(string) string, log *slog.Logger) Config {
	if getenv == nil {
		getenv = os.Getenv
	}
	if log == nil {
		log = slog.Default()
	}
	cfg := Config{SamplerRatio: 1.0, LogFormat: LogFormatText}

	switch v := getenv(envLogFormat); v {
	case "", LogFormatText:
	case LogFormatJSON:
		cfg.LogFormat = LogFormatJSON
	default:
		log.Warn("unsupported log format; using text", "variable", envLogFormat, "length", len(v))
	}

	if arg := getenv(envSamplerArg); arg != "" {
		ratio, err := strconv.ParseFloat(arg, 64)
		if err != nil || ratio < 0 || ratio > 1 || math.IsNaN(ratio) {
			log.Warn("unusable sampler argument; sampling everything", "variable", envSamplerArg)
		} else {
			cfg.SamplerRatio = ratio
		}
	}

	if strings.TrimSpace(getenv(envEndpoint)) == "" || getenv(envSDKDisabled) == "true" {
		return cfg
	}
	for _, name := range []string{
		envProtocol,
		"OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
		"OTEL_EXPORTER_OTLP_METRICS_PROTOCOL",
		"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL",
	} {
		if v := getenv(name); v != "" && v != protocolHTTPProtobuf {
			log.Warn("OTLP stays off: only http/protobuf is supported", "variable", name, "supported", protocolHTTPProtobuf)
			return cfg
		}
	}
	cfg.OTLP = true
	cfg.Traces = getenv("OTEL_TRACES_EXPORTER") != "none"
	cfg.Metrics = getenv("OTEL_METRICS_EXPORTER") != "none"
	cfg.Logs = getenv("OTEL_LOGS_EXPORTER") != "none"
	return cfg
}
