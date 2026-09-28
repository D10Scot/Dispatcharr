package hls

import (
	"context"
	"log/slog"
	"os"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// DetectTimeout bounds the one-frame detection encode (spec D11).
const DetectTimeout = 10 * time.Second

// DetectArgv is the detection encode: one black 256x144 frame through
// hwupload and h264_qsv to the null muxer. Exit 0 means Quick Sync is usable.
func DetectArgv(device string) []string {
	return []string{
		"-hide_banner", "-loglevel", "error",
		"-init_hw_device", "qsv=hw:" + device, "-filter_hw_device", "hw",
		"-f", "lavfi", "-i", "color=c=black:s=256x144:r=25",
		"-frames:v", "1", "-vf", "format=nv12,hwupload",
		"-c:v", "h264_qsv", "-f", "null", "-",
	}
}

// Detector is the process-wide answer to "is Quick Sync usable?" (D11). It
// runs the detection encode at the first HLS attach in the process and
// caches the answer; the pipelines of every channel share one.
//
// QSV IS WRITTEN OFF FOR THE PROCESS ONLY ON EVIDENCE THAT THE DEVICE FAILED
// (finding 5): a generation that failed twice on QSV must then succeed in
// software AND a re-run of the detection encode must fail. A channel whose
// source is bad fails in software too, and never reaches MarkUnusable.
type Detector struct {
	// Command is the ffmpeg executable ("ffmpeg" when empty).
	Command string
	// Device is the render node (DefaultDevice when empty). A device that
	// does not exist is software without running anything.
	Device string
	// Timeout bounds each detection encode (DetectTimeout when zero).
	Timeout time.Duration
	// Log receives the one WARNING a fallback is logged with.
	Log *slog.Logger

	// run serialises detection encodes and is held across one; a waiter
	// that gives up on it answers software without caching anything.
	run ctxLock
	// mu guards the answer below and is never held across a subprocess.
	mu       sync.Mutex
	checked  bool
	usable   bool
	unusable bool
	warned   bool
}

func (d *Detector) command() string {
	if d.Command != "" {
		return d.Command
	}
	return "ffmpeg"
}

func (d *Detector) device() string {
	if d.Device != "" {
		return d.Device
	}
	return DefaultDevice
}

func (d *Detector) log() *slog.Logger {
	if d.Log != nil {
		return d.Log
	}
	return slog.Default()
}

// Engine is the engine a new generation should start on: QSV when the
// cached detection passed and nothing has written it off, software
// otherwise. The first call runs the detection; later calls return at once.
//
// ONLY A CONCLUSIVE ANSWER IS CACHED. A detection cut short by the caller's
// own context -- a pipeline stopped while it waited, a viewer who zapped away
// -- says nothing about the device, so that call answers software and the
// next caller detects again. Detection's own timeout is conclusive: a device
// that cannot encode one frame in DetectTimeout is not usable.
func (d *Detector) Engine(ctx context.Context) Engine {
	if err := d.run.lock(ctx); err != nil {
		return EngineSoftware
	}
	defer d.run.unlock()
	d.mu.Lock()
	checked := d.checked
	d.mu.Unlock()
	if !checked {
		usable, conclusive := d.detect(ctx)
		if !conclusive {
			return EngineSoftware
		}
		d.mu.Lock()
		d.usable, d.checked = usable, true
		d.mu.Unlock()
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.usable && !d.unusable {
		return EngineQSV
	}
	if !d.warned {
		d.warned = true
		d.log().Warn("Quick Sync is not usable; HLS encodes in software", "device", d.device())
	}
	return EngineSoftware
}

// Recheck runs the detection encode again and reports whether it passed,
// and whether that answer is conclusive (the caller's context did not end
// first). It does not change the cached answer; MarkUnusable does, and only
// on a conclusive failure (D11: evidence against the device).
func (d *Detector) Recheck(ctx context.Context) (usable, conclusive bool) {
	if err := d.run.lock(ctx); err != nil {
		return false, false
	}
	defer d.run.unlock()
	return d.detect(ctx)
}

// MarkUnusable writes Quick Sync off for the rest of the process.
func (d *Detector) MarkUnusable() {
	d.mu.Lock()
	defer d.mu.Unlock()
	if !d.unusable {
		d.log().Warn("Quick Sync failed where software succeeded, and its detection encode now fails; HLS encodes in software for the rest of the process", "device", d.device())
	}
	d.unusable = true
	d.warned = true
}

// detect is the detection encode itself: a missing device, any non-zero
// exit, a spawn failure or the detection's own timeout all mean "not
// usable". conclusive is false when the CALLER's context ended first, which
// is no evidence either way.
func (d *Detector) detect(parent context.Context) (usable, conclusive bool) {
	if _, err := os.Stat(d.device()); err != nil {
		return false, true
	}
	timeout := d.Timeout
	if timeout <= 0 {
		timeout = DetectTimeout
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()
	proc, err := ffmpeg.Start(ctx, d.command(), DetectArgv(d.device()))
	if err != nil {
		d.log().Info("the Quick Sync detection encode could not start", "error", redact.Error(err))
		return false, parent.Err() == nil
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		proc.ReadStderr(func(line string) {
			d.log().Debug("detection encode stderr", "line", redact.Line(line))
		})
	}()
	err = proc.Wait()
	<-done
	if parent.Err() != nil {
		return false, false
	}
	return err == nil && ctx.Err() == nil, true
}
