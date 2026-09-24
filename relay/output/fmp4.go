// Package output holds the OUTPUT-SIDE processes: a per-channel ffmpeg that
// reads the channel's shared TS ring on fd 0 and produces something else on
// fd 1.
//
// At 2c-6 there is exactly one such process, the fMP4 remux -- the port of
// apps/proxy/live_proxy/output/fmp4/{manager,buffer}.py -- and the package
// exists as its own concern rather than inside `channel` for the reason the
// spec's repo-layout paragraph gives for every other split: the input-side
// source (`channel`, `ffmpeg`) answers "where do this channel's bytes come
// from", and this answers "what else is made out of them once they are here".
//
// 2c-7 ADDS A DIMENSION HERE AND REWRITES NOTHING. An Output Profile is the
// same shape -- one ffmpeg per (channel, profile), reading the same ring on
// fd 0 -- differing in three places this package already parameterises: the
// argv (an OutputProfile's built command rather than the remux literal), the
// SINK (a second buffer.Ring of MPEG-TS rather than a buffer.Fragments of
// MP4 boxes), and the key a pipeline is registered under, which is already the
// compound string Python's _parse_output_key splits (`fmp4`, `fmp4:p3`).
// Config.Command/Config.Argv and Channel.AttachOutput's format key are those
// three seams; what 2c-7 adds is a second Pipeline constructor and a second
// sink type, not a change to the lifecycle, the refcount or the spawn.
//
// 2c-7 DID EXACTLY THAT, and this file's name is now narrower than its
// contents: Pipeline, its supervisor, its writer and its stop are shared by
// both processes and live here, while profile.go holds only what the Output
// Profile adds. The file is NOT split, deliberately -- a move shows in a diff
// as a whole delete and a whole add, and every line of 2c-6's reviewed prose
// would re-enter review to buy a better file name (the 2c-7 plan's Ruling R1).
package output

import (
	"bytes"
	"context"
	"encoding/binary"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// FormatFMP4 is the output-format key an fMP4 client tunes under, and the
// value channel_status.py:567 records for it in the client registry.
const FormatFMP4 = "fmp4"

// RemuxCommand and RemuxArgv are output/fmp4/manager.py:32-45's
// FFMPEG_REMUX_CMD, token for token, with the command split off the front the
// way ffmpeg.Start takes it.
//
// A LITERAL, NOT A SETTING, and therefore not subject to Amendment A1.4's "off
// the wire or the tune fails" rule. A1.4 is about proxy_settings -- values an
// operator changes and Python reads through ConfigHelper -- and this list is
// none of those: it is a module constant in the relay's own source, in the same
// class as ffmpeg.KillWait and InitSegmentTimeout below. Constraint 8's rule
// applies instead: it carries its source file:line and a test asserts the same
// tokens against the same location.
//
// The bitstream filter is what the second list exists for. `aac_adtstoasc`
// converts AAC's ADTS framing to the raw form MP4 requires and is REQUIRED when
// the source audio is AAC; for AC3, EAC3, MP3 and the rest ffmpeg errors out on
// it, which is what the stderr reader watches for and what argvNoBSF is the
// retry with (manager.py:29-31, :46-57, :373-378).
const RemuxCommand = "ffmpeg"

// RemuxArgv is FFMPEG_REMUX_CMD[1:].
func RemuxArgv() []string {
	return []string{
		"-loglevel", "error",
		"-f", "mpegts",
		"-i", "pipe:0",
		"-c", "copy",
		"-map", "0",
		"-bsf:a", "aac_adtstoasc",
		"-use_editlist", "0",
		"-flush_packets", "1",
		"-f", "mp4",
		"-movflags", "frag_keyframe+delay_moov+default_base_moof",
		"pipe:1",
	}
}

// RemuxArgvNoBSF is FFMPEG_REMUX_CMD_NO_BSF[1:] (manager.py:46-57). Note it
// drops `-map 0` as well as the filter, exactly as Python's second list does --
// a difference easy to miss and reproduced rather than tidied.
func RemuxArgvNoBSF() []string {
	return []string{
		"-loglevel", "error",
		"-f", "mpegts",
		"-i", "pipe:0",
		"-c", "copy",
		"-use_editlist", "0",
		"-flush_packets", "1",
		"-f", "mp4",
		"-movflags", "frag_keyframe+delay_moov+default_base_moof",
		"pipe:1",
	}
}

const (
	// InitSegmentTimeout is manager.py:60's INIT_SEGMENT_TIMEOUT: how long a
	// client waits for the remux's init segment before giving up and ending
	// its body (generator.py:182, :196-200).
	InitSegmentTimeout = 15 * time.Second

	// MaxInitSegmentBytes is manager.py:334's 10 MB: a remux whose output has
	// no moof box in its first 10 MB is not producing fragmented MP4, and the
	// pipeline aborts rather than buffering forever.
	MaxInitSegmentBytes = 10 * 1024 * 1024

	// readSize is manager.py:294's 65536: the read off the remux's fd 1.
	// output/profile/manager.py:231 is the same literal for the Output
	// Profile transcode, so both processes read in the same unit and one
	// constant carries both citations (2c-7).
	readSize = 65536

	// stopJoinWait is manager.py:168's `t.join(timeout=5)`: how long a stop
	// gives the reader to finish flushing after fd 0 is closed, before the
	// process is killed.
	stopJoinWait = 5 * time.Second

	// bsfErrorFilter and bsfErrorPhrase are manager.py:373's two substrings.
	// BOTH must be present, as the `and` there requires.
	bsfErrorFilter = "aac_adtstoasc"
	bsfErrorPhrase = "is not supported by the bitstream filter"
)

// moofBox is manager.py:63's MOOF_BOX_TYPE.
var moofBox = []byte("moof")

// findMoofOffset is manager.py:71-90's _find_moof_offset: the byte offset of
// the first `moof` box at or after start, or -1.
//
// MP4 boxes are [4-byte big-endian length][4-byte type][payload]. A length
// below 8 is not a valid box, and Python advances ONE byte on it rather than
// giving up. That is NOT a resynchronisation: any length of 8 or more is
// trusted and strided over, so a scan that starts off a box boundary reads a
// garbage length, jumps past every real box and returns -1 (issues #306 and
// #119). This function is therefore used only where the scan starts ON a
// boundary -- the init segment from offset 0, a fragment's successor from its
// own moof's end -- and resyncOffset below is what a misaligned buffer uses.
//
// Python's `except struct.error` arm is UNREACHABLE: unpack_from cannot fail
// while offset+8 <= len(data). Not reproduced, because there is nothing to
// reproduce.
func findMoofOffset(data []byte, start int) int {
	offset := start
	for offset+8 <= len(data) {
		size := int64(binary.BigEndian.Uint32(data[offset : offset+4]))
		if bytes.Equal(data[offset+4:offset+8], moofBox) {
			return offset
		}
		if size < 8 {
			offset++
			continue
		}
		next := int64(offset) + size
		if next > int64(len(data)) {
			// Python assigns offset += box_size and the loop condition then
			// fails, returning -1. Same answer, without the conversion.
			return -1
		}
		offset = int(next)
	}
	return -1
}

// minMoofBox is the smallest real moof, and the smallest length resyncOffset
// accepts for a candidate: its own 8-byte header plus an mfhd, 16 bytes. A
// "moof" shorter than that is garbage that happens to spell the type, and an
// aligned one is resynchronised past rather than trusted (flush). Adopted from
// #348's A-4.
const minMoofBox = 16

// maxFragmentBytes is the most the working buffer holds while a fragment has
// no end in sight -- a valid moof followed by a box whose length is corrupt,
// which makes the fragment's end unfindable and would otherwise hold the
// buffer open toward a 4 GiB length. Past it the fragment is abandoned and
// the scanner resynchronises. The same ceiling also guards an aligned moof
// whose own length is corrupt, but that check is a backstop only (flush):
// since maxMoofBoxBytes bounds an aligned moof's own length before this
// ceiling is ever consulted for one, it cannot fire while maxMoofBoxBytes
// stays below it, as it does today (1 MiB against 64 MiB) -- kept for the
// invariant that a fragment never grows past the ceiling however it fails to
// end, and live again only if maxMoofBoxBytes is ever raised past it. 64 MiB
// is 50 Mbit/s over a 10-second keyframe interval with margin; adopted from
// #348's A-4.
const maxFragmentBytes = 64 << 20

// maxMoofBoxBytes is the largest length resyncOffset accepts for a candidate
// moof box's OWN header -- the moof, not the fragment: a moof holds a few
// track headers and a sample table and runs to kilobytes, where the mdat
// after it can run to megabytes. A "moof" literal inside a payload reads a
// length that is garbage; one past this bound is refused as a resync point
// rather than trusted, because the aligned path would then wait for that many
// bytes before publishing anything. flush's aligned check refuses the same
// bound (review round 1 of #399): an ALIGNED moof declaring more than this is
// resynchronised past at once rather than waited on. That is why flush's
// ceiling-abandon for an aligned moof's own corrupt length is now a backstop
// that cannot fire in practice -- see maxFragmentBytes.
const maxMoofBoxBytes = 1 << 20

// resyncTail is how much of a working buffer with no resync point in it is
// kept: the most of a moof header that can sit at the end without its "moof"
// literal being complete -- a four-byte length and three bytes of the type.
const resyncTail = 7

// resyncOffset finds the next plausible moof header at or after start in a
// buffer that is NOT aligned on a box boundary, the fix for issues #306 and
// #119. It searches for the four-byte type literal and checks the length in
// front of it, rather than striding by lengths it cannot trust: the first
// candidate whose length is between minMoofBox and maxMoofBoxBytes wins. -1
// when there is none.
func resyncOffset(data []byte, start int) int {
	for from := start; from+8 <= len(data); {
		i := bytes.Index(data[from+4:], moofBox)
		if i < 0 {
			return -1
		}
		at := from + i
		if size := binary.BigEndian.Uint32(data[at : at+4]); size >= minMoofBox && size <= maxMoofBoxBytes {
			return at
		}
		from = at + 1
	}
	return -1
}

// scanner turns the remux's fd 1 byte stream into an init segment and a
// sequence of fragments, the port of _reader_loop's body (manager.py:289-349)
// and _flush_complete_fragments (:252-287).
type scanner struct {
	out *buffer.Fragments

	init       []byte
	initStored bool
	frag       []byte

	// ceiling overrides maxFragmentBytes for one scanner, for tests; zero
	// means the constant. A field rather than a package variable a test
	// lowers, so no test can race another scanner's read of it.
	ceiling int
}

func (s *scanner) fragmentCeiling() int {
	if s.ceiling > 0 {
		return s.ceiling
	}
	return maxFragmentBytes
}

// abandon gives up a fragment whose end cannot be found: dropping one byte
// misaligns the buffer, so the next pass of flush resynchronises past the
// moof that could not be bounded.
func (s *scanner) abandon() { s.frag = s.frag[1:] }

// ErrNoInitSegment is the abort at manager.py:334-339: 10 MB of remux output
// with no moof box in it.
var ErrNoInitSegment = fmt.Errorf("output: no moof box in the first %d bytes of the remux output", MaxInitSegmentBytes)

// write feeds one read's worth of remux output through the scanner.
func (s *scanner) write(data []byte) error {
	if !s.initStored {
		s.init = append(s.init, data...)
		at := findMoofOffset(s.init, 0)
		if at < 0 {
			if len(s.init) > MaxInitSegmentBytes {
				return ErrNoInitSegment
			}
			return nil
		}
		// EVERYTHING BEFORE THE FIRST moof IS THE INIT SEGMENT (ftyp, moov),
		// and the bytes from it onwards are the first fragment's beginning
		// (manager.py:320-332).
		segment := make([]byte, at)
		copy(segment, s.init[:at])
		s.frag = append(s.frag, s.init[at:]...)
		s.init = nil
		s.initStored = true
		s.out.SetInit(segment)
		s.flush()
		return nil
	}
	s.frag = append(s.frag, data...)
	s.flush()
	return nil
}

// flush publishes every COMPLETE fragment in the working buffer. A fragment
// ends where the next moof box begins, so the last one is always held back
// until its successor arrives -- manager.py:277-279's `break  # Current
// fragment not complete yet`, reproduced exactly, and the reason a remux that
// stops mid-stream leaves one fragment unpublished until `final` runs.
func (s *scanner) flush() {
	for len(s.frag) >= 8 {
		size := int64(binary.BigEndian.Uint32(s.frag[0:4]))
		if !bytes.Equal(s.frag[4:8], moofBox) || size < minMoofBox || size > maxMoofBoxBytes {
			// manager.py:259-266: the stream is not aligned to a moof, so drop
			// bytes until one is found. start=1, not 0, or this would find the
			// box it has already rejected. Through resyncOffset, not
			// findMoofOffset: Python strided from offset 1 by a garbage length
			// and cleared the whole buffer on the -1 it got (#306, #119). A
			// moof shorter than minMoofBox is not one either: aligned on it,
			// the seed returned without consuming anything and the buffer
			// grew with every write (#348's A-4). A moof longer than
			// maxMoofBoxBytes is not a real one either -- resyncOffset already
			// refuses it as a resync candidate for the same reason, and
			// waiting for it here would hold the buffer toward the 64 MiB
			// ceiling for a length no real moof ever declares (review round 1
			// of #399).
			next := resyncOffset(s.frag, 1)
			if next < 0 {
				// Nothing yet. Keep only the tail a header could be arriving
				// in, so the buffer stays bounded and a moof whose header
				// straddles this read is still found on the next.
				if len(s.frag) > resyncTail {
					s.frag = append(s.frag[:0], s.frag[len(s.frag)-resyncTail:]...)
				}
				return
			}
			s.frag = s.frag[next:]
			continue
		}
		if size > int64(len(s.frag)) {
			// _find_moof_offset(frag_buf, start=moof_size) returns -1 for a
			// start past the end, and manager.py:279 breaks. Same answer --
			// unless the moof's own length is corrupt and the wait would
			// never end. This ceiling check is a backstop, not a live path:
			// size is bounded by maxMoofBoxBytes before flush ever reaches
			// here (the condition above), so this arm cannot see a size large
			// enough to hold the wait open past fragmentCeiling() while
			// maxMoofBoxBytes stays below it, as it does today. Kept for the
			// invariant -- a fragment never grows past the ceiling, however
			// it fails to end -- and live again only if maxMoofBoxBytes is
			// ever raised past maxFragmentBytes.
			if len(s.frag) > s.fragmentCeiling() {
				s.abandon()
				continue
			}
			return
		}
		next := findMoofOffset(s.frag, int(size))
		if next < 0 {
			// The same wait, for the box after the moof.
			if len(s.frag) > s.fragmentCeiling() {
				s.abandon()
				continue
			}
			return
		}
		s.out.Put(s.frag[:next])
		s.frag = s.frag[next:]
	}
}

// final publishes whatever is left when fd 1 ends: manager.py:346-348's
// `finally: if frag_buf and init_stored: put_fragment(...)`. The last fragment
// has no successor to bound it, so without this it would never be published.
//
// The buffer must be aligned on a real moof to be a fragment at all -- the
// same idiom flush uses to recognise one. Without this, ending mid-desync
// left only the up-to-resyncTail-byte remnant a resync-with-nothing-found
// kept, and that got published as though it were a whole fragment: junk at
// the end of every fMP4 viewer's stream (review round 1 of #399).
func (s *scanner) final() {
	if s.initStored && len(s.frag) >= 8 && bytes.Equal(s.frag[4:8], moofBox) {
		s.out.Put(s.frag)
		s.frag = nil
	}
}

// Config is what Start needs.
type Config struct {
	// ChannelID is the channel this pipeline serves, for logs.
	ChannelID string

	// Source is the channel's TS ring: the remux's fd 0.
	Source *buffer.Ring

	// JoinBehind is how far behind live the WRITER starts reading the source,
	// from the channel's Tuning. manager.py:208-212 positions the writer with
	// new_client_behind_seconds "so the fMP4 buffer is pre-populated by the
	// time the first client connects".
	JoinBehind time.Duration

	// Retention and BudgetBytes bound the fragment buffer, from the same
	// channel Tuning and manager config the TS ring is built from.
	Retention   time.Duration
	BudgetBytes int

	// Remux is the process to spawn. Its zero value means the production
	// remux; a test substitutes a stand-in, and 2c-7 substitutes an Output
	// Profile's built command.
	Remux

	// Log is the logger. Nil means slog.Default().
	Log *slog.Logger

	// Now is the fragment buffer's clock. Nil means time.Now.
	Now func() time.Time
}

// Remux names the process that produces an output format: the seam a test and
// 2c-7 both reach through. A zero Remux is the production fMP4 remux.
type Remux struct {
	// Command is the executable. Empty means RemuxCommand.
	Command string

	// Argv is its argument list. Nil means RemuxArgv().
	Argv []string

	// ArgvNoBSF is the retry list for a non-AAC source. Nil means
	// RemuxArgvNoBSF() when Argv is also nil, and Argv otherwise -- a
	// stand-in has no bitstream filter to drop, so the retry is the same
	// process.
	ArgvNoBSF []string
}

func (c Config) command() string {
	if c.Command != "" {
		return c.Command
	}
	return RemuxCommand
}

func (c Config) argv() []string {
	if c.Argv != nil {
		return c.Argv
	}
	return RemuxArgv()
}

func (c Config) argvNoBSF() []string {
	if c.ArgvNoBSF != nil {
		return c.ArgvNoBSF
	}
	if c.Argv != nil {
		// A caller that supplied one list and not the other means the same
		// process either way: a stand-in has no bitstream filter to drop.
		return c.Argv
	}
	return RemuxArgvNoBSF()
}

// Pipeline is one running output process for one (channel, format): the
// subprocess, the goroutine that feeds it the channel's ring, the goroutine
// that scans its output into fragments, and the goroutine that reads its
// stderr.
//
// THERE IS NO OWNER LOCK AND NO STATE KEY. output_owner and output_state
// (manager.py:437-449) existed so a second uWSGI worker could tell whether
// another worker's remux was already running for this channel and, if so, poll
// until it said `active` rather than starting a second one
// (server.py:1300-1338). With one relay process, the map that holds this
// Pipeline IS that answer, and the init segment is the one readiness signal --
// spec D2's key-family table says exactly this ("output_owner deleted with the
// ownership lease, same reasoning"). The TTL refresh loop
// (_refresh_redis_ttls, :456-483) goes with them: it exists to stop an orphaned
// key outliving the process that wrote it, and nothing here can be orphaned.
type Pipeline struct {
	cfg   Config
	log   *slog.Logger
	frags *buffer.Fragments

	// ring is the SECOND SINK, 2c-7's: an Output Profile transcode writes
	// MPEG-TS into a buffer.Ring where the remux writes MP4 boxes into
	// frags. Exactly one of the two is non-nil for the life of a pipeline,
	// set by the constructor and never changed, so the three branches that
	// read it need no lock.
	ring *buffer.Ring

	// bsf is whether this pipeline's stderr is watched for the
	// aac_adtstoasc refusal and restarted without the filter. TRUE ONLY FOR
	// THE REMUX: an Output Profile's argv is the operator's, and Python's
	// OutputProfileManager never scans its stderr for anything
	// (output/profile/manager.py:270-295), so a profile that happened to
	// carry `-bsf:a aac_adtstoasc` must not be restarted here when Python
	// would leave it dead.
	bsf bool

	cancel context.CancelFunc
	done   chan struct{}
}

// closeSink shuts whichever buffer this pipeline writes, which is what wakes a
// client waiting on it and ends every read loop.
func (p *Pipeline) closeSink() {
	if p.ring != nil {
		p.ring.Close()
		return
	}
	p.frags.Close()
}

// read is one generation's fd 1 into this pipeline's sink.
//
// Only the fMP4 reader can fail -- ErrNoInitSegment, the 10 MB abort -- so the
// transcode arm reports nothing and this returns nil for it.
func (p *Pipeline) read(proc *ffmpeg.Process) error {
	if p.ring != nil {
		p.profileReader(proc)
		return nil
	}
	return p.reader(proc)
}

// Start spawns the remux and returns once its process is running. The pipeline
// then runs until Stop is called or ctx is done; Done is closed once its
// process has been reaped and its buffer is shut.
//
// THE FIRST SPAWN IS SYNCHRONOUS, and that is what makes a spawn failure a 500
// rather than an empty 200. Python's ensure_output_format calls
// FMP4RemuxManager.start() inline (server.py:1363) before views.py builds the
// StreamingHttpResponse, so a posix_spawn that raises reaches stream_ts's outer
// handler and the client gets a 500 with no body (views.py:789-798 returns 500
// on a False, and :823-827 catches the raise). A wholly asynchronous Start
// would turn every such failure into a 200 whose body is empty, which is the
// SAME answer this relay gives for an init-segment timeout -- two different
// faults made indistinguishable to a client and to a log reader. The retry
// without the bitstream filter is asynchronous, because by then the response is
// already open in both implementations.
func Start(ctx context.Context, cfg Config) (*Pipeline, error) {
	log := cfg.Log
	if log == nil {
		log = slog.Default()
	}
	log = log.With("channel", cfg.ChannelID, "format", FormatFMP4)

	ctx, cancel := context.WithCancel(ctx)
	proc, err := ffmpeg.StartPiped(ctx, cfg.command(), cfg.argv())
	if err != nil {
		cancel()
		return nil, fmt.Errorf("output: starting the remux: %w", redact.Error(err))
	}
	p := &Pipeline{
		cfg: cfg,
		log: log,
		frags: buffer.NewFragments(buffer.FragmentsConfig{
			BudgetBytes: cfg.BudgetBytes,
			Retention:   cfg.Retention,
			Now:         cfg.Now,
		}),
		bsf:    true,
		cancel: cancel,
		done:   make(chan struct{}),
	}
	go p.run(ctx, proc)
	return p, nil
}

// Fragments is the buffer an fMP4 client reads. Nil for an Output Profile
// transcode, whose sink is Ring.
func (p *Pipeline) Fragments() *buffer.Fragments { return p.frags }

// Ring is the buffer an Output Profile transcode writes and its clients read.
// Nil for the fMP4 remux, whose sink is Fragments.
func (p *Pipeline) Ring() *buffer.Ring { return p.ring }

// Done is closed once the pipeline's process has ended and its buffer is shut.
func (p *Pipeline) Done() <-chan struct{} { return p.done }

// Stop ends the pipeline and waits for it, bounded by stopJoinWait plus
// ffmpeg.KillWait -- manager.py:151-181's stop(), whose own budget is the same
// join plus the same kill.
func (p *Pipeline) Stop() {
	p.cancel()
	select {
	case <-p.done:
	case <-time.After(stopJoinWait + ffmpeg.KillWait):
		p.log.Warn("the remux did not stop in time")
	}
}

// run is the supervisor: one generation, and at most one restart without the
// bitstream filter.
//
// ONE RESTART, NOT A LOOP, and that is Python's own bound rather than a choice.
// _handle_bsf_error (manager.py:382-431) restarts with FFMPEG_REMUX_CMD_NO_BSF,
// whose stderr can never carry the aac_adtstoasc message because the filter is
// not in its argv -- so a second BSF restart is unreachable there, and the
// generation bound here makes it explicit rather than relying on the argv to
// enforce it. A remux that fails for any OTHER reason is not restarted, by
// either implementation.
//
// THE DEAD BRANCH IS NOT REPRODUCED, AND IS FILED AS [#307].
// manager.py:403-413 sets `self.running = True` and then tests
// `if not self.running:` to catch a stop() that arrived during the restart --
// a condition that cannot hold two statements after the assignment, so the
// cleanup it guards has never run, and a stop() landing in that window leaves
// the restarted process and its Redis keys behind until the next teardown.
// There is no dead branch to reproduce, so none is; the window it was written
// for is real and IS handled here, by the context: a cancelled ctx ends run
// before the second generation is spawned, and a StartPiped against a cancelled
// context fails rather than leaving a process behind.
func (p *Pipeline) run(ctx context.Context, proc *ffmpeg.Process) {
	defer close(p.done)
	// The buffer closes with the pipeline, which is what wakes a client
	// waiting for an init segment that will now never arrive and what ends a
	// client's read loop.
	defer p.closeSink()

	for generation := 0; ; generation++ {
		bsf, err := p.generation(ctx, proc)
		switch {
		case err != nil:
			p.log.Error("the remux failed", "error", redact.Error(err))
		case ctx.Err() != nil:
			p.log.Info("the remux stopped")
		default:
			p.log.Info("the remux ended")
		}
		if !bsf || generation > 0 || ctx.Err() != nil {
			return
		}
		p.log.Warn("non-AAC audio detected, retrying the remux without the bitstream filter")
		retry, startErr := ffmpeg.StartPiped(ctx, p.cfg.command(), p.cfg.argvNoBSF())
		if startErr != nil {
			p.log.Error("the remux could not be restarted", "error", redact.Error(startErr))
			return
		}
		proc = retry
	}
}

// generation runs one remux process to its end and reports whether its stderr
// asked for the no-bitstream-filter retry.
func (p *Pipeline) generation(parent context.Context, proc *ffmpeg.Process) (bsf bool, err error) {
	// A generation-scoped context so the BSF retry stops THIS generation's
	// writer without ending the pipeline: the writer blocks in Ring.Wait when
	// the channel is quiet, and a killed process alone would not wake it until
	// the next chunk arrived.
	ctx, cancel := context.WithCancel(parent)
	defer cancel()

	// The BSF flag is written by the stderr goroutine and read after it has
	// been joined, so the join is the happens-before edge and no mutex is
	// needed. A bool read while that goroutine still ran WOULD be a race, and
	// -race would say so.
	var wantRetry bool
	stderrDone := make(chan struct{})
	go func() {
		defer close(stderrDone)
		proc.ReadStderr(func(line string) {
			// redact.Line, because ffmpeg echoes what it was given and an
			// input-side URL can reach an output-side diagnostic through a
			// metadata tag. Python logs these at WARNING unredacted
			// (manager.py:372), the same divergence 2c-4's Ruling R8 records
			// for the input side.
			p.log.Warn("remux stderr", "line", redact.Line(line))
			if p.bsf && strings.Contains(line, bsfErrorFilter) && strings.Contains(line, bsfErrorPhrase) {
				wantRetry = true
				// manager.py:374-378 starts a thread that kills the process
				// (:387-389). Kill is that SIGKILL to the whole group; cancel
				// is what stops this generation's writer.
				proc.Kill()
				cancel()
			}
		})
	}()

	writerDone := make(chan struct{})
	go func() {
		defer close(writerDone)
		p.writer(ctx, proc)
	}()

	readerDone := make(chan struct{})
	var readErr error
	go func() {
		defer close(readerDone)
		readErr = p.read(proc)
	}()

	select {
	case <-readerDone:
		// fd 1 ended on its own: EOF, the 10 MB abort, or the process died.
	case <-ctx.Done():
		// manager.py:158-171's stop(): close fd 0 FIRST so ffmpeg flushes its
		// last fragment and exits cleanly, and only kill it if the reader has
		// not finished within the join budget.
		proc.CloseStdin()
		select {
		case <-readerDone:
		case <-time.After(stopJoinWait):
		}
	}

	cancel()
	proc.CloseStdin()
	proc.Kill()
	// THE STDERR DRAIN IS JOINED BEFORE THE REAP (#304). The parent-owned
	// stderr pipe in relay/ffmpeg is what makes the drain correct whatever the
	// order -- cmd.Wait no longer closes the reader's end -- so this is
	// belt and braces rather than the fix. It is written this way regardless,
	// because an ordering that is correct only because of a detail two
	// packages away is an ordering the next reader will get wrong. Safe from
	// deadlock by the Kill above: SIGKILL cannot be ignored, so the child's
	// write end closes and the reader reaches EOF.
	<-stderrDone
	_ = proc.Wait()
	<-writerDone
	<-readerDone
	return wantRetry, readErr
}

// writer is _writer_loop (manager.py:204-250): the channel's TS ring into the
// remux's fd 0, starting new_client_behind_seconds behind live.
//
// PYTHON'S CATCH-UP BRANCH IS NOT PORTED, and the reason is that the condition
// it recovers from cannot arise here. manager.py:237-240 jumps the writer to
// `ts_buffer.index - 5` when it is more than 20 chunks behind AND the last read
// returned nothing -- a pair that is only simultaneously true through
// get_optimized_client_data's expiry arm (input/buffer.py:353-357), which
// returns an empty list unchanged rather than the chunks it could not find,
// because the chunks expired out of Redis under the reader. Ring.Read cannot
// return that state: eviction and the read are under one lock, and a cursor
// behind the oldest resident chunk is advanced TO that chunk with `skipped`
// reporting the gap. The recovery is therefore performed, by a different
// mechanism, and it recovers to the OLDEST RESIDENT chunk rather than to
// head-5 -- a stated divergence in the safe direction, losing fewer fragments
// than Python does.
func (p *Pipeline) writer(ctx context.Context, proc *ffmpeg.Process) {
	// manager.py:244-249's `finally`: fd 0 closes when the writer stops, which
	// is what makes a remux whose source ended flush and exit rather than
	// waiting on a pipe nobody will write to again.
	defer proc.CloseStdin()

	source := p.cfg.Source
	cursor := source.Head()
	if p.cfg.JoinBehind > 0 {
		cursor = source.Join(p.cfg.JoinBehind)
	}
	stdin := proc.Stdin()

	for {
		chunks, next, skipped := source.Read(cursor)
		if skipped > 0 {
			p.log.Warn("the remux fell behind the channel's ring", "skipped", skipped, "head", source.Head())
		}
		if len(chunks) > 0 {
			cursor = next
			for _, chunk := range chunks {
				if _, err := stdin.Write(chunk); err != nil {
					// manager.py:231-236: a broken stdin ends the writer and
					// the whole remux with it. Not logged with the error
					// itself at WARNING as Python does: an EPIPE here is the
					// ordinary end of every stopped remux.
					p.log.Debug("the remux stopped reading its input")
					return
				}
			}
			continue
		}
		if err := source.Wait(ctx, cursor); err != nil {
			return
		}
	}
}

// reader is _reader_loop (manager.py:289-349): fd 1 into the fragment buffer,
// with the init segment split off the front.
func (p *Pipeline) reader(proc *ffmpeg.Process) error {
	s := &scanner{out: p.frags}
	defer s.final()

	buf := make([]byte, readSize)
	stdout := proc.Stdout()
	for {
		n, err := stdout.Read(buf)
		if n > 0 {
			if writeErr := s.write(buf[:n]); writeErr != nil {
				return writeErr
			}
		}
		if err != nil {
			return nil
		}
	}
}
