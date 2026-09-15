package channel

import (
	"context"
	"sync"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/output"
)

// OutputProfile is one is_active OutputProfile as the control plane described
// it: core/models.py:200-203's build_command() in full, COMMAND FIRST.
//
// A plain struct rather than the wire type, for Tuning's reason: this package
// never imports the wire package, so httpapi converts once per answer.
type OutputProfile struct {
	// ID is the OutputProfile primary key, which is what the authorize hop
	// puts in X-Relay-Output and what the client registry renders as
	// output_profile_id.
	ID int

	// Argv is [command, arg...]. NIL MEANS DJANGO COULD NOT BUILD IT --
	// shlex refused the profile's parameters -- which is a different fault
	// from the profile being absent, and the two get different answers (the
	// 2c-7 plan's Ruling R4).
	Argv []string
}

// Command is the executable to spawn: argv[0], or the empty string when
// Django could not build the list. NIL-SAFE ON PURPOSE -- an unbuildable
// profile reaches AttachOutput with a nil Argv, and indexing it there would
// turn a control-plane data problem into a panic in the channel package.
func (p OutputProfile) Command() string {
	if len(p.Argv) == 0 {
		return ""
	}
	return p.Argv[0]
}

// Args is everything after the command, the way ffmpeg.StartPiped takes it.
func (p OutputProfile) Args() []string {
	if len(p.Argv) < 2 {
		return []string{}
	}
	return p.Argv[1:]
}

// OutputProfiles is a next-source answer's whole active set.
type OutputProfiles struct {
	// Known reports whether the answer carried output_profiles at all. False
	// means a control plane older than Phase 2 PR 2b-2, which is a contract
	// mismatch rather than "no profiles are configured" -- an empty ByID with
	// Known true is the latter.
	Known bool

	// ByID is keyed by the STRINGIFIED id, as the map arrives and as
	// X-Relay-Output spells it.
	ByID map[string]OutputProfile
}

// Lookup returns the profile with this id, and whether the set holds one.
func (p OutputProfiles) Lookup(id string) (OutputProfile, bool) {
	profile, found := p.ByID[id]
	return profile, found
}

// OutputSpec is what varies between the output pipelines one channel can run.
// Everything else -- the join window, the retention, the byte budget, the
// logger -- comes off the channel, so a caller cannot give two pipelines on
// the same channel two different memory profiles by accident.
type OutputSpec struct {
	// Source is the ring the process reads on fd 0. Nil means the channel's
	// own ring. An Output Profile transcode always reads the channel's; an
	// fMP4 remux reads the channel's when no profile is active and the
	// PROFILE'S when one is -- views.py:773-776 resolves get_buffer(profile)
	// first and hands it to ensure_output_format at :790-792.
	Source *buffer.Ring

	// Profile, when non-nil, makes this an Output Profile transcode: its own
	// command line, a buffer.Ring of MPEG-TS as the sink, and no
	// bitstream-filter retry. Nil makes it the fMP4 remux.
	Profile *OutputProfile

	// Remux is the process an fMP4 pipeline spawns. Ignored when Profile is
	// set -- an Output Profile's command comes off the wire and must never
	// fall back to the remux literal (the 2c-7 plan's Ruling R3).
	Remux output.Remux
}

// outputEntry is one running output pipeline and how many clients hold it.
type outputEntry struct {
	pipeline *output.Pipeline
	refs     int
}

// AttachOutput returns the channel's output pipeline for `format`, starting it
// if nothing holds one yet, and registers this caller against it. The returned
// release function must be called exactly once, and a deferred call is the only
// correct shape.
//
// THE PORT OF THREE PYTHON MECHANISMS, COLLAPSED INTO A REFCOUNT.
// ensure_output_format (server.py:1294-1366) decides whether a manager already
// runs -- locally, or on another worker, or as stale state from a dead one --
// and the disconnect sweep (server.py:1206-1214) decides whether one should
// stop, by reading every remaining client's output_format out of Redis and
// stopping any manager whose key is no longer among them. With one process and
// one registry, "which formats do the remaining clients want" is the refcount,
// and the three-way staleness question does not arise: there is no other worker
// to have started a manager, and no key that can outlive the process that wrote
// it (spec D2's key-family table deletes output_owner and output_state by
// name).
//
// THE PIPELINE STOPS AT ZERO IMMEDIATELY, WITH NO SHUTDOWN DELAY, and that is
// parity rather than an omission. Python's sweep runs at server.py:1211-1214,
// BEFORE the `if total == 0` branch at :1221 that honours
// channel_shutdown_delay -- so an fMP4 client leaving a channel a TS client is
// still watching stops the remux at once, while the CHANNEL itself lingers for
// the delay. Both halves are reproduced: this is the sweep, and
// Manager.release is the delay.
//
// LOCK ORDER. outMu is its own mutex and never nests with c.mu: nothing under
// it reads the client registry or the state, and nothing that holds c.mu
// reaches in here. Starting a pipeline spawns a process, which is milliseconds
// of LookPath and fork/exec -- short, but not something the status endpoints'
// State() and Clients() should ever queue behind.
func (c *Channel) AttachOutput(format string, spec OutputSpec) (*output.Pipeline, func(), error) {
	c.outMu.Lock()
	defer c.outMu.Unlock()

	if entry, running := c.outputs[format]; running {
		entry.refs++
		return entry.pipeline, func() { c.releaseOutput(format) }, nil
	}

	// context.Background(), NOT the attaching client's request context and not
	// the channel's own: one ffmpeg per (channel, format) is shared by every
	// client on that format (spec's 2c-6 row), so the first client's
	// disconnect must not cancel the remux the second is reading -- the same
	// hazard Amendment A3.6 records for the tune's control-plane call, in the
	// same shape. What ends this pipeline is its refcount reaching zero or
	// stopOutputs, both below, and both are reached on every path a channel or
	// a client can end.
	source := spec.Source
	if source == nil {
		source = c.ring
	}
	var (
		pipeline *output.Pipeline
		err      error
	)
	if spec.Profile != nil {
		// 2c-7. The transcode's sink is a second buffer.Ring of MPEG-TS, its
		// command line comes off the wire, and it has no bitstream-filter
		// retry to make -- OutputProfileManager._stderr_loop
		// (output/profile/manager.py:270-295) logs and does nothing else.
		pipeline, err = output.StartProfile(context.Background(), output.ProfileConfig{
			ChannelID:   c.id,
			ProfileID:   spec.Profile.ID,
			Source:      source,
			Command:     spec.Profile.Command(),
			Argv:        spec.Profile.Args(),
			JoinBehind:  c.tuning.JoinBehind,
			Retention:   c.tuning.Retention,
			ChunkBytes:  c.tuning.ChunkBytes,
			BudgetBytes: c.budgetBytes,
			Log:         c.log,
			Now:         c.now,
		})
	} else {
		pipeline, err = output.Start(context.Background(), output.Config{
			ChannelID:   c.id,
			Source:      source,
			JoinBehind:  c.tuning.JoinBehind,
			Retention:   c.tuning.Retention,
			BudgetBytes: c.budgetBytes,
			Remux:       spec.Remux,
			Log:         c.log,
		})
	}
	if err != nil {
		return nil, nil, err
	}
	c.outputs[format] = &outputEntry{pipeline: pipeline, refs: 1}
	return pipeline, func() { c.releaseOutput(format) }, nil
}

// releaseOutput drops one reference and stops the pipeline at zero.
//
// Stop is called OUTSIDE outMu, for Manager.release's reason: it waits on the
// process, and holding the registry lock across that would make one slow remux
// teardown block every other format's attach on this channel.
func (c *Channel) releaseOutput(format string) {
	var stopping *output.Pipeline
	c.outMu.Lock()
	if entry, running := c.outputs[format]; running {
		entry.refs--
		if entry.refs <= 0 {
			delete(c.outputs, format)
			stopping = entry.pipeline
		}
	}
	c.outMu.Unlock()
	if stopping != nil {
		c.log.Info("no clients remain for the output format, stopping it", "channel", c.id, "format", format)
		stopping.Stop()
	}
}

// stopOutputs tears down every pipeline this channel holds, whatever their
// refcounts: stop_all_output_formats (server.py:1397-1400), called from
// stop_channel's local cleanup at :1771 and from nowhere else.
//
// CALLED FROM run's DEFERRED CALLS, which is the one place a channel ends, so
// there is exactly one mechanism and no second path that could silently cover
// for its removal. A client still attached to a stopped channel finds its
// fragment buffer closed, which is how its read loop ends.
func (c *Channel) stopOutputs() {
	c.outMu.Lock()
	entries := make([]*outputEntry, 0, len(c.outputs))
	for format, entry := range c.outputs {
		entries = append(entries, entry)
		delete(c.outputs, format)
	}
	c.outMu.Unlock()
	for _, entry := range entries {
		entry.pipeline.Stop()
	}
}

// outputRegistry is the state AttachOutput needs, embedded in Channel so the
// struct's own definition stays about the input side.
type outputRegistry struct {
	outMu   sync.Mutex
	outputs map[string]*outputEntry
}

// OutputFormats is every format this channel currently runs a pipeline for, for
// tests and logs.
func (c *Channel) OutputFormats() []string {
	c.outMu.Lock()
	defer c.outMu.Unlock()
	out := make([]string, 0, len(c.outputs))
	for format := range c.outputs {
		out = append(out, format)
	}
	return out
}
