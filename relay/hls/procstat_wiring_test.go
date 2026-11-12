package hls

import (
	"sync/atomic"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/procstat"
)

// hlsGroups is every group procstat.Default holds under exactly l.
func hlsGroups(l procstat.Labels) []procstat.Group {
	var out []procstat.Group
	for _, g := range procstat.Default.Groups() {
		if g.Labels == l {
			out = append(out, g)
		}
	}
	return out
}

func waitUntil(cond func() bool, within time.Duration) bool {
	deadline := time.Now().Add(within)
	for time.Now().Before(deadline) {
		if cond() {
			return true
		}
		time.Sleep(10 * time.Millisecond)
	}
	return cond()
}

// M8/M9's wiring (observability D7): the HLS probe is tracked as kind=hls
// under the channel's numeric id and its HLS profile, and unregistered once
// the pipeline stops.
func TestTheHLSProbeIsTrackedAsHLSWithItsProfile(t *testing.T) {
	h := newHarness(t)
	labels := procstat.Labels{ChannelID: 4701, Kind: procstat.KindHLS, ProfileID: 7}
	p := h.startWith(probeVideoOnly, func(c *Config) {
		c.ChannelPK, c.ProfileID = labels.ChannelID, labels.ProfileID
		c.ProbeCommand = func(int) (string, []string) { return "sleep", []string{"30"} }
	}, func(Spawn) []string { return nil })
	if !waitUntil(func() bool { return len(hlsGroups(labels)) == 1 }, 10*time.Second) {
		t.Fatalf("the probe is not tracked under %+v: registry holds %+v", labels, procstat.Default.Groups())
	}
	p.Stop()
	if !waitUntil(func() bool { return len(hlsGroups(labels)) == 0 }, 10*time.Second) {
		t.Fatalf("the probe is still tracked under %+v after the pipeline stopped", labels)
	}
}

// The encoder is tracked under the same labels. The probe has been reaped,
// and so unregistered, before the encoder's command is even built, so once
// the encoder has been asked for any group under these labels is its own.
func TestTheHLSEncoderIsTrackedAsHLSWithItsProfile(t *testing.T) {
	h := newHarness(t)
	labels := procstat.Labels{ChannelID: 4702, Kind: procstat.KindHLS, ProfileID: 8}
	var spawned atomic.Bool
	p := h.startWith(probeVideoOnly, func(c *Config) {
		c.ChannelPK, c.ProfileID = labels.ChannelID, labels.ProfileID
		c.Command = func(Spawn) (string, []string) {
			spawned.Store(true)
			return "sleep", []string{"30"}
		}
	}, nil)
	if !waitUntil(spawned.Load, 10*time.Second) {
		t.Fatal("the encoder was never spawned")
	}
	if !waitUntil(func() bool { return len(hlsGroups(labels)) == 1 }, 10*time.Second) {
		t.Fatalf("the encoder is not tracked under %+v: registry holds %+v", labels, procstat.Default.Groups())
	}
	p.Stop()
	if !waitUntil(func() bool { return len(hlsGroups(labels)) == 0 }, 10*time.Second) {
		t.Fatalf("the encoder is still tracked under %+v after the pipeline stopped", labels)
	}
}
