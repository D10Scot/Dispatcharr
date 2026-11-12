//go:build !linux

package procstat

import "os"

type nullSource struct{}

// SystemSource reports nothing on a platform without /proc, so M8 and M9 have
// no points there.
func SystemSource() Source { return nullSource{} }

func (nullSource) Snapshot() ([]Proc, error) { return nil, nil }
func (nullSource) TicksPerSecond() float64   { return defaultClkTick }
func (nullSource) PageSize() int             { return os.Getpagesize() }
