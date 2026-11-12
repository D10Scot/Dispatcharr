package output

import (
	"context"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
	"github.com/D10Scot/Dispatcharr/relay/procstat"
)

// groupsLabelled is every group procstat.Default holds under exactly l.
func groupsLabelled(l procstat.Labels) []procstat.Group {
	var out []procstat.Group
	for _, g := range procstat.Default.Groups() {
		if g.Labels == l {
			out = append(out, g)
		}
	}
	return out
}

// requireTracked waits for exactly one group under l, then for none once
// stop has run: the process was registered while it ran and its Wait
// unregistered it.
func requireTracked(t *testing.T, l procstat.Labels, what string, stop func()) {
	t.Helper()
	if !waitFor(func() bool { return len(groupsLabelled(l)) == 1 }, 10*time.Second) {
		t.Fatalf("%s is not tracked under %+v: registry holds %+v", what, l, procstat.Default.Groups())
	}
	stop()
	if !waitFor(func() bool { return len(groupsLabelled(l)) == 0 }, 10*time.Second) {
		t.Fatalf("%s is still tracked under %+v after it stopped", what, l)
	}
}

// M8/M9's wiring (observability D7): an Output Profile transcode is tracked
// as kind=output under the channel's numeric id and its profile id.
func TestAProfileTranscodeIsTrackedAsOutputWithItsProfile(t *testing.T) {
	cfg := standInProfile(t, sourceRing(t, 64))
	cfg.ChannelPK, cfg.ProfileID = 4601, 3
	p, err := StartProfile(t.Context(), cfg)
	if err != nil {
		t.Fatalf("StartProfile: %v", err)
	}
	t.Cleanup(p.Stop)
	requireTracked(t, procstat.Labels{ChannelID: 4601, Kind: procstat.KindOutput, ProfileID: 3}, "the profile transcode", p.Stop)
}

// The fMP4 remux is tracked as kind=fmp4, carrying the profile id of the
// chain it reads (zero for the channel's own ring).
func TestAnFMP4RemuxIsTrackedAsFMP4WithItsProfile(t *testing.T) {
	t.Setenv(relaytest.StandInEnv, "1")
	command, argv := relaytest.StandInCommand("--fmp4-fragments", "100000", "--fmp4-interval", "0.05")
	p, err := Start(t.Context(), Config{
		ChannelID: "wiring-fmp4",
		ChannelPK: 4602,
		ProfileID: 12,
		Source:    sourceRing(t, 64),
		Retention: time.Minute,
		Remux:     Remux{Command: command, Argv: argv, ArgvNoBSF: argv},
	})
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	t.Cleanup(p.Stop)
	requireTracked(t, procstat.Labels{ChannelID: 4602, Kind: procstat.KindFMP4, ProfileID: 12}, "the fMP4 remux", p.Stop)
}

// The no-bitstream-filter retry is tracked too. The first generation exits
// at once with the aac_adtstoasc refusal and is reaped (and so unregistered)
// before the retry spawns, so once the retry has written its init segment
// any group under these labels is the retry's.
func TestTheNoBSFRetryIsTrackedAsFMP4(t *testing.T) {
	t.Setenv(relaytest.StandInEnv, "1")
	command, failing := relaytest.StandInCommand("--fmp4-bsf-error", "--fmp4-exit")
	_, working := relaytest.StandInCommand("--fmp4-fragments", "100000", "--fmp4-interval", "0.05")
	p, err := Start(t.Context(), Config{
		ChannelID: "wiring-bsf",
		ChannelPK: 4603,
		Source:    sourceRing(t, 512),
		Retention: time.Minute,
		Remux:     Remux{Command: command, Argv: failing, ArgvNoBSF: working},
	})
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	t.Cleanup(p.Stop)
	ctx, cancel := context.WithTimeout(t.Context(), 15*time.Second)
	defer cancel()
	if err := p.Fragments().WaitInit(ctx); err != nil {
		t.Fatalf("the retry wrote no init segment: %v", err)
	}
	requireTracked(t, procstat.Labels{ChannelID: 4603, Kind: procstat.KindFMP4}, "the no-BSF retry", p.Stop)
}
