//go:build linux

package procstat

import (
	"os/exec"
	"syscall"
	"testing"
	"time"
)

// A live test: a real child in its own process group, read through /proc.
func TestLiveProcessGroupHasCPUAndRSS(t *testing.T) {
	cmd := exec.CommandContext(t.Context(), "sleep", "30")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Skipf("cannot start sleep: %v", err)
	}
	t.Cleanup(func() { _ = cmd.Process.Kill(); _ = cmd.Wait() })

	r := NewRegistry(SystemSource())
	untrack := r.Track(cmd.Process.Pid, Labels{ChannelID: 1, Kind: KindSource})
	defer untrack()

	deadline := time.Now().Add(5 * time.Second)
	for {
		s := r.Collect()
		if len(s) == 1 && s[0].CPUSeconds >= 0 && s[0].RSSBytes > 0 && s[0].Live {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("no positive CPU and RSS for the live group: %+v", s)
		}
		time.Sleep(50 * time.Millisecond)
	}
}

func TestSystemSourceReadsTheTestProcessItself(t *testing.T) {
	src := SystemSource()
	if src.TicksPerSecond() <= 0 || src.PageSize() <= 0 {
		t.Fatalf("ticks=%v page=%d", src.TicksPerSecond(), src.PageSize())
	}
	procs, err := src.Snapshot()
	if err != nil {
		t.Fatal(err)
	}
	if len(procs) == 0 {
		t.Fatal("no processes listed")
	}
}
