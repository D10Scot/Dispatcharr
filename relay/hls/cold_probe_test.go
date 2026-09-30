package hls

import (
	"context"
	"errors"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// Issue #560: a probe's bound is a bound on analysis, never on the source's
// start. These tests run a pipeline over a ring that is EMPTY when it starts,
// as a cold channel's is: the pipeline starts at the entry's attach, and the
// source publishes its first chunk only later (about 6 s on the FFmpeg stream
// profile, whose ffmpeg analyses its own input first).

// coldHarness is a harness whose ring holds nothing yet.
func coldHarness(t *testing.T) *standInHarness {
	return &standInHarness{t: t, src: newTestSource(), logs: &logBuffer{}, spawnLog: filepath.Join(t.TempDir(), "spawns")}
}

// eofProbe is what ffprobe does on pipe:0: it reads its input to the end, and
// with no input at all fails "pipe:0: End of file", exit 1. Otherwise it
// answers the probe JSON in path. spawned counts its spawns.
func eofProbe(path string, spawned *atomic.Int32) func(int) (string, []string) {
	return func(int) (string, []string) {
		spawned.Add(1)
		return "sh", []string{"-c", `n=$(wc -c); if [ "$n" -eq 0 ]; then echo "pipe:0: End of file" >&2; exit 1; fi; cat "$1"`, "sh", path}
	}
}

// A first chunk later than the quick probe's whole bound is waited for, and
// the output becomes ready.
func TestAProbeWaitsForTheSourcesFirstChunk(t *testing.T) {
	h := coldHarness(t)
	probe := file(t, "probe.json", []byte(probeVideoOnly))
	video := file(t, "v.mp4", videoStream(0, 2, 50))
	var spawned atomic.Int32
	p := h.startWith(probeVideoOnly, func(c *Config) {
		c.ProbeCommand = eofProbe(probe, &spawned)
	}, func(Spawn) []string {
		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--wait-stdin-eof"}
	})
	late := QuickProbe.Analyze + 500*time.Millisecond
	time.Sleep(late)
	// More than QuickProbe.Bytes, so the probe ends on bytes at once.
	for written := 0; written <= QuickProbe.Bytes; written += testChunk {
		h.src.write(t, chunkOf('a'))
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := p.Ready(ctx); err != nil {
		t.Fatalf("Ready = %v with the first chunk %v after the start: the probe's %v bound ran out before its input arrived\n%s",
			err, late, QuickProbe.Analyze, h.logs.String())
	}
}

// A source that never sends a byte fails the output once SourceStartWait has
// passed, and never before it, with no probe spawned.
func TestASourceThatSendsNothingFailsTheOutputAfterTheStartWait(t *testing.T) {
	h := coldHarness(t)
	probe := file(t, "probe.json", []byte(probeVideoOnly))
	var spawned atomic.Int32
	const wait = 400 * time.Millisecond
	started := time.Now()
	p := h.startWith(probeVideoOnly, func(c *Config) {
		c.SourceStartWait = wait
		c.ProbeCommand = eofProbe(probe, &spawned)
	}, func(Spawn) []string { return nil })
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	err := p.Ready(ctx)
	elapsed := time.Since(started)
	if !errors.Is(err, ErrFailed) {
		t.Fatalf("Ready = %v after %v, want ErrFailed: a source that never sent a byte held the pipeline past SourceStartWait\n%s", err, elapsed, h.logs.String())
	}
	if elapsed < wait {
		t.Fatalf("the output failed %v after the start, before SourceStartWait (%v)", elapsed, wait)
	}
	if n := spawned.Load(); n != 0 {
		t.Fatalf("%d probe(s) spawned with no input: the wait did not precede the spawn", n)
	}
	if logs := h.logs.String(); !strings.Contains(logs, "sent no input within 400ms") {
		t.Fatalf("the failure does not say the source sent nothing:\n%s", logs)
	}
	waitDone(t, p, 5*time.Second)
}

// A ring that closes before its first chunk is a stop, as one that closes
// under a probe is (R40): the channel is ending.
func TestARingThatClosesBeforeItsFirstChunkIsAStop(t *testing.T) {
	h := coldHarness(t)
	probe := file(t, "probe.json", []byte(probeVideoOnly))
	var spawned atomic.Int32
	p := h.startWith(probeVideoOnly, func(c *Config) {
		c.ProbeCommand = eofProbe(probe, &spawned)
	}, func(Spawn) []string { return nil })
	time.Sleep(200 * time.Millisecond)
	h.src.ring.Close()
	waitDone(t, p, 5*time.Second)
	if err := p.Err(); err != nil {
		t.Fatalf("Err after the ring closed before its first chunk = %v, want nil: the channel is ending\n%s", err, h.logs.String())
	}
	if n := spawned.Load(); n != 0 || strings.Contains(h.logs.String(), "level=ERROR") {
		t.Fatalf("a ring that closed before its first chunk spawned %d probe(s) or logged an error:\n%s", n, h.logs.String())
	}
}

// A stop while the pipeline waits for its first chunk ends it at once, as a
// stop, however long SourceStartWait is.
func TestAStopWhileWaitingForTheFirstChunkIsAStop(t *testing.T) {
	h := coldHarness(t)
	probe := file(t, "probe.json", []byte(probeVideoOnly))
	var spawned atomic.Int32
	p := h.startWith(probeVideoOnly, func(c *Config) {
		c.SourceStartWait = time.Minute
		c.ProbeCommand = eofProbe(probe, &spawned)
	}, func(Spawn) []string { return nil })
	time.Sleep(200 * time.Millisecond)
	stopped := time.Now()
	p.Stop()
	if took := time.Since(stopped); took > 2*time.Second {
		t.Fatalf("Stop took %v: the wait for the first chunk did not end with the pipeline's context", took)
	}
	if err := p.Err(); err != nil {
		t.Fatalf("Err after a Stop during the wait = %v, want nil: a stop is not a failure\n%s", err, h.logs.String())
	}
	if n := spawned.Load(); n != 0 || strings.Contains(h.logs.String(), "level=ERROR") {
		t.Fatalf("a stop during the wait spawned %d probe(s) or logged an error:\n%s", n, h.logs.String())
	}
}
