package channel

import (
	"runtime"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/procstat"
	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

// sourceGroups is every group procstat.Default holds for channel pk as a
// transcode source.
func sourceGroups(pk int) []procstat.Group {
	var out []procstat.Group
	for _, g := range procstat.Default.Groups() {
		if g.Labels == (procstat.Labels{ChannelID: pk, Kind: procstat.KindSource}) {
			out = append(out, g)
		}
	}
	return out
}

// M8/M9's wiring (observability D7): a transcode source with a real argv is
// tracked as kind=source under the channel's numeric id while it runs, and
// once its process is reaped the registry no longer holds the group. On Linux
// M8 is also read, and its value for that label set never decreases across
// the process's end.
func TestATranscodeSourceIsTrackedWhileItRuns(t *testing.T) {
	rec := telemetrytest.Install(t)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	const pk = 4242

	ch, release, err := m.Attach("procstat-wiring", testClient("a"), func() (Started, error) {
		return Started{
			Source:    &TranscodeSource{Command: "sleep", Argv: []string{"30"}, URL: "http://provider.invalid/live.ts"},
			Tuning:    testTuning(),
			ChannelPK: pk,
			Info:      SourceInfo{URL: "http://provider.invalid/live.ts", StreamID: 1, M3UProfileID: 1},
		}, nil
	})
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	waitFor(t, "the source's group to be tracked", 5*time.Second, func() bool { return len(sourceGroups(pk)) == 1 })

	cpu := func() float64 {
		var total float64
		for _, p := range rec.Points("mino_relay_process_cpu") {
			if p.Attrs["channel_id"] == "4242" && p.Attrs["kind"] == "source" {
				total += p.Value
			}
		}
		return total
	}
	var before float64
	if runtime.GOOS == "linux" {
		before = cpu()
	}

	release()
	m.StopAll()
	<-ch.Done()
	waitFor(t, "the source's group to be unregistered", 5*time.Second, func() bool { return len(sourceGroups(pk)) == 0 })

	if runtime.GOOS == "linux" {
		if after := cpu(); after < before {
			t.Errorf("M8 for channel 4242/source fell from %v to %v across the process's end", before, after)
		}
	}
}
