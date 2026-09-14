// Package ffmpeg spawns and supervises the upstream subprocess and parses its
// stderr: the FFmpeg, VLC and Streamlink stream-profile architectures' half
// of the relay that is not the ring.
//
// Three files, one concern each. spawn.go is the process -- os/exec with
// SysProcAttr{Setpgid: true} and, on Linux, Pdeathsig: SIGKILL, which is spec
// D5's first named exception to strict parity: the Python relay spawns with
// os.posix_spawn and no setsid or PDEATHSIG, so an ffmpeg blocked on a stalled
// upstream survives its worker and holds a provider slot (CLAUDE.md,
// § Operationally). Python chose posix_spawn because fork() hangs in gevent's
// _before_fork handler, a reason that does not exist in Go and is not
// cargo-culted; what is reproduced is the OBSERVABLE contract, fd for fd
// (input/manager.py:823-923): stdin /dev/null, stdout the video, stderr
// parsed line by line on CR or LF, SIGKILL and nothing gentler on stop, the
// exit status as Python's returncode. parse.go is the port of
// apps/proxy/live_proxy/services/log_parsers.py -- the FFmpeg, VLC and
// Streamlink parsers, their factory and its order -- and progress.go the
// port of _parse_ffmpeg_stats' three regexes, scientific-notation defect
// included (parity-matrix row 28). detector.go is the buffering state
// machine of input/manager.py:1165-1247 with an injected clock; what a
// timeout MEANS is the source's decision (channel.TranscodeSource), because
// Python fails over there and 2c-5 owns that.
//
// WHAT THIS PACKAGE DELIBERATELY DOES NOT CONTAIN, correcting 2c-1's stub
// comment: no shell word splitter and no {streamUrl}/{userAgent}/
// {channelId} substitution. 2c-1 recorded (its Finding F3) that
// stream_profile.args arrives as raw `parameters` text and that 2c-4 would
// write a shlex with a differential test against Python's. It does not.
// Spec Amendment A4.1: Django builds each source's argv with
// StreamProfile.build_command and sends it as stream_profile.argv, so the
// argv this package spawns is byte for byte the argv the Python relay spawns
// from the same answer, and there is nothing here to keep in step with
// core/models.py:137-160.
package ffmpeg
