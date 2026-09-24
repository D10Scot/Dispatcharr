package channel

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

// ErrInputFailed is VLC's "unable to open the MRL": input/manager.py:1059-1064
// closes the socket on it, which the main loop then reads as a connection
// failure. Only reachable when the profile's command is literally vlc or
// cvlc -- auto-detection never reports it (ffmpeg.AutoParse).
var ErrInputFailed = errors.New("channel: the transcode process could not open its input")

// TranscodeSource is the FFmpeg, VLC and Streamlink stream-profile
// architectures: a subprocess whose fd 1 is the video and whose fd 2 is
// parsed line by line. The port of input/manager.py's transcode half --
// _establish_transcode_connection, the stderr reader thread,
// _log_stderr_content and _parse_ffmpeg_stats -- behind the same one-method
// Source interface ProxySource implements.
//
// THE ARGV ARRIVES BUILT. Django ran StreamProfile.build_command on the
// answer (core/models.py:137-160: shlex.split of the profile's parameters,
// then the three {streamUrl}/{userAgent}/{channelId} substitutions), so
// Argv is what Python would spawn, and this relay carries no shell word
// splitter and no substitution table. Spec Amendment A4.1 has the ruling.
// The ONE transformation left here is Python's own, at input/manager.py:
// 808-812: a UDP upstream has every user-agent argument removed.
type TranscodeSource struct {
	// Command is the profile's executable: "ffmpeg", "vlc", "streamlink",
	// or an operator's path. It also selects the log parser
	// (ffmpeg.ToolFor), exactly as input/manager.py:797-803 does.
	Command string

	// Argv is the built argument list, without the command.
	Argv []string

	// URL is the provider URL the argv carries. Read for ONE thing: the
	// stream type, which decides the UDP filter. It is never logged and
	// never put in an error.
	URL string

	// UserAgent is the user agent Django substituted for {userAgent}, so
	// the UDP filter can find the arguments that carry it
	// (input/manager.py:811's `self.user_agent not in arg`).
	UserAgent string

	// ChunkSize is the read size off fd 1. Zero means 8192,
	// apps/proxy/config.py:7's CHUNK_SIZE, which input/manager.py:1843's
	// os.read uses. The same default, for the same reason, as ProxySource.
	ChunkSize int

	// Now is the detector's clock. Nil means time.Now.
	Now func() time.Time

	// channel is set by run() through attach: where stats and state go,
	// and where the detector's thresholds come from. THE SOURCE HOLDS NO
	// COPY OF buffering_speed OR buffering_timeout: they are read off the
	// channel's Tuning, the one snapshot of the tune's proxy_settings
	// (parity-matrix row 5), so there is no second field to drift from it.
	// An earlier draft carried both on this struct as well, and the first
	// tests written against it never armed, because the fields the tests
	// set were not the fields the detector read.
	channel *Channel

	mu    sync.Mutex
	cause error
}

// attach is the seam Channel.run uses to hand a source its channel. It is
// unexported and the interface it satisfies is package-private, so nothing
// outside this package can point a source at a channel it does not run on.
func (s *TranscodeSource) attach(c *Channel) { s.channel = c }

func (s *TranscodeSource) chunkSize() int {
	if s.ChunkSize > 0 {
		return s.ChunkSize
	}
	return 8192
}

func (s *TranscodeSource) log() *slog.Logger {
	if s.channel != nil && s.channel.log != nil {
		return s.channel.log
	}
	return slog.Default()
}

// argv applies the one transformation input/manager.py:808-812 applies at
// spawn time: on a UDP upstream every argument that contains the user agent,
// or "user-agent" or "user_agent" in any case, is dropped.
//
// Python filters self.transcode_cmd, which INCLUDES the command at index 0;
// a command containing "user-agent" would be dropped there and the spawn
// would fail on the first argument. That shape is not reproduced: the
// command is not an argument.
func (s *TranscodeSource) argv() []string {
	if StreamTypeOf(s.URL) != "udp" {
		return s.Argv
	}
	kept := make([]string, 0, len(s.Argv))
	for _, arg := range s.Argv {
		lower := strings.ToLower(arg)
		if (s.UserAgent != "" && strings.Contains(arg, s.UserAgent)) ||
			strings.Contains(lower, "user-agent") || strings.Contains(lower, "user_agent") {
			continue
		}
		kept = append(kept, arg)
	}
	return kept
}

// fail records why the source is ending and stops the process. The first
// cause wins; a later one (the SIGKILL's own exit status, say) does not
// overwrite it.
func (s *TranscodeSource) fail(cause error, cancel context.CancelFunc) {
	s.mu.Lock()
	if s.cause == nil {
		s.cause = cause
	}
	s.mu.Unlock()
	cancel()
}

func (s *TranscodeSource) failure() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.cause
}

// Run spawns the process and copies its fd 1 into sink until it ends, the
// detector times out, or ctx is done.
func (s *TranscodeSource) Run(parent context.Context, sink io.Writer) error {
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	// A fresh attempt has no cause yet: the run loop calls Run again on the
	// same source after a failure (input/manager.py's retry loop), and a
	// cause left over from the last attempt would end this one at once.
	s.mu.Lock()
	s.cause = nil
	s.mu.Unlock()

	proc, err := ffmpeg.Start(ctx, s.Command, s.argv())
	if err != nil {
		return fmt.Errorf("channel: starting the transcode process: %w", redact.Error(err))
	}

	var tuning Tuning
	if s.channel != nil {
		tuning = s.channel.tuning
	}
	reader := &stderrReader{source: s, cancel: cancel, inputPhase: true,
		detector: ffmpeg.Detector{Threshold: tuning.BufferingSpeed, Timeout: tuning.BufferingTimeout, Now: s.Now}}
	reader.tool, reader.toolKnown = ffmpeg.ToolFor(s.Command)
	stderrDone := make(chan struct{})
	go func() {
		defer close(stderrDone)
		proc.ReadStderr(reader.line)
	}()

	buf := make([]byte, s.chunkSize())
	var copyErr error
	for {
		n, readErr := proc.Stdout().Read(buf)
		if n > 0 {
			if _, writeErr := sink.Write(buf[:n]); writeErr != nil {
				copyErr = fmt.Errorf("channel: writing transcode bytes to the buffer: %w", redact.Error(writeErr))
				break
			}
		}
		if readErr != nil {
			break
		}
	}

	// fd 1 is closed. Python's _close_socket kills and waits half a second
	// (input/manager.py:1737-1749); a process that exits on its own inside
	// that window reports its real status, one that lingers is killed.
	exit := waitOrKill(proc)
	cancel()
	<-stderrDone

	switch {
	case copyErr != nil:
		return copyErr
	case s.failure() != nil:
		return s.failure()
	case parent.Err() != nil:
		return parent.Err()
	case exit == nil:
		return nil
	default:
		return exit
	}
}

func waitOrKill(proc *ffmpeg.Process) error {
	done := make(chan error, 1)
	go func() { done <- proc.Wait() }()
	select {
	case err := <-done:
		return err
	case <-time.After(ffmpeg.KillWait):
		proc.Kill()
		return <-done
	}
}

// stderrReader is the port of the stderr reader thread's per-line work:
// _read_stderr's frame= gate (input/manager.py:993), _parse_ffmpeg_stats
// and the buffering decision (:1102-1247), and _log_stderr_content's phase
// tracking, parser routing and log levels (:1031-1100).
type stderrReader struct {
	source     *TranscodeSource
	cancel     context.CancelFunc
	tool       ffmpeg.Tool
	toolKnown  bool
	inputPhase bool
	detector   ffmpeg.Detector
}

func (r *stderrReader) line(line string) {
	s := r.source
	log := s.log()

	if ffmpeg.IsProgressLine(line) {
		r.progress(line)
	}

	lower := strings.ToLower(line)
	// Phase tracking, :1041-1045: an Input or decoder line means the input
	// phase, an Output or encoder line ends it. Stream lines are parsed as
	// input info only during the input phase, so the OUTPUT stream lines
	// ffmpeg prints for its own remux do not overwrite the source's.
	if strings.HasPrefix(lower, "input #") || strings.Contains(lower, "decoder") {
		r.inputPhase = true
	}
	if strings.HasPrefix(lower, "output #") || strings.Contains(lower, "encoder") {
		r.inputPhase = false
	}

	var kind ffmpeg.Kind
	var info ffmpeg.Info
	var parsed bool
	if r.toolKnown {
		// Direct routing, :1054-1069.
		kind = ffmpeg.CanParse(r.tool, line)
		if kind == ffmpeg.KindVLCInputFailed {
			log.Warn("the transcode process could not open its input", "channel", s.channelID(), "line", redact.Line(line))
			s.fail(ErrInputFailed, r.cancel)
		} else if kind != "" {
			info, parsed = ffmpeg.Parse(kind, line)
		}
	} else {
		kind, info, parsed = ffmpeg.AutoParse(line)
	}
	if parsed && s.channel != nil {
		switch kind {
		case ffmpeg.KindVideo, ffmpeg.KindAudio, ffmpeg.KindInput:
			// FFmpeg lines count only during the input phase, :1079-1082.
			if r.inputPhase {
				s.channel.reportInfo(info)
			}
		default:
			// VLC and Streamlink lines count any time, :1083-1085.
			s.channel.reportInfo(info)
		}
	}

	// The log levels of :1088-1098, through redact.Line: ffmpeg's preamble
	// echoes the provider URL ("Input #0, mpegts, from '<url>':") and its
	// HLS demuxer echoes every segment URL, and Python logs both verbatim
	// at INFO -- a credential leak scripts/check_credential_logging.py
	// cannot see, because the variable is not named for a URL. Not
	// reproduced.
	redacted := redact.Line(line)
	switch {
	case containsAny(lower, "error", "failed", "cannot", "invalid", "corrupt"):
		log.Error("transcode process error", "channel", s.channelID(), "line", redacted)
	case containsAny(lower, "warning", "deprecated", "ignoring"):
		log.Warn("transcode process warning", "channel", s.channelID(), "line", redacted)
	case strings.HasPrefix(line, "frame=") || strings.Contains(line, "fps=") || strings.Contains(line, "speed="):
		// Python's trace level; slog has no lower level than Debug.
		log.Debug("transcode stats", "channel", s.channelID(), "line", redacted)
	case containsAny(lower, "input", "output", "stream", "video", "audio"):
		log.Info("transcode stream info", "channel", s.channelID(), "line", redacted)
	default:
		log.Debug("transcode process output", "channel", s.channelID(), "line", redacted)
	}
}

// progress is _parse_ffmpeg_stats: the four values to the channel, then the
// buffering decision on the speed.
func (r *stderrReader) progress(line string) {
	s := r.source
	p, ok := ffmpeg.ParseProgress(line)
	if !ok {
		return
	}
	if s.channel != nil {
		s.channel.reportProgress(p)
	}
	if p.Speed == nil {
		return
	}
	switch verdict := r.detector.Observe(*p.Speed); verdict {
	case ffmpeg.Started:
		// :1213-1226: the flag, the clock, a warning, the channel_buffering
		// event and the state.
		s.log().Warn("buffering started", "channel", s.channelID(), "speed", *p.Speed, "threshold", r.detector.Threshold)
		if s.channel != nil {
			s.channel.emit("channel_buffering", map[string]any{"speed": *p.Speed})
			s.channel.reportBuffering(true)
		}
	case ffmpeg.Continuing:
		// :1232-1234 re-writes the BUFFERING state on every sample; the
		// state is already buffering here, so there is nothing to write.
	case ffmpeg.TimedOut:
		// :1178-1211, parity-matrix row 1: the next stream, asked for from
		// THIS goroutine, as Python asks from its stderr thread. On success
		// the channel has parked the new source and cancelled this attempt.
		// On failure the channel stays buffering and the detector DEFERS:
		// the next ask is one buffering_timeout away, not one progress
		// record away as it was in Python (:1210, issue #302).
		bufferingFor := r.detector.BufferingFor()
		s.log().Error("buffering timeout reached", "channel", s.channelID(), "speed", *p.Speed, "buffering_for", bufferingFor.Round(100*time.Millisecond), "timeout", r.detector.Timeout)
		if s.channel != nil && s.channel.failoverFromBuffering(bufferingFor) {
			s.log().Info("switched to the next stream after a buffering timeout", "channel", s.channelID())
			// :1185-1186, the successful-switch branch: buffering cleared
			// and the clock forgotten. The process this reader belongs to
			// is about to be killed, so the reset is for fidelity, not
			// for the next record.
			r.detector.Reset()
		} else {
			s.log().Error("failed to switch to the next stream after a buffering timeout", "channel", s.channelID(), "retry_in", r.detector.Timeout)
			r.detector.Defer()
		}
	case ffmpeg.Ended:
		s.log().Info("buffering ended", "channel", s.channelID(), "speed", *p.Speed)
		if s.channel != nil {
			s.channel.reportBuffering(false)
		}
	case ffmpeg.Steady:
	}
}

func (s *TranscodeSource) channelID() string {
	if s.channel == nil {
		return ""
	}
	return s.channel.id
}

func containsAny(s string, words ...string) bool {
	for _, w := range words {
		if strings.Contains(s, w) {
			return true
		}
	}
	return false
}
