package output

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strconv"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// The Output Profile transcode: the port of
// apps/proxy/live_proxy/output/profile/manager.py.
//
// ONE PROCESS PER (channel, profile) PAIR, shared by every client on that
// profile -- parity-matrix row 11, "ten AC3 clients cost one ffmpeg". It reads
// the channel's own TS ring on fd 0 and writes MPEG-TS on fd 1 into a SECOND
// buffer.Ring, which is then what its clients read instead of the channel's.
// Everything about starting it, feeding it, supervising it and stopping it is
// Pipeline's, unchanged from 2c-6; what this file adds is the sink, the
// command line's source and the registry key.

// FormatMPEGTS is the output-format key a plain TS client tunes under, and the
// value channel_status.py:567 records for it. Named here rather than imported
// from httpapi because ProfileKey below composes it.
const FormatMPEGTS = "mpegts"

// ProfileKey is the registry key an Output Profile transcode runs under:
// `mpegts:p<id>`, which is EXACTLY the Redis format namespace
// OutputProfileManager builds for itself (output/profile/manager.py:303, :315,
// :325, :332, :349, :364 -- SIX sites, all the literal
// f"mpegts:p{self.profile_id}". A seventh line, :361, carries the same text in
// a docstring and is not a site).
//
// ALWAYS mpegts, WHATEVER THE CLIENT'S OUTPUT FORMAT, and that is Python's
// shape rather than a simplification: the transcode's own output is MPEG-TS
// (an OutputProfile reads raw TS on pipe:0 and writes to pipe:1,
// core/models.py:173-174), so an fMP4 client on a profile gets TWO processes
// chained -- this one under `mpegts:p3`, and the remux under `fmp4:p3` reading
// this one's ring. views.py:765-792 spells that chain out: ensure_output_profile
// first, get_buffer(profile=) second, ensure_output_format(f"fmp4:p{id}",
// source_buffer=that) third.
func ProfileKey(profileID int) string {
	return FormatKey(FormatMPEGTS, &profileID)
}

// FormatKey composes an output registry key from a format and an optional
// profile id: views.py:731-734's `f'{fmt}:p{id}' if profile else fmt`, and the
// inverse of server.py:1367-1382's _parse_output_key. A nil or zero id is the
// bare format.
func FormatKey(format string, profileID *int) string {
	if profileID == nil {
		return format
	}
	return format + ":p" + strconv.Itoa(*profileID)
}

// ErrProfileCommandAbsent is a profile whose built command line is empty or
// whose argv[0] is blank.
//
// Python reaches the same failure one step later and reports it the same way:
// posix_spawn_proc([""]) raises, OutputProfileManager.start returns False
// (manager.py:89-95), ensure_output_profile returns False, and views.py:767-772
// answers 500. Named here so the log says which of the two 500s this is.
var ErrProfileCommandAbsent = errors.New("output: the Output Profile has no command to spawn")

// ProfileConfig is what StartProfile needs.
//
// DELIBERATELY NOT Config, and not Config.Remux either. Remux's zero value
// means "the production fMP4 remux" (Config.command() falls back to
// RemuxCommand and Config.argv() to RemuxArgv), which is exactly the wrong
// default here: an Output Profile with no command must fail the tune, not
// quietly become a remux. 2c-6's Ruling R1 named Remux as the seam 2c-7 would
// reach through; reading its zero-value semantics is what changed that (the
// 2c-7 plan's Ruling R3).
type ProfileConfig struct {
	// ChannelID and ProfileID identify the pair, for logs.
	ChannelID string
	ProfileID int

	// Source is the channel's TS ring: the transcode's fd 0.
	Source *buffer.Ring

	// Command and Argv are core/models.py:200-203's build_command() split at
	// element 0 -- the command, then its arguments. Off the wire, never
	// built here: spec Amendment A4.1, and the relay carries no word
	// splitter.
	Command string
	Argv    []string

	// JoinBehind is how far behind live the writer starts reading the
	// source. manager.py:180-184 positions it with new_client_behind_seconds,
	// exactly as the fMP4 remux's writer is positioned.
	JoinBehind time.Duration

	// Retention, ChunkBytes and BudgetBytes bound the output ring, from the
	// channel's own Tuning and budget -- the same numbers the channel's ring
	// is built from, because Python builds the profile's StreamBuffer from
	// the same Config (manager.py:301-310, a plain StreamBuffer).
	Retention   time.Duration
	ChunkBytes  int
	BudgetBytes int

	// Log is the logger. Nil means slog.Default().
	Log *slog.Logger

	// Now is the output ring's clock. Nil means time.Now.
	Now func() time.Time
}

// StartProfile spawns the Output Profile transcode and returns once its
// process is running.
//
// SYNCHRONOUS FOR THE SAME REASON Start is (2c-6's Ruling R4):
// ensure_output_profile calls OutputProfileManager.start() inline
// (server.py:1532) before views.py builds the StreamingHttpResponse, so a
// spawn that fails reaches views.py:767-772 and the client gets a 500 with a
// body. A wholly asynchronous start would make that failure a 200 with an
// empty body instead.
func StartProfile(ctx context.Context, cfg ProfileConfig) (*Pipeline, error) {
	log := cfg.Log
	if log == nil {
		log = slog.Default()
	}
	key := ProfileKey(cfg.ProfileID)
	log = log.With("channel", cfg.ChannelID, "format", key)

	if cfg.Command == "" {
		return nil, ErrProfileCommandAbsent
	}

	ctx, cancel := context.WithCancel(ctx)
	proc, err := ffmpeg.StartPiped(ctx, cfg.Command, cfg.Argv)
	if err != nil {
		cancel()
		return nil, fmt.Errorf("output: starting the Output Profile transcode: %w", redact.Error(err))
	}
	p := &Pipeline{
		// THE COMMAND FIELDS ARE FILLED IN even though nothing restarts this
		// pipeline: `bsf` is false, so run's retry arm is unreachable. Left
		// EMPTY, as a first draft had them, Config.command() would fall back
		// to RemuxCommand and Config.argv() to RemuxArgv -- so if that arm
		// ever did become reachable it would spawn the fMP4 REMUX in place of
		// the operator's transcode. Found by the break-check that set `bsf`
		// to true: the spawn count stayed at 1 because the second process was
		// a real ffmpeg and not the stand-in. Two guards, and the structural
		// one is this.
		cfg: Config{
			ChannelID:  cfg.ChannelID,
			Source:     cfg.Source,
			JoinBehind: cfg.JoinBehind,
			Remux:      Remux{Command: cfg.Command, Argv: cfg.Argv, ArgvNoBSF: cfg.Argv},
		},
		log: log,
		ring: buffer.New(buffer.Config{
			BudgetBytes: cfg.BudgetBytes,
			Retention:   cfg.Retention,
			ChunkBytes:  cfg.ChunkBytes,
			Now:         cfg.Now,
		}),
		bsf:    false,
		cancel: cancel,
		done:   make(chan struct{}),
	}
	go p.run(ctx, proc)
	return p, nil
}

// profileReader is _reader_loop (output/profile/manager.py:229-268): fd 1
// straight into the output ring, which packetises and realigns it exactly as
// StreamBuffer.add_chunk does for the channel's own input.
//
// NO SCANNER AND NO INIT SEGMENT. The remux's reader has to split MP4 boxes
// because a player needs the moov before any fragment; a transcode's output is
// MPEG-TS and the ring's own 188-byte realignment is the whole of the
// structure it has.
//
// IT RETURNS NOTHING, unlike reader, which has the 10 MB no-init-segment abort
// to report. Both of this loop's exits are ordinary: EOF on fd 1 is how every
// stopped process ends, and a closed output ring is this pipeline's own stop.
// A signature carrying an `error` it could only ever fill with nil would be a
// lie, and nilerr says so.
func (p *Pipeline) profileReader(proc *ffmpeg.Process) {
	buf := make([]byte, readSize)
	stdout := proc.Stdout()
	for {
		n, readErr := stdout.Read(buf)
		if n > 0 {
			if _, writeErr := p.ring.Write(buf[:n]); writeErr != nil {
				// buffer.ErrClosed, the only error Ring.Write returns: the
				// ring shut under us, which only this pipeline's own stop
				// does.
				break
			}
		}
		if readErr != nil {
			break
		}
	}
}
