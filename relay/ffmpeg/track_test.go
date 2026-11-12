package ffmpeg

import (
	"context"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/procstat"
)

// trackedLabels is the label set procstat.Default holds for pgid, if any.
func trackedLabels(pgid int) (procstat.Labels, bool) {
	for _, g := range procstat.Default.Groups() {
		if g.PGID == pgid {
			return g.Labels, true
		}
	}
	return procstat.Labels{}, false
}

// sleeper starts a real process that runs until ctx is cancelled.
func sleeper(ctx context.Context, t *testing.T) *Process {
	t.Helper()
	p, err := Start(ctx, "sleep", []string{"30"})
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	return p
}

// Track registers the process group under its labels; Wait unregisters it
// once the process is reaped; a second Wait, and a Track after Wait, leave
// the registry alone (observability spec O4, track_test.go).
func TestTrackRegistersTheGroupAndWaitUnregistersIt(t *testing.T) {
	ctx, cancel := context.WithCancel(t.Context())
	p := sleeper(ctx, t)
	labels := procstat.Labels{ChannelID: 41, Kind: procstat.KindOutput, ProfileID: 3}

	p.Track(labels)
	got, ok := trackedLabels(p.PID())
	if !ok || got != labels {
		t.Fatalf("after Track the registry holds %+v, %v for group %d; want %+v", got, ok, p.PID(), labels)
	}

	cancel()
	_ = p.Wait()
	if got, ok := trackedLabels(p.PID()); ok {
		t.Fatalf("after Wait the registry still holds group %d as %+v", p.PID(), got)
	}
	_ = p.Wait() // harmless
	p.Track(labels)
	if got, ok := trackedLabels(p.PID()); ok {
		t.Fatalf("a Track after Wait registered group %d as %+v", p.PID(), got)
	}
}

// An untracked process, the default, never touches the registry.
func TestAnUntrackedProcessNeverTouchesTheRegistry(t *testing.T) {
	ctx, cancel := context.WithCancel(t.Context())
	before := len(procstat.Default.Groups())
	p := sleeper(ctx, t)
	if _, ok := trackedLabels(p.PID()); ok {
		t.Fatalf("an untracked process's group %d is registered", p.PID())
	}
	cancel()
	_ = p.Wait()
	if after := len(procstat.Default.Groups()); after != before {
		t.Fatalf("the registry went from %d groups to %d around an untracked process", before, after)
	}
}
