package procstat_test

import (
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/procstat"
	"github.com/D10Scot/Dispatcharr/relay/telemetry"
	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

type scriptedSource struct {
	snaps [][]procstat.Proc
	n     int
}

func (s *scriptedSource) Snapshot() ([]procstat.Proc, error) {
	snap := s.snaps[s.n]
	s.n++
	return snap, nil
}
func (*scriptedSource) TicksPerSecond() float64 { return 100 }
func (*scriptedSource) PageSize() int           { return 4096 }

func p(pid int, start uint64, secs float64) procstat.Proc {
	return procstat.Proc{PID: pid, PGrp: 500, Start: start, CPUTicks: uint64(secs * 100)}
}

const metric = "mino_relay_process_cpu"

// A restart is a new counter epoch: the series starts again and its start time
// says so. That is the reset a backend expects at a process restart.
func TestARestartIsANewCounterEpoch(t *testing.T) {
	labels := procstat.Labels{ChannelID: 7, Kind: procstat.KindSource}

	// Registry A, under meter provider A, accumulates to 12 s (tests 1-3).
	regA := procstat.NewRegistry(&scriptedSource{snaps: [][]procstat.Proc{
		{p(500, 10, 2), p(501, 11, 3)},
		{p(500, 10, 4), p(501, 11, 5)},
		{p(500, 10, 6)},
		{p(500, 10, 6), p(501, 99, 1)},
	}})
	regA.Track(500, labels)
	a := telemetrytest.Install(t, telemetry.WithProcRegistry(regA))
	var last telemetrytest.Point
	for i, want := range []float64{5, 9, 11, 12} {
		pts := a.Points(metric)
		if len(pts) != 1 || pts[0].Value != want {
			t.Fatalf("A collection %d = %+v, want %v", i+1, pts, want)
		}
		last = pts[0]
	}

	// A fresh registry under a fresh meter provider stands for a restarted
	// relay. Its group's first snapshot reads 0.5 s.
	regB := procstat.NewRegistry(&scriptedSource{snaps: [][]procstat.Proc{{p(500, 10, 0.5)}}})
	regB.Track(500, labels)
	b := telemetrytest.Install(t, telemetry.WithProcRegistry(regB))
	pts := b.Points(metric)
	if len(pts) != 1 {
		t.Fatalf("B points = %+v", pts)
	}
	if pts[0].Value != 0.5 {
		t.Errorf("B's first point = %v, want 0.5", pts[0].Value)
	}
	if !pts[0].Start.After(last.Time) {
		t.Errorf("B's start time %v is not after A's last timestamp %v: the series did not restart", pts[0].Start, last.Time)
	}
}

func TestTheDefaultRegistryIsNotSharedBetweenEpochs(t *testing.T) {
	a := procstat.NewRegistry(&scriptedSource{snaps: [][]procstat.Proc{{p(500, 10, 1)}}})
	b := procstat.NewRegistry(&scriptedSource{snaps: [][]procstat.Proc{{p(500, 10, 1)}}})
	l := procstat.Labels{ChannelID: 1, Kind: procstat.KindHLS, ProfileID: 2}
	a.Track(500, l)
	if got := a.Collect(); len(got) != 1 || got[0].CPUSeconds != 1 {
		t.Fatalf("A = %+v", got)
	}
	if got := b.Collect(); got != nil {
		t.Fatalf("B reported another registry's accumulator: %+v", got)
	}
}
