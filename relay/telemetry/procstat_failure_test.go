package telemetry_test

import (
	"bytes"
	"io/fs"
	"log/slog"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/procstat"
	"github.com/D10Scot/Dispatcharr/relay/telemetry"
	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

// failableProc is fakeProc until fail is set, then every snapshot fails with
// an error whose text names a pid's /proc path and a sentinel.
type failableProc struct{ fail atomic.Bool }

func (p *failableProc) Snapshot() ([]procstat.Proc, error) {
	if p.fail.Load() {
		return nil, &fs.PathError{Op: "open", Path: "/proc/4242/stat-" + sentinel, Err: syscall.EACCES}
	}
	return fakeProc{}.Snapshot()
}
func (*failableProc) TicksPerSecond() float64 { return 100 }
func (*failableProc) PageSize() int           { return 4096 }

// captureDefault routes slog.Default to a JSON buffer for the test.
func captureDefault(t *testing.T) *bytes.Buffer {
	t.Helper()
	var buf bytes.Buffer
	prev := slog.Default()
	slog.SetDefault(slog.New(slog.NewJSONHandler(&buf, nil)))
	t.Cleanup(func() { slog.SetDefault(prev) })
	return &buf
}

// After a failed /proc snapshot, M9 has no point (a false zero would read as
// a process using no memory) while M8 keeps its accumulator, and one WARNING
// names the error's type only: never the path, which names a pid.
func TestAFailedProcSnapshotDropsRSSAndWarnsOnceByTypeOnly(t *testing.T) {
	src := &failableProc{}
	reg := procstat.NewRegistry(src)
	reg.Track(500, procstat.Labels{ChannelID: 7, Kind: procstat.KindSource})
	rec := telemetrytest.Install(t, telemetry.WithProcRegistry(reg))
	logs := captureDefault(t)

	if p := rec.Points("mino_relay_process_memory_rss"); len(p) != 1 {
		t.Fatalf("control: RSS before the failure = %+v", p)
	}
	src.fail.Store(true)
	if p := rec.Points("mino_relay_process_memory_rss"); len(p) != 0 {
		t.Errorf("RSS after a failed snapshot = %+v, want no point", p)
	}
	if got := rec.Sum("mino_relay_process_cpu"); got != 2 {
		t.Errorf("CPU after a failed snapshot = %v, want the accumulated 2", got)
	}
	rec.Points("mino_relay_process_memory_rss") // a third collection, still failing

	out := logs.String()
	if n := strings.Count(out, "could not read /proc"); n != 1 {
		t.Errorf("warnings = %d, want 1 (rate limited):\n%s", n, out)
	}
	if !strings.Contains(out, `"error.type":"syscall.Errno"`) {
		t.Errorf("the warning does not name the innermost error type:\n%s", out)
	}
	for _, leak := range []string{sentinel, "/proc/4242", "permission denied"} {
		if strings.Contains(out, leak) {
			t.Errorf("the warning carries %q:\n%s", leak, out)
		}
	}

	src.fail.Store(false)
	if p := rec.Points("mino_relay_process_memory_rss"); len(p) != 1 {
		t.Errorf("RSS after recovery = %+v, want one point", p)
	}
}
