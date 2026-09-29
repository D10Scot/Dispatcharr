package hls

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// GenerationExitGrace is how long a generation may keep running after its
// stdin closed before it is killed (spec D10). ffmpeg.KillWait stays the
// reap budget after the kill.
const GenerationExitGrace = 5 * time.Second

// The restart bound (spec § Encoder argv, failure): a generation that dies
// after its first segment is restarted as at a source boundary, but a third
// such death within deathWindow is a total failure.
const (
	deathWindow = 60 * time.Second
	maxDeaths   = 3
)

// StallTimeout is the hung-encoder watchdog (ruling R33): a generation that
// writes no new video fragment for max(10 s, 5 x TARGETDURATION) while the
// channel's ring keeps advancing is dead, exactly as one that exits is, and
// counts against the restart bound. An encoder that neither exits nor reads
// its input -- a wedged device driver -- otherwise holds the pipeline until
// Stop. The ring is the measure of "input advancing", not the bytes fed to
// the encoder, because a wedged encoder that stops reading its stdin stops
// the feed too.
//
// BEFORE A GENERATION'S FIRST VIDEO FRAGMENT the allowance is
// StartupStallFactor x StallTimeout (ruling R55): a cold software encode of an
// interlaced 1080 source is fed at the provider's real-time rate and needs its
// deinterlacer's lookahead and a full GOP before it can write anything, and
// the first attempt of a cold tune was measured killed at 10 s with nothing
// wrong with it. After the first fragment the plain StallTimeout applies.
const StallTimeout = max(10*time.Second, 5*TargetDuration*time.Second)

// StartupStallFactor scales StallTimeout into the allowance a generation gets
// before its first video fragment (ruling R55): 30 s at TARGETDURATION 2.
const StartupStallFactor = 3

// StartupStall is the startup allowance for a pipeline of the given target
// duration: what a generation gets before its first video fragment. The
// entry's waits are derived from the longest target's (MaxTargetDuration).
func StartupStall(target int) time.Duration {
	_, startup := stallLimits(target)
	return startup
}

// stallLimits is the watchdog's pair for a pipeline whose target duration is
// target seconds (ruling R42): the stall timeout max(10 s, 5 x target), and
// the allowance before a generation's first fragment, max(StartupStallFactor x
// StallTimeout, the stall timeout) -- 30 s at every target from 2 to 6 (ruling
// R58), which is what keeps the entry's waits at 43 s, under nginx's 60 s
// read timeout on /hls/. The wait before a first fragment is an encoder's cold
// start, whose GOP is 2 s in every mode, or a copy's first closed GOP, at most
// 2 x K = 12 s of media, so the allowance does not need to grow with the
// target: three times max(10 s, 5 x 6) would be 90 s.
func stallLimits(target int) (stall, startup time.Duration) {
	stall = max(StallTimeout, 5*time.Duration(target)*time.Second)
	return stall, max(StartupStallFactor*StallTimeout, stall)
}

// stopJoinWait bounds Stop's wait for the pipeline to wind down: the exit
// grace, the reap budget and a margin.
const stopJoinWait = GenerationExitGrace + ffmpeg.KillWait + 2*time.Second

// stderrTail is how many of a generation's last stderr lines a total
// failure's ERROR carries.
const stderrTail = 10

// ErrFailed is a pipeline that gave up (spec § Encoder argv, failure): every
// attempt at a generation exited before its first segment, a later
// generation's probe found no video, or generations kept dying. 4a-1b turns
// it into the channel's hlsFailedUntilBoundary mark.
var ErrFailed = errors.New("hls: the HLS output failed")

// Spawn is one encoder process the pipeline is about to start: which
// generation and attempt, on which engine, and the argv it built.
type Spawn struct {
	Generation int
	Attempt    int
	Engine     Engine
	Argv       []string
	Extra      []bool
}

// Config is one pipeline's configuration.
type Config struct {
	// ChannelID names the channel in logs.
	ChannelID string
	// Source is the channel: its ring and its boundaries.
	Source Source
	// Mode is the HLS profile's mode: the built-in transcode (the zero
	// value, and the only one 4a-1a runs) or 4a-1d's automatic.
	Mode Mode
	// JoinBehind is how far behind live generation 0 starts (and is probed
	// from), the fMP4 remux's own join point. Zero starts at the ring's
	// head.
	JoinBehind time.Duration
	// Detector and Silence are process-wide; nil gives the pipeline its own.
	Detector *Detector
	Silence  *SilenceCache
	// FFmpeg and FFprobe are the executables ("ffmpeg" and "ffprobe" when
	// empty). Device is the QSV render node (DefaultDevice when empty).
	FFmpeg  string
	FFprobe string
	Device  string
	// ExitGrace overrides GenerationExitGrace, AudioWait the segmenter's
	// AudioWait, and StallTimeout the watchdog's, for tests.
	ExitGrace    time.Duration
	AudioWait    time.Duration
	StallTimeout time.Duration
	// StartupStallTimeout is the watchdog's allowance before a generation's
	// first video fragment (R55); zero means StartupStallFactor x the stall
	// timeout in force.
	StartupStallTimeout time.Duration
	// Command maps a Spawn to the command and argv actually run. Nil runs
	// FFmpeg with the built argv; the stand-in tests replace it.
	Command func(Spawn) (string, []string)
	// ProbeCommand maps a probe to the command and argv run, by generation.
	// Nil runs FFprobe with ProbeArgv.
	ProbeCommand func(generation int) (string, []string)
	// Rewind is the process-wide rewind store and WindowDepth this channel's
	// window depth (4a-3). Both must be set for the pipeline to keep a window;
	// otherwise its store holds the live edge alone, as before.
	Rewind      *Rewind
	WindowDepth time.Duration
	// Log and Now are the logger and the clock.
	Log *slog.Logger
	Now func() time.Time
}

// Pipeline is one channel's HLS output (spec § State): the current
// generation -- an ffmpeg child, its probe, its fixed output parameters --
// and the Store its segmenter publishes into. It is started by Start and runs
// until Stop, the channel's ring closing, or ErrFailed.
//
// 4a-1b's HLS entry path attaches it through Channel.AttachHLS and serves its
// Store under /hls/.
type Pipeline struct {
	cfg    Config
	log    *slog.Logger
	store  *Store
	det    *Detector
	sil    *SilenceCache
	now    func() time.Time
	cancel context.CancelFunc
	done   chan struct{}

	readyOnce sync.Once
	readyCh   chan struct{}
	// background is the goroutines a pipeline starts beyond its generation:
	// the re-run of the detection encode (D11). run waits for them.
	background sync.WaitGroup

	mu       sync.Mutex
	err      error
	readyErr error
	output   *Output
	codecs   map[string]string
	// initCodecs is each generation's CODECS values until one generation
	// has them all and they become codecs (noteInit).
	initCodecs map[int]map[string]string
	engine     Engine
	gen        int
	probes     map[int]Probe
}

// Start begins a pipeline. It returns at once: the probe (3 s, or 11 s with
// its one re-probe) and the
// wait for generation 0's init segments (bounded by the caller, 20 s in
// 4a-1b) run outside it, so a caller holding a lock -- AttachOutput's outMu
// -- is never held behind them (D9). Ready is the wait.
func Start(ctx context.Context, cfg Config) (*Pipeline, error) {
	if cfg.Source == nil || cfg.Source.Ring() == nil {
		return nil, errors.New("hls: a pipeline needs a source ring")
	}
	log := cfg.Log
	if log == nil {
		log = slog.Default()
	}
	now := cfg.Now
	if now == nil {
		now = time.Now
	}
	det := cfg.Detector
	if det == nil {
		det = &Detector{Command: cfg.FFmpeg, Device: cfg.Device, Log: log}
	}
	sil := cfg.Silence
	if sil == nil {
		sil = &SilenceCache{Command: cfg.FFmpeg, Log: log}
	}
	ctx, cancel := context.WithCancel(ctx)
	p := &Pipeline{
		cfg:     cfg,
		log:     log.With("channel", cfg.ChannelID, "format", "hls"),
		store:   NewStore(now),
		det:     det,
		sil:     sil,
		now:     now,
		cancel:  cancel,
		done:    make(chan struct{}),
		readyCh: make(chan struct{}),
		probes:  map[int]Probe{},
	}
	if cfg.Rewind != nil && cfg.WindowDepth > 0 {
		cfg.Rewind.open(cfg.ChannelID, cfg.WindowDepth, p.store)
	}
	go p.run(ctx)
	return p, nil
}

// Store is the pipeline's segments and playlists.
func (p *Pipeline) Store() *Store { return p.store }

// IsReady is whether one generation's init segments all exist and the pipeline
// did not fail before that (Ready's answer, without the wait). A pipeline that
// is not ready has served no multivariant, so nothing lingers for it (4a-3).
func (p *Pipeline) IsReady() bool {
	select {
	case <-p.readyCh:
		p.mu.Lock()
		defer p.mu.Unlock()
		return p.readyErr == nil
	default:
		return false
	}
}

// SetLingering tells the pipeline's window its channel is lingering (spec D14),
// which the disk cap's eviction order prefers to evict from.
func (p *Pipeline) SetLingering(on bool) { p.store.SetLingering(on) }

// Done is closed when the pipeline has ended.
func (p *Pipeline) Done() <-chan struct{} { return p.done }

// Err is why the pipeline ended: ErrFailed or ErrNoVideo, or nil for a stop
// or the channel's ring closing.
func (p *Pipeline) Err() error {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.err
}

// Engine is the engine the current generation runs on, for 4a-1b's
// hls_encoder payload field.
func (p *Pipeline) Engine() Engine {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.engine
}

// Generation is the current generation number, for hls_generation.
func (p *Pipeline) Generation() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.gen
}

// TargetDuration is the pipeline's target duration: its output's once
// generation 0's probe has decided it (2 s in transcode, up to 6 s for a copied
// automatic run), and the default before that. The session's presence
// thresholds, the stall watchdog and the store's byte ceiling all scale with
// it (ruling R42).
func (p *Pipeline) TargetDuration() time.Duration {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.output == nil || p.output.Target <= 0 {
		return TargetDuration * time.Second
	}
	return time.Duration(p.output.Target) * time.Second
}

// watchLimits is the watchdog's stall timeout and its startup allowance, in
// the order a test override wins: cfg.StallTimeout, else the target's own;
// cfg.StartupStallTimeout, else StartupStallFactor x an overridden
// StallTimeout (the rule the seed's own tests pin), else the target's own.
func (p *Pipeline) watchLimits() (stall, startup time.Duration) {
	target := int(p.TargetDuration() / time.Second)
	stall, startup = stallLimits(target)
	if p.cfg.StallTimeout > 0 {
		stall = p.cfg.StallTimeout
		startup = StartupStallFactor * p.cfg.StallTimeout
	}
	if p.cfg.StartupStallTimeout > 0 {
		startup = p.cfg.StartupStallTimeout
	}
	return stall, startup
}

// GenerationProbe is what a generation's probe found.
func (p *Pipeline) GenerationProbe(gen int) (Probe, bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	probe, ok := p.probes[gen]
	return probe, ok
}

// Output is the run's fixed output, once generation 0's probe has decided it.
func (p *Pipeline) Output() (Output, bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.output == nil {
		return Output{}, false
	}
	return *p.output, true
}

// Ready waits until one generation's init segments all exist -- normally
// generation 0's (the multivariant waits for them, D7; R41) -- the pipeline
// ends first, or ctx ends. It reports
// readiness, not health: a pipeline that fails after its inits exist still
// answers nil here, and Done and Err are what say it ended.
func (p *Pipeline) Ready(ctx context.Context) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-p.readyCh:
		p.mu.Lock()
		defer p.mu.Unlock()
		return p.readyErr
	}
}

// Multivariant renders the multivariant playlist under base, once Ready.
func (p *Pipeline) Multivariant(base string) ([]byte, error) {
	select {
	case <-p.readyCh:
	default:
		return nil, errors.New("hls: the multivariant is not ready")
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.readyErr != nil {
		return nil, p.readyErr
	}
	return Multivariant(*p.output, p.codecs, base), nil
}

// Stop ends the pipeline and waits, bounded, for its generation to go.
func (p *Pipeline) Stop() {
	p.cancel()
	select {
	case <-p.done:
	case <-time.After(stopJoinWait):
		p.log.Warn("the HLS pipeline did not stop in time")
	}
}

func (p *Pipeline) markReady(err error) {
	p.readyOnce.Do(func() {
		p.mu.Lock()
		p.readyErr = err
		p.mu.Unlock()
		close(p.readyCh)
	})
}

// noteInit records a rendition's init segment and its CODECS value, and
// marks the pipeline ready once ONE generation has every rendition's init
// (ruling R41): usually generation 0, but a generation 0 that ended at a
// boundary, or died, before writing all of its inits must not leave Ready
// unanswered while a later generation serves segments. The multivariant's
// CODECS come from that generation's inits; the output they describe is
// fixed for the run (D8), so every generation's are the same.
//
// Completeness is judged from the codecs recorded here under p.mu, never
// from the store (plan review, round 4, finding 1): each reader stores its
// init before it records its codec, so a store that already holds every
// init can still be missing a codec, and adopting the map then would
// advertise an empty CODECS entry for the life of the pipeline. A complete
// codec map implies every init is stored, because SetInit comes first.
func (p *Pipeline) noteInit(name string, gen int, data []byte, codec string) {
	p.store.SetInit(name, gen, data)
	p.mu.Lock()
	if p.codecs != nil || p.output == nil {
		p.mu.Unlock()
		return
	}
	if p.initCodecs == nil {
		p.initCodecs = map[int]map[string]string{}
	}
	if p.initCodecs[gen] == nil {
		p.initCodecs[gen] = map[string]string{}
	}
	p.initCodecs[gen][name] = codec
	for _, r := range p.output.Renditions() {
		if _, ok := p.initCodecs[gen][r]; !ok {
			p.mu.Unlock()
			return
		}
	}
	p.codecs, p.initCodecs = p.initCodecs[gen], nil
	if p.output.Automatic {
		// The multivariant declares the family's ceiling, not the first
		// complete generation's own string (R59); the init segments keep
		// each generation's own.
		declared, ok := ceilingCodec(p.codecs[RenditionVideo], *p.output)
		if !ok {
			p.log.Warn("the video codec string could not be raised to the family's ceiling; declaring it as it is",
				"generation", gen, "codec", p.codecs[RenditionVideo])
		}
		p.codecs[RenditionVideo] = declared
	}
	p.mu.Unlock()
	p.markReady(nil)
}

func (p *Pipeline) finish(err error) {
	p.mu.Lock()
	p.err = err
	p.mu.Unlock()
	if err == nil {
		err = ErrStoreClosed
	}
	p.markReady(err)
}

// run is the generation loop (D10): probe where the generation starts, run
// it with the failure policy, and at a source boundary or a death start the
// next one.
func (p *Pipeline) run(ctx context.Context) {
	defer close(p.done)
	defer p.background.Wait()
	defer p.store.Close()

	ring := p.cfg.Source.Ring()
	start := ring.Head()
	if p.cfg.JoinBehind > 0 {
		start = ring.Join(p.cfg.JoinBehind)
	}
	var deaths []time.Time
	// forceEncode is set by an over-long copied segment: every later
	// generation of the run is encoded into the declared family (spec § Two
	// run-level rules for automatic).
	forceEncode := false
	// noteDeath records one death or over-long ending in the 3-in-60 s window
	// and reports whether it was the third.
	noteDeath := func() bool {
		now := p.now()
		kept := deaths[:0]
		for _, at := range deaths {
			if now.Sub(at) < deathWindow {
				kept = append(kept, at)
			}
		}
		deaths = append(kept, now)
		return len(deaths) >= maxDeaths
	}
	for gen := 0; ; gen++ {
		if ctx.Err() != nil {
			p.finish(nil)
			return
		}
		probe, bound, fed, err := p.probeGeneration(ctx, gen, start)
		if ctx.Err() != nil {
			p.finish(nil)
			return
		}
		if fed.end == feedClosed && (err != nil || probe.Video == nil || !probe.Video.Complete()) {
			// The channel's ring closed under the probe (ruling R40): the
			// channel is ending, and a probe of its last few bytes failing
			// is that, not a failure of the output. A stop, as attempt
			// classifies a ring that closes under an encoder.
			p.finish(nil)
			return
		}
		if fed.end == feedBoundary && (err != nil || probe.Video == nil || !probe.Video.Complete()) {
			// Finding 3 (plan review, round 1): this generation's
			// connection ended at another boundary before the probe could
			// describe it -- a failover candidate that sent a few kilobytes
			// and dropped. There is nothing of it to encode, and the next
			// connection is already in the ring, so the pipeline moves on
			// to it as at any boundary. Only a probe that read its whole
			// bound and still failed says the source is unusable.
			//
			// Generation 0 too (ruling R39): it starts JoinBehind behind
			// live, so a failover in the last few seconds puts a boundary
			// inside its probe window, and a viewer who tuned just after
			// it must not get ErrNoVideo for the OLD connection's tail.
			// Generation 0 keeps its number: it has not started yet.
			p.log.Warn("an HLS generation's connection ended before it could be probed; moving to the next boundary",
				"generation", gen, "boundary", fed.boundary)
			start = fed.boundary - 1
			if gen == 0 {
				gen-- // the loop's increment makes the next one generation 0 again
			}
			continue
		}
		if err != nil {
			p.log.Error("the HLS probe failed", "generation", gen, "error", redact.Error(err))
			p.finish(ErrFailed)
			return
		}
		p.mu.Lock()
		p.probes[gen] = probe
		delete(p.probes, gen-16)
		p.gen = gen
		first := p.output == nil
		p.mu.Unlock()
		if first {
			out, err := DecideFor(probe, p.cfg.Mode)
			if err != nil {
				if probe.Video != nil {
					// Nit 5 (plan review, round 1): said as what it is.
					p.log.Error("the HLS source's video could not be probed: no width or height even at the full bound", "generation", gen)
				} else {
					p.log.Error("the HLS source has no video stream", "generation", gen)
				}
				p.finish(ErrNoVideo)
				return
			}
			p.mu.Lock()
			p.output = &out
			p.mu.Unlock()
			// Before any publish: the media playlists' TARGETDURATION and the
			// byte ceiling follow the pipeline's own target (R42).
			p.store.SetTargetDuration(out.Target)
			p.log.Info("HLS output decided", "generation", gen, "width", out.Width, "height", out.Height,
				"frame_rate", out.FrameRate, "family", out.Family, "target", out.Target, "level", out.Level, "automatic", out.Automatic)
		} else if probe.Video == nil {
			p.log.Error("a later HLS generation's source has no video stream", "generation", gen)
			p.finish(ErrFailed)
			return
		}
		p.logProbe(gen, probe)

		result := p.generation(ctx, gen, start, probe, bound, forceEncode)
		switch result.outcome {
		case outcomeStopped:
			p.finish(nil)
			return
		case outcomeFailed:
			p.log.Error("the HLS output failed: every attempt at a generation exited before its first segment",
				"generation", gen, "stderr", strings.Join(result.tail, " | "))
			p.finish(ErrFailed)
			return
		case outcomeBoundary:
			p.log.Info("source boundary: the HLS generation ended and the next starts there", "generation", gen, "boundary", result.boundary)
			start = result.boundary - 1
		case outcomeDied:
			if noteDeath() {
				p.log.Error("the HLS output failed: its generations keep dying",
					"generation", gen, "deaths", len(deaths), "within", deathWindow, "stderr", strings.Join(result.tail, " | "))
				p.finish(ErrFailed)
				return
			}
			p.log.Warn("an HLS generation died after its first segment; restarting at the ring's head, as at a source boundary", "generation", gen)
			start = ring.Head()
		case outcomeOverlong:
			// A copied segment that would round above the target ended the
			// generation at once. It counts toward the restart bound as a
			// death does, every later generation is encoded, and the run
			// resumes at the ring's head as after a death.
			if noteDeath() {
				p.log.Error("the HLS output failed: its generations keep ending",
					"generation", gen, "deaths", len(deaths), "within", deathWindow, "stderr", strings.Join(result.tail, " | "))
				p.finish(ErrFailed)
				return
			}
			forceEncode = true
			p.log.Warn("a copied HLS segment was longer than the target duration allows; the run is encoded from here",
				"generation", gen)
			start = ring.Head()
		}
	}
}

// logVideoDecision logs an automatic attempt's video decision once, with the
// one-word reason it was encoded (spec § Automatic generation), so a copy that
// was not made says why. A field order of unknown is said to be treated as
// progressive (R28, issue #525) whenever it is the field order.
func (p *Pipeline) logVideoDecision(gen, n int, out Output, probe Probe, plan Plan, forceEncode bool) {
	fill, reason := "encode", ""
	if plan.VideoCopy {
		fill = "copy"
	} else {
		_, reason = out.VideoDecision(probe, forceEncode)
	}
	field := "none"
	if probe.Video != nil {
		field = probe.Video.Field.String()
		if probe.Video.Field == FieldUnknown {
			field = "unknown, treated as progressive (R28)"
		}
	}
	p.log.Info("HLS video", "generation", gen, "attempt", n, "fill", fill, "reason", reason,
		"family", out.Family, "field_order", field, "keyframes", probe.Keyframes, "keyframe_interval", probe.KeyframeInterval)
}

// logProbe logs the probe's audio decisions, including a choice between
// several qualifying streams (spec § Encoder argv).
func (p *Pipeline) logProbe(gen int, probe Probe) {
	var streams []string
	for _, a := range probe.Audio {
		streams = append(streams, fmt.Sprintf("%s %s %dch %dHz qualifies=%t", a.ID, a.Codec, a.Channels, a.SampleRate, a.Qualifies()))
	}
	video := "none"
	if probe.Video != nil {
		video = fmt.Sprintf("%s %dx%d %s %s", probe.Video.Codec, probe.Video.Width, probe.Video.Height, probe.Video.FrameRate, probe.Video.Field)
	}
	p.log.Info("HLS generation probed", "generation", gen, "video", video, "audio", strings.Join(streams, "; "))
	if q := probe.Qualifying(); len(q) > 1 {
		p.log.Info("more than one qualifying audio stream; the first fills aac, and ac3/eac3 prefer their own codec", "generation", gen, "chosen", q[0].ID)
	}
}

// probeGeneration is D9's probe as ruling R30 amends it: the quick bound,
// then ONE re-probe at the full bound only when the quick one found video
// without its geometry or field order and there were more bytes to read. It
// returns the probe, the bound it succeeded with (the encoder's input
// analysis follows it), and how the probe's feed ended.
func (p *Pipeline) probeGeneration(ctx context.Context, gen int, start uint64) (Probe, ProbeBound, feedResult, error) {
	probe, fed, err := p.probe(ctx, gen, start, QuickProbe)
	if err != nil || !needsFullProbe(probe, fed, p.cfg.Mode) {
		return probe, QuickProbe, fed, err
	}
	p.log.Info("the HLS probe found video without its geometry or field order; re-probing at the full bound",
		"generation", gen, "bytes", FullProbe.Bytes, "analyze", FullProbe.Analyze)
	full, fullFed, fullErr := p.probe(ctx, gen, start, FullProbe)
	if fullErr == nil {
		if full.Video == nil || !full.Video.Complete() {
			p.log.Warn("the HLS probe is still incomplete at the full bound; deciding from what it found", "generation", gen)
		}
		return full, FullProbe, fullFed, nil
	}
	// The re-probe itself failed (its ffprobe could not start, say): the
	// quick probe's answer is still the best there is.
	p.log.Warn("the HLS re-probe failed; deciding from the quick probe", "generation", gen, "error", redact.Error(fullErr))
	return probe, QuickProbe, fed, err
}

// needsFullProbe is R30's re-probe condition: video was found but not its
// width, height or field order -- or, in automatic mode only, fewer than two
// keyframes (ruling R37: the copy rule's K <= 6 s and its bitrate over the
// probe window must stay observable, and 3 s cannot hold two keyframes 4 s
// apart) -- AND the quick probe's feed stopped for a reason more bytes would
// change: not at a boundary or the ring's close, where a longer probe would
// read the same bytes again.
func needsFullProbe(p Probe, fed feedResult, mode Mode) bool {
	if p.Video == nil || fed.end == feedBoundary || fed.end == feedClosed {
		return false
	}
	if !p.Video.Complete() {
		return true
	}
	return mode == ModeAutomatic && p.Keyframes < 2
}

// probe runs one ffprobe over the bytes the generation will start from,
// within bound.
func (p *Pipeline) probe(ctx context.Context, gen int, start uint64, bound ProbeBound) (Probe, feedResult, error) {
	command, argv := p.cfg.FFprobe, ProbeArgvFor(bound, p.cfg.Mode)
	if command == "" {
		command = "ffprobe"
	}
	if p.cfg.ProbeCommand != nil {
		command, argv = p.cfg.ProbeCommand(gen)
	}
	pctx, cancel := context.WithTimeout(ctx, bound.Analyze+ffmpeg.KillWait+time.Second)
	defer cancel()
	proc, err := ffmpeg.StartPiped(pctx, command, argv)
	if err != nil {
		return Probe{}, feedResult{end: feedWriteFailed}, fmt.Errorf("hls: starting the probe: %w", redact.Error(err))
	}
	stderrDone := make(chan struct{})
	go func() {
		defer close(stderrDone)
		proc.ReadStderr(func(line string) {
			p.log.Debug("HLS probe stderr", "line", redact.Line(line))
		})
	}()
	feedCtx, stopFeed := context.WithTimeout(pctx, bound.Analyze)
	fedDone := make(chan struct{})
	var fed feedResult
	go func() {
		defer close(fedDone)
		defer proc.CloseStdin()
		fed = feed(feedCtx, p.cfg.Source, start, proc.Stdin(), bound.Bytes, nil)
	}()
	out, readErr := io.ReadAll(io.LimitReader(proc.Stdout(), 4<<20))
	stopFeed()
	<-fedDone
	<-stderrDone
	waitErr := proc.Wait()
	if ctx.Err() != nil {
		return Probe{}, fed, ctx.Err()
	}
	if waitErr != nil || readErr != nil {
		return Probe{}, fed, fmt.Errorf("hls: the probe failed: %w", redact.Error(errors.Join(waitErr, readErr)))
	}
	probe, err := ParseProbe(out)
	return probe, fed, err
}

type outcome int

const (
	outcomeStopped outcome = iota
	outcomeBoundary
	outcomeEarly
	outcomeDied
	outcomeFailed
	// outcomeOverlong is a copied generation ended at once by a segment that
	// would round above the target duration. It is not outcomeEarly: no
	// same-engine retry of a copy that would fail the same way.
	outcomeOverlong
)

type genResult struct {
	outcome  outcome
	boundary uint64
	tail     []string
}

// generation runs one generation with D11's failure policy. An attempt that
// exits before its first segment is retried once on the same engine; if
// that was Quick Sync and it fails again, the same input is tried in
// software, and Quick Sync is written off for the process only when that
// software attempt succeeds AND a re-run of the detection encode fails.
// Anything else that fails every attempt fails this channel's HLS output
// alone.
//
// A generation whose video an automatic run copies (4a-1d) has no encoder to
// retry on another engine: it copies twice, and if both attempts exit before
// their first segment it is encoded into the run's declared family under the
// ordinary policy (R74), on the same input. Only when that encode fails too is
// the generation, and so the channel's HLS output, failed.
func (p *Pipeline) generation(ctx context.Context, gen int, start uint64, probe Probe, bound ProbeBound, forceEncode bool) genResult {
	if p.cfg.Mode == ModeAutomatic {
		out := p.currentOutput()
		if copied, _ := out.VideoDecision(probe, forceEncode); copied {
			r := p.attempt(ctx, gen, 1, start, probe, bound, EngineCopy, false, nil)
			if r.outcome != outcomeEarly {
				return r
			}
			p.log.Warn("a copied HLS generation exited before its first segment; retrying", "generation", gen)
			r = p.attempt(ctx, gen, 2, start, probe, bound, EngineCopy, false, nil)
			if r.outcome != outcomeEarly {
				return r
			}
			p.log.Warn("a copy generation exited before its first segment twice; encoding it into the declared family",
				"generation", gen, "family", out.Family)
			return p.encodeGeneration(ctx, gen, start, probe, bound, true, 3)
		}
	}
	return p.encodeGeneration(ctx, gen, start, probe, bound, forceEncode, 1)
}

// encodeGeneration is D11's failure policy for an encoded generation,
// numbering its attempts from first (3 after a failed copy's two). The
// encoder is the run's declared family's: h264_qsv or libx264, or in an HEVC
// run hevc_qsv or libx265, each family detected and written off on its own
// evidence.
func (p *Pipeline) encodeGeneration(ctx context.Context, gen int, start uint64, probe Probe, bound ProbeBound, forceEncode bool, first int) genResult {
	family := p.currentOutput().Family
	engine := p.det.EngineFor(ctx, family)
	r := p.attempt(ctx, gen, first, start, probe, bound, engine, forceEncode, nil)
	if r.outcome != outcomeEarly {
		return r
	}
	p.log.Warn("an HLS generation exited before its first segment; retrying", "generation", gen, "engine", engine)
	r = p.attempt(ctx, gen, first+1, start, probe, bound, engine, forceEncode, nil)
	if r.outcome != outcomeEarly {
		return r
	}
	if engine == EngineQSV {
		p.log.Warn("an HLS generation failed twice on Quick Sync; trying the same input in software", "generation", gen)
		r = p.attempt(ctx, gen, first+2, start, probe, bound, EngineSoftware, forceEncode, func() {
			// Software got a segment out of the input Quick Sync could
			// not. Whether that was the device is the detection encode's
			// to say, on its own goroutine so the segmenter never waits
			// for it; run waits for it before the pipeline is Done.
			p.background.Add(1)
			go func() {
				defer p.background.Done()
				if usable, conclusive := p.det.RecheckFor(ctx, family); conclusive && !usable {
					p.det.MarkUnusableFor(family)
				}
			}()
		})
		if r.outcome != outcomeEarly {
			return r
		}
	}
	r.outcome = outcomeFailed
	return r
}

// currentOutput is the run's fixed output, decided by generation 0's probe.
func (p *Pipeline) currentOutput() Output {
	p.mu.Lock()
	defer p.mu.Unlock()
	return *p.output
}

// attempt is one encoder process: its spawn, its input writer, its stderr,
// its output readers and its segmenter, joined before it returns.
func (p *Pipeline) attempt(ctx context.Context, gen, n int, start uint64, probe Probe, bound ProbeBound, engine Engine, forceEncode bool, onFirst func()) genResult {
	p.mu.Lock()
	out := *p.output
	// No attempt's noteInit may complete a codec set with a string an earlier
	// attempt of this generation recorded before it failed (the 4a-1a r5
	// hand-off): the set starts empty, and the silence fills below record
	// theirs after this.
	if p.codecs == nil {
		delete(p.initCodecs, gen)
	}
	p.mu.Unlock()
	var plan Plan
	if p.cfg.Mode == ModeAutomatic {
		plan = PlanAutomatic(out, probe, engine, gen, forceEncode)
	} else {
		plan = PlanGeneration(out, probe, engine)
	}
	plan.Input = bound
	p.mu.Lock()
	p.engine = plan.Engine
	p.mu.Unlock()
	if p.cfg.Mode == ModeAutomatic {
		p.logVideoDecision(gen, n, out, probe, plan, forceEncode)
	}

	silence := map[string]*silenceClock{}
	var encoded []string
	for _, r := range out.Audio {
		switch plan.Fills[r.Name].Kind {
		case FillSilence:
			canned, err := p.sil.Get(ctx, r)
			if err != nil {
				if ctx.Err() != nil {
					// Stopped while waiting for the canned encode (another
					// channel's, or this one's own first): a stop, never a
					// failure of the output (plan review, round 2, finding 1).
					return genResult{outcome: outcomeStopped}
				}
				p.log.Error("the canned silence for an HLS rendition could not be made", "rendition", r.Name, "error", redact.Error(err))
				return genResult{outcome: outcomeEarly}
			}
			silence[r.Name] = &silenceClock{canned: canned}
			p.noteInit(r.Name, gen, canned.Init, canned.Track.Codec)
		default:
			encoded = append(encoded, r.Name)
		}
		p.log.Info("HLS rendition", "generation", gen, "attempt", n, "rendition", r.Name, "fill", plan.Fills[r.Name].Kind, "source", plan.Fills[r.Name].Source.ID)
	}

	spawn := Spawn{Generation: gen, Attempt: n, Engine: plan.Engine, Argv: out.Argv(plan, p.device()), Extra: out.Extra(plan)}
	command, argv := p.cfg.FFmpeg, spawn.Argv
	if command == "" {
		command = "ffmpeg"
	}
	if p.cfg.Command != nil {
		command, argv = p.cfg.Command(spawn)
	}
	actx, acancel := context.WithCancel(ctx)
	defer acancel()
	proc, err := ffmpeg.StartPipedExtra(actx, command, argv, spawn.Extra)
	if err != nil {
		if ctx.Err() != nil {
			return genResult{outcome: outcomeStopped}
		}
		p.log.Error("the HLS encoder could not start", "generation", gen, "error", redact.Error(err))
		return genResult{outcome: outcomeEarly}
	}

	seg := newSegmenter(p.store, gen, encoded, silence, p.now, p.cfg.AudioWait, onFirst)
	seg.target, seg.copied = uint64(max(out.Target, 0)), plan.VideoCopy // #nosec G115 -- a target duration in seconds, 2 to 6
	seg.onOverlong = func() {
		p.log.Warn("a copied HLS segment would round above the target duration; ending the generation",
			"generation", gen, "attempt", n, "target", out.Target)
		proc.Kill()
	}
	var tailMu sync.Mutex
	var tail []string
	stderrDone := make(chan struct{})
	go func() {
		defer close(stderrDone)
		proc.ReadStderr(func(line string) {
			line = redact.Line(line)
			p.log.Warn("HLS encoder stderr", "generation", gen, "line", line)
			tailMu.Lock()
			tail = append(tail, line)
			if len(tail) > stderrTail {
				tail = tail[len(tail)-stderrTail:]
			}
			tailMu.Unlock()
		})
	}()

	readersDone := make(chan struct{})
	var readers sync.WaitGroup
	read := func(name string, r io.Reader) {
		readers.Add(1)
		go func() {
			defer readers.Done()
			defer seg.finish(name)
			var info Track
			sp := splitter{
				onInit: func(b []byte) error {
					t, err := ParseInit(b)
					if err != nil {
						return err
					}
					stripped, err := StripEdits(b)
					if err != nil {
						return err
					}
					info = t
					seg.init(name, t)
					p.noteInit(name, gen, stripped, t.Codec)
					return nil
				},
				onFrag: func(b []byte) error {
					f, err := ParseFragment(b, info)
					if err != nil {
						return err
					}
					if err := shiftStart(&f, info.StartOffset); err != nil {
						return err
					}
					seg.fragment(name, f)
					return nil
				},
			}
			if err := sp.read(r); err != nil {
				p.log.Error("an HLS encoder output is not fragmented MP4; ending the generation", "generation", gen, "rendition", name, "error", redact.Error(err))
				proc.Kill()
				_, _ = io.Copy(io.Discard, r)
			}
		}()
	}
	read(RenditionVideo, proc.Stdout())
	for i, name := range audioOrder {
		if r := proc.Extra(i); r != nil {
			read(name, r)
		}
	}
	go func() {
		readers.Wait()
		close(readersDone)
	}()
	go p.watch(gen, seg, proc, readersDone)
	segDone := make(chan struct{})
	go func() {
		defer close(segDone)
		seg.run()
	}()

	var fed feedResult
	var inputClosed time.Time
	fedDone := make(chan struct{})
	ring := p.cfg.Source.Ring()
	go func() {
		defer close(fedDone)
		fed = feed(actx, p.cfg.Source, start, proc.Stdin(), 0, func(index uint64) {
			seg.setAnchor(arrival(ring, index, p.now))
		})
		proc.CloseStdin()
		if fed.end == feedBoundary || fed.end == feedClosed {
			inputClosed = time.Now()
			// D10: the generation exits on its own at stdin EOF (M8: 0.065 s);
			// one still running after the grace is killed.
			select {
			case <-readersDone:
			case <-time.After(p.exitGrace()):
				p.log.Warn("an HLS generation was still running after its input closed; killing it", "generation", gen, "grace", p.exitGrace())
				proc.Kill()
			}
		}
	}()

	<-readersDone
	acancel()
	_ = proc.Wait()
	exited := time.Now()
	<-fedDone
	<-stderrDone
	<-segDone
	if !inputClosed.IsZero() {
		// D10 and M8: a generation exits on its own once its input closes.
		// Logged for Q6, the failover gap, whose first term this is.
		p.log.Info("HLS generation ended after its input closed", "generation", gen, "attempt", n,
			"after_input_closed", exited.Sub(inputClosed), "segments", seg.Published())
	}

	tailMu.Lock()
	result := genResult{tail: tail}
	tailMu.Unlock()
	switch {
	case ctx.Err() != nil:
		result.outcome = outcomeStopped
	case seg.Overlong():
		result.outcome = outcomeOverlong
	case fed.end == feedBoundary:
		result.outcome, result.boundary = outcomeBoundary, fed.boundary
	case fed.end == feedClosed:
		result.outcome = outcomeStopped
	case seg.Published() == 0:
		result.outcome = outcomeEarly
	default:
		result.outcome = outcomeDied
	}
	return result
}

// watch is the stall watchdog (R33): it kills the generation when no new
// video fragment has arrived for StallTimeout of the ring ADVANCING -- or, while
// the generation has written no video fragment yet, for the longer startup
// allowance (R55: StartupStallFactor x StallTimeout). The
// clock starts at the first ring advance after the latest fragment, and
// stops again whenever the ring has not moved for half the timeout, so an
// upstream in dead air -- which starves the encoder of input, and is the
// channel's own failover's business -- never reads as a stalled encoder, and
// an encoder resuming after one gets the whole timeout. The kill ends the
// process's outputs, and the attempt is then classified as any process that
// ended on its own: a death after its first segment, an early exit before it.
func (p *Pipeline) watch(gen int, seg *segmenter, proc *ffmpeg.Process, done <-chan struct{}) {
	stall, startup := p.watchLimits()
	ring := p.cfg.Source.Ring()
	ticker := time.NewTicker(stall / 10)
	defer ticker.Stop()
	frags, head := seg.VideoFragments(), ring.Head()
	var advancing time.Time // when the ring first moved since the latest fragment; zero if it has not
	moved := time.Now()     // when the ring last moved
	for {
		select {
		case <-done:
			return
		case <-ticker.C:
		}
		now := time.Now()
		if n := seg.VideoFragments(); n != frags {
			frags, head, advancing = n, ring.Head(), time.Time{}
			continue
		}
		if h := ring.Head(); h != head {
			head, moved = h, now
			if advancing.IsZero() {
				advancing = now
			}
		} else if now.Sub(moved) >= stall/2 {
			advancing = time.Time{}
		}
		limit := stall
		if frags == 0 {
			limit = startup
		}
		if !advancing.IsZero() && now.Sub(advancing) >= limit {
			p.log.Warn("an HLS generation wrote no video while its input advanced; killing it as a stalled encoder",
				"generation", gen, "stalled_for", now.Sub(advancing).Round(time.Millisecond))
			proc.Kill()
			return
		}
	}
}

func (p *Pipeline) device() string {
	if p.cfg.Device != "" {
		return p.cfg.Device
	}
	return DefaultDevice
}

func (p *Pipeline) exitGrace() time.Duration {
	if p.cfg.ExitGrace > 0 {
		return p.cfg.ExitGrace
	}
	return GenerationExitGrace
}
