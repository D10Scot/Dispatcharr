//go:build !linux

package procstat

import "testing"

func TestSystemSourceReportsNothingOffLinux(t *testing.T) {
	src := SystemSource()
	procs, err := src.Snapshot()
	if err != nil || len(procs) != 0 {
		t.Fatalf("Snapshot = %v, %v; want nothing", procs, err)
	}
	if src.TicksPerSecond() != 100 || src.PageSize() <= 0 {
		t.Fatalf("ticks=%v page=%d", src.TicksPerSecond(), src.PageSize())
	}
}
