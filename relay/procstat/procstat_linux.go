//go:build linux

package procstat

import (
	"encoding/binary"
	"os"
	"unsafe"
)

type procSource struct {
	ticks float64
}

// SystemSource reads /proc.
func SystemSource() Source {
	clk := defaultClkTick
	if b, err := os.ReadFile("/proc/self/auxv"); err == nil {
		clk = ParseAuxv(b, int(unsafe.Sizeof(uintptr(0))), binary.NativeEndian)
	}
	return procSource{ticks: float64(clk)}
}

func (s procSource) TicksPerSecond() float64 { return s.ticks }
func (procSource) PageSize() int             { return os.Getpagesize() }

// Snapshot scans /proc/[0-9]*/stat once; snapshotFrom says which per-pid
// failures are skipped and which fail the snapshot.
func (procSource) Snapshot() ([]Proc, error) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, err
	}
	names := make([]string, len(entries))
	for i, e := range entries {
		names[i] = e.Name()
	}
	return snapshotFrom(names, func(name string) ([]byte, error) {
		return os.ReadFile("/proc/" + name + "/stat") //nolint:gosec // a numeric /proc directory entry
	})
}
