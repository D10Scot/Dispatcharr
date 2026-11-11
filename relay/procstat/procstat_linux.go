//go:build linux

package procstat

import (
	"encoding/binary"
	"os"
	"strconv"
	"strings"
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

// Snapshot scans /proc/[0-9]*/stat once. A process that exits between the
// directory listing and the read is skipped, as is any entry that does not
// parse: a half-read process must not fail the whole collection.
func (procSource) Snapshot() ([]Proc, error) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, err
	}
	out := make([]Proc, 0, len(entries))
	for _, e := range entries {
		name := e.Name()
		if name == "" || name[0] < '0' || name[0] > '9' {
			continue
		}
		if _, err := strconv.Atoi(name); err != nil {
			continue
		}
		raw, err := os.ReadFile("/proc/" + name + "/stat") //nolint:gosec // a numeric /proc directory entry
		if err != nil {
			continue
		}
		p, err := ParseStat(strings.TrimSpace(string(raw)))
		if err != nil {
			continue
		}
		out = append(out, p)
	}
	return out, nil
}
