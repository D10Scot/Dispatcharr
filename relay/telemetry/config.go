package telemetry

import (
	"log/slog"
	"math"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
	"unicode"
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
	// set and non-empty, OTEL_SDK_DISABLED is not "true" (trimmed, any case),
	// no protocol variable names anything but http/protobuf, and every OTLP
	// header, endpoint, timeout, certificate and metric-interval variable is one
	// the exporters accept (see malformedOTLPVariable).
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

	if strings.TrimSpace(getenv(envEndpoint)) == "" || strings.EqualFold(strings.TrimSpace(getenv(envSDKDisabled)), "true") {
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
	if name := malformedOTLPVariable(getenv); name != "" {
		log.Warn("OTLP stays off: a variable is malformed", "variable", name)
		return cfg
	}
	cfg.OTLP = true
	cfg.Traces = getenv("OTEL_TRACES_EXPORTER") != "none"
	cfg.Metrics = getenv("OTEL_METRICS_EXPORTER") != "none"
	cfg.Logs = getenv("OTEL_LOGS_EXPORTER") != "none"
	return cfg
}

// The OTLP variables the exporters parse. Each name is the namespace followed
// by one of the signal infixes, "" for the generic variable.
const otlpNamespace = "OTEL_EXPORTER_OTLP_"

var otlpSignals = []string{"", "TRACES_", "METRICS_", "LOGS_"}

// malformedOTLPVariable returns the name of the first OTLP variable the
// exporters would refuse, or "" when every one is usable.
//
// The trace and metric exporters (v1.47.0) report a refused value through
// OpenTelemetry's internal logger, which writes the raw value to stderr from a
// private log.Logger that neither slog, SafeHandler nor the installed error
// handler can reach. A header value is a credential and an endpoint may carry
// userinfo, so the relay refuses the value here, before any exporter sees it,
// and names only the variable. Each check is at least as strict as the
// exporter's own parse (internal/envconfig and sdk/metric/env.go), so a value
// that passes cannot reach one of those log calls.
func malformedOTLPVariable(getenv func(string) string) string {
	for _, sig := range otlpSignals {
		if name := otlpNamespace + sig + "HEADERS"; !validOTLPHeaders(getenv(name)) {
			return name
		}
		if name := otlpNamespace + sig + "ENDPOINT"; !validOTLPEndpoint(getenv(name)) {
			return name
		}
		if name := otlpNamespace + sig + "TIMEOUT"; !validOTLPTimeout(getenv(name)) {
			return name
		}
		if name := otlpNamespace + sig + "CERTIFICATE"; !readableFile(getenv(name)) {
			return name
		}
		// The exporters read the client pair only when both are set.
		certName, keyName := otlpNamespace+sig+"CLIENT_CERTIFICATE", otlpNamespace+sig+"CLIENT_KEY"
		if c, k := strings.TrimSpace(getenv(certName)), strings.TrimSpace(getenv(keyName)); c != "" && k != "" {
			if !readableFile(c) {
				return certName
			}
			if !readableFile(k) {
				return keyName
			}
		}
	}
	for _, name := range []string{"OTEL_METRIC_EXPORT_INTERVAL", "OTEL_METRIC_EXPORT_TIMEOUT"} {
		if !validMetricInterval(getenv(name)) {
			return name
		}
	}
	return ""
}

// validOTLPHeaders mirrors envconfig's stringToHeader: comma-separated items,
// each with an "=", a non-empty token key and a value url.PathUnescape
// accepts. An empty variable is unset.
func validOTLPHeaders(v string) bool {
	v = strings.TrimSpace(v)
	if v == "" {
		return true
	}
	for item := range strings.SplitSeq(v, ",") {
		key, val, found := strings.Cut(item, "=")
		if !found || !validHeaderKey(strings.TrimSpace(key)) {
			return false
		}
		if _, err := url.PathUnescape(val); err != nil {
			return false
		}
	}
	return true
}

// validHeaderKey is envconfig's isValidHeaderKey: an RFC 7230 token.
func validHeaderKey(key string) bool {
	if key == "" {
		return false
	}
	for _, c := range key {
		if c > unicode.MaxASCII {
			return false
		}
		if unicode.IsLetter(c) || unicode.IsDigit(c) || strings.ContainsRune("!#$%&'*+-.^_`|~", c) {
			continue
		}
		return false
	}
	return true
}

func validOTLPEndpoint(v string) bool {
	v = strings.TrimSpace(v)
	if v == "" {
		return true
	}
	_, err := url.Parse(v)
	return err == nil
}

// validOTLPTimeout is envconfig's WithDuration: an integer number of
// milliseconds.
func validOTLPTimeout(v string) bool {
	v = strings.TrimSpace(v)
	if v == "" {
		return true
	}
	_, err := strconv.Atoi(v)
	return err == nil
}

// validMetricInterval is sdk/metric's envDuration: the raw value, untrimmed,
// a positive base-10 count of milliseconds that fits a time.Duration.
func validMetricInterval(v string) bool {
	if v == "" {
		return true
	}
	d, err := strconv.ParseInt(v, 10, 64)
	return err == nil && d > 0 && d <= int64(time.Duration(math.MaxInt64)/time.Millisecond)
}

// readableFile mirrors the exporters' os.ReadFile of a certificate or key
// path; a failed read would log the path with the error.
func readableFile(path string) bool {
	path = strings.TrimSpace(path)
	if path == "" {
		return true
	}
	_, err := os.ReadFile(path) //nolint:gosec // an operator-configured certificate path, read as the exporter will
	return err == nil
}

// EndpointForLog is OTEL_EXPORTER_OTLP_ENDPOINT as scheme://host[:port] only:
// no userinfo, path, query or fragment (D12). It is what the one INFO line
// main writes when OTLP export starts may name, and it mirrors the Python
// bootstrap's endpoint_for_log. An endpoint with no scheme or host renders as
// "(unparseable)" rather than as any part of the value.
func EndpointForLog(getenv func(string) string) string {
	if getenv == nil {
		getenv = os.Getenv
	}
	u, err := url.Parse(strings.TrimSpace(getenv(envEndpoint)))
	if err != nil || u.Scheme == "" || u.Hostname() == "" {
		return "(unparseable)"
	}
	host := u.Hostname()
	if strings.Contains(host, ":") {
		host = "[" + host + "]"
	}
	if port := u.Port(); port != "" {
		return u.Scheme + "://" + host + ":" + port
	}
	return u.Scheme + "://" + host
}
