// Package ffmpeg spawns and supervises the upstream subprocess and parses its
// stderr.
//
// Empty at 2c-1. 2c-4 brings the spawn path and the port of
// apps/proxy/live_proxy/input/log_parsers.py.
//
// TWO THINGS FIXED IN ADVANCE, so 2c-4 does not have to re-decide them.
//
// Spawning uses os/exec with SysProcAttr{Setpgid: true, Pdeathsig: SIGKILL}.
// That is D5's first named exception to strict parity: the Python relay
// spawns with os.posix_spawn and no setsid or PDEATHSIG, so an ffmpeg blocked
// on a stalled upstream survives its worker and holds a provider slot
// (CLAUDE.md, § Operationally). No test asserts the current behaviour and it
// is process hygiene rather than streaming behaviour a client can observe,
// which is why this one gets fixed in transit and the rest do not.
//
// Building the argv needs a shell word splitter this module has to write
// itself. The contract is asymmetric about this: output_profiles[*].argv
// arrives pre-split, because Django ran shlex.split on it
// (apps/proxy/next_source.py:747, core/models.py:200-203), while
// stream_profile.args arrives as the raw `parameters` text
// (apps/proxy/next_source.py:515) and still needs splitting plus the three
// {streamUrl} / {userAgent} / {channelId} substitutions
// (core/models.py:147-160). The standard library has no shlex, and the
// no-third-party-dependencies rule stands, so 2c-4 writes one with a
// differential test against Python's. Recorded in the 2c-1 plan as Finding F3.
package ffmpeg
