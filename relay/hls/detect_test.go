package hls

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

// lookPath finds a POSIX utility the detection tests use as their "encoder":
// true passes, false fails. Neither reads its argv, which is the point -- the
// subject is the relay's reading of the exit status, not the encode.
func lookPath(t *testing.T, name string) string {
	t.Helper()
	path, err := exec.LookPath(name)
	if err != nil {
		t.Fatalf("%s is not on PATH: %v", name, err)
	}
	return path
}

// device is a file that exists, standing in for /dev/dri/renderD128.
func device(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "renderD128")
	if err := os.WriteFile(path, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

// D11: with no render node the relay encodes in software, without running
// anything; a detection encode that exits 0 means Quick Sync; any failure
// means software; and the answer is cached for the process.
func TestDetection(t *testing.T) {
	missing := &Detector{Command: filepath.Join(t.TempDir(), "never-run"), Device: filepath.Join(t.TempDir(), "renderD128")}
	if got := missing.Engine(context.Background()); got != EngineSoftware {
		t.Errorf("a missing device gave %s, want software", got)
	}
	passing := &Detector{Command: lookPath(t, "true"), Device: device(t)}
	if got := passing.Engine(context.Background()); got != EngineQSV {
		t.Errorf("a passing detection encode gave %s, want qsv", got)
	}
	passing.Command = lookPath(t, "false")
	if got := passing.Engine(context.Background()); got != EngineQSV {
		t.Errorf("the answer was not cached: %s", got)
	}
	if usable, conclusive := passing.Recheck(context.Background()); usable || !conclusive {
		t.Errorf("a failing re-run of the detection gave usable=%t conclusive=%t", usable, conclusive)
	}
	failing := &Detector{Command: lookPath(t, "false"), Device: device(t)}
	if got := failing.Engine(context.Background()); got != EngineSoftware {
		t.Errorf("a failing detection encode gave %s, want software", got)
	}
	unstartable := &Detector{Command: filepath.Join(t.TempDir(), "no-such-ffmpeg"), Device: device(t)}
	if got := unstartable.Engine(context.Background()); got != EngineSoftware {
		t.Errorf("an encoder that cannot start gave %s, want software", got)
	}
	passing.MarkUnusable()
	passing.MarkUnusable()
	if got := passing.Engine(context.Background()); got != EngineSoftware {
		t.Errorf("MarkUnusable did not write Quick Sync off: %s", got)
	}
	var defaults Detector
	if defaults.command() != "ffmpeg" || defaults.device() != DefaultDevice || defaults.log() == nil {
		t.Errorf("the zero Detector's defaults")
	}
}

func TestDetectArgv(t *testing.T) {
	want := "-hide_banner -loglevel error -init_hw_device qsv=hw:/dev/dri/renderD128 -filter_hw_device hw -f lavfi -i color=c=black:s=256x144:r=25 -frames:v 1 -vf format=nv12,hwupload -c:v h264_qsv -f null -"
	if got := joinArgs(DetectArgv(DefaultDevice)); got != want {
		t.Errorf("DetectArgv = %q, want %q", got, want)
	}
}

// script writes an executable shell script, the "encoder" a detection test
// runs. It ignores its argv; its exit status and its moment are the subject.
func script(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "detect.sh")
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"+body+"\n"), 0o700); err != nil { // #nosec G306 -- a test's own script must be executable
		t.Fatal(err)
	}
	return path
}

// Finding 1 (plan review, round 1): a detection cut short by the CALLER's
// context is no evidence against the device. It answers software for that
// call, caches nothing, and the next caller detects again; a re-check cut
// short is inconclusive, which is what keeps the pipeline from writing
// Quick Sync off on its own Stop.
func TestADetectionCutShortByTheCallerIsNotCached(t *testing.T) {
	d := &Detector{Command: script(t, "sleep 1; exit 0"), Device: device(t)}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	if got := d.Engine(ctx); got != EngineSoftware {
		t.Fatalf("a cut-short detection gave %s, want software for that call", got)
	}
	if got := d.Engine(context.Background()); got != EngineQSV {
		t.Fatalf("a cut-short detection was cached: a later caller with a live context got %s, want qsv", got)
	}
	cancelled, stop := context.WithCancel(context.Background())
	stop()
	if usable, conclusive := d.Recheck(cancelled); usable || conclusive {
		t.Fatalf("a re-check under an ended context gave usable=%t conclusive=%t, want an inconclusive answer", usable, conclusive)
	}
	timedOut := &Detector{Command: script(t, "sleep 5; exit 0"), Device: device(t), Timeout: 100 * time.Millisecond}
	if usable, conclusive := timedOut.Recheck(context.Background()); usable || !conclusive {
		t.Fatalf("the detection's own timeout gave usable=%t conclusive=%t, want a conclusive failure", usable, conclusive)
	}
}

// Nit 6 (plan review, round 1): a pipeline waiting behind another
// channel's detection encode, or canned silence encode, gives up when its
// own context ends rather than holding its Stop.
func TestAWaiterGivesUpOnTheProcessWideLocks(t *testing.T) {
	d := &Detector{Command: script(t, "sleep 1; exit 0"), Device: device(t)}
	first := make(chan Engine, 1)
	go func() { first <- d.Engine(context.Background()) }()
	time.Sleep(100 * time.Millisecond)
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	started := time.Now()
	if got := d.Engine(ctx); got != EngineSoftware || time.Since(started) > 500*time.Millisecond {
		t.Fatalf("a waiter behind a running detection answered %s after %v, want software at its own deadline", got, time.Since(started))
	}
	if got := <-first; got != EngineQSV {
		t.Fatalf("the detection the waiter queued behind answered %s", got)
	}
	var s SilenceCache
	if err := s.run.lock(context.Background()); err != nil {
		t.Fatal(err)
	}
	ctx2, cancel2 := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel2()
	if _, err := s.Get(ctx2, Rendition{Name: RenditionAAC, Channels: 2}); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("a waiter behind a running canned encode got %v, want its own deadline", err)
	}
	s.run.unlock()
}
