package channel

import (
	"context"
	"sync"

	"github.com/D10Scot/Dispatcharr/relay/output"
)

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
func (c *Channel) AttachOutput(format string, remux output.Remux) (*output.Pipeline, func(), error) {
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
	pipeline, err := output.Start(context.Background(), output.Config{
		ChannelID:   c.id,
		Source:      c.ring,
		JoinBehind:  c.tuning.JoinBehind,
		Retention:   c.tuning.Retention,
		BudgetBytes: c.budgetBytes,
		Remux:       remux,
		Log:         c.log,
	})
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
