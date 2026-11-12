package telemetry

import (
	"bytes"
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"
)

// The OTel internal logger is a private log.Logger bound to the stderr the
// process started with, so the only way to see what it prints is to be the
// parent of the process it runs in. probeEnv selects the child's mode.
const probeEnv = "MINO_TELEMETRY_STDERR_PROBE"

// TestStderrProbeChild is the child half of the probe; it does nothing in a
// normal run.
//
// Mode "loadconfig" is production: LoadConfig decides, and Init runs with what
// it decided. Mode "forced" skips LoadConfig and starts every OTLP signal, so
// the exporters see the malformed value: that is the control, proving the
// probe can see a leak at all.
func TestStderrProbeChild(_ *testing.T) {
	mode := os.Getenv(probeEnv)
	if mode == "" {
		return
	}
	cfg := LoadConfig(nil, slog.New(slog.NewTextHandler(os.Stderr, nil)))
	if mode == "forced" {
		cfg = Config{OTLP: true, Traces: true, Metrics: true, Logs: true, SamplerRatio: 1, LogFormat: LogFormatText}
	}
	_, _ = fmt.Fprintf(os.Stdout, "otlp=%v\n", cfg.OTLP)
	tel, err := Init(context.Background(), cfg)
	if err != nil {
		_, _ = fmt.Fprintf(os.Stdout, "init failed: %s\n", innermostType(err))
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = tel.Shutdown(ctx)
}

// runProbe runs the child with an environment built from an allowlist plus
// extra, and returns its stdout and stderr.
func runProbe(t *testing.T, mode string, extra map[string]string) (string, string) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestStderrProbeChild$", "-test.count=1") //nolint:gosec // re-running this test binary
	cmd.Env = []string{probeEnv + "=" + mode, "PATH=" + os.Getenv("PATH"), "HOME=" + os.Getenv("HOME"), "TMPDIR=" + os.TempDir(), "LANG=C"}
	for k, v := range extra {
		cmd.Env = append(cmd.Env, k+"="+v)
	}
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		t.Fatalf("probe child (%s) failed: %v\nstdout:\n%s\nstderr:\n%s", mode, err, stdout.String(), stderr.String())
	}
	return stdout.String(), stderr.String()
}

// Round-3 finding 1, the reviewer's probe: a malformed header or endpoint
// value with a credential in it. The child's whole stderr must carry no
// sentinel, and OTLP must stay off.
func TestAMalformedOTLPValueNeverReachesStderr(t *testing.T) {
	if testing.Short() {
		t.Skip("spawns child processes")
	}
	base := map[string]string{
		envEndpoint:                  "http://127.0.0.1:1",
		"OTEL_EXPORTER_OTLP_TIMEOUT": "200",
	}
	with := func(k, v string) map[string]string {
		m := map[string]string{}
		for bk, bv := range base {
			m[bk] = bv
		}
		m[k] = v
		return m
	}

	// The control: with the pre-validation bypassed, the exporters print it.
	headers := with("OTEL_EXPORTER_OTLP_HEADERS", "Authorization: Bearer "+sentinel)
	_, stderr := runProbe(t, "forced", headers)
	if !strings.Contains(stderr, sentinel) {
		t.Fatalf("control: the exporters printed no sentinel, so this probe cannot see a leak:\n%s", stderr)
	}

	for name, env := range map[string]map[string]string{
		"headers":          headers,
		"signal headers":   with("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "Authorization=Bearer%zz"+sentinel),
		"endpoint":         with(envEndpoint, "http://user:"+sentinel+"@collector.example:port%zz/"),
		"signal endpoint":  with("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "http://user:"+sentinel+"@c:port%zz/"),
		"timeout":          with("OTEL_EXPORTER_OTLP_TRACES_TIMEOUT", sentinel),
		"certificate":      with("OTEL_EXPORTER_OTLP_CERTIFICATE", "/nonexistent/"+sentinel+".pem"),
		"metric interval":  with("OTEL_METRIC_EXPORT_INTERVAL", sentinel),
		"metric timeout":   with("OTEL_METRIC_EXPORT_TIMEOUT", "-1"+sentinel),
		"client cert pair": with("OTEL_EXPORTER_OTLP_CLIENT_KEY", "/nonexistent/"+sentinel+".key"),
	} {
		if name == "client cert pair" {
			env["OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE"] = os.Args[0]
		}
		stdout, stderr := runProbe(t, "loadconfig", env)
		if strings.Contains(stderr, sentinel) {
			t.Errorf("LEAK: %s: the sentinel reached stderr:\n%s", name, stderr)
		}
		if !strings.Contains(stdout, "otlp=false") {
			t.Errorf("%s: OTLP was enabled with a malformed value: %s", name, stdout)
		}
		if strings.Count(stderr, "OTLP stays off") != 1 {
			t.Errorf("%s: want exactly one warning naming the variable, got:\n%s", name, stderr)
		}
	}
}
