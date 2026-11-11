package procstat

import (
	"sort"
	"sync"
)

// Kind names what a tracked process group is for. The values are the closed
// set the spec's `kind` label takes (D7).
const (
	KindSource = "source" // a Stream Profile's process
	KindOutput = "output" // an Output Profile transcode
	KindFMP4   = "fmp4"   // the fMP4 remux
	KindHLS    = "hls"    // the HLS pipeline
)

// Labels identify a tracked group in the metrics. ChannelID is the channel's
// numeric id (0 when unknown); ProfileID is the Output Profile id, 0 when the
// group has none.
type Labels struct {
	ChannelID int
	Kind      string
	ProfileID int
}

// Proc is one process as /proc/<pid>/stat reports it.
type Proc struct {
	PID      int
	PGrp     int
	Start    uint64 // field 22: clock ticks after boot; with PID it is the identity
	CPUTicks uint64 // fields 14 + 15: utime + stime
	RSSPages int64  // field 24
}

// Source supplies one snapshot of every process on the host.
type Source interface {
	Snapshot() ([]Proc, error)
	// TicksPerSecond is AT_CLKTCK.
	TicksPerSecond() float64
	// PageSize is the size of one RSS page in bytes.
	PageSize() int
}

// Sample is one label set's reading.
type Sample struct {
	Labels Labels
	// CPUSeconds is the accumulated CPU of every identity ever seen in a
	// group with these labels. It never decreases within a Registry.
	CPUSeconds float64
	// RSSBytes is the resident memory of the live members of the groups
	// currently tracked under these labels.
	RSSBytes int64
	// Live reports whether a group with these labels is still tracked.
	Live bool
}

// Group is a registered process group.
type Group struct {
	PGID   int
	Labels Labels
}

type identity struct {
	pid   int
	start uint64
}

// Registry tracks process groups and accumulates their CPU. It is safe for
// concurrent use. The accumulators belong to the Registry, not to the
// package, so a new Registry is a new counter epoch.
type Registry struct {
	src Source

	mu     sync.Mutex
	nextID int
	groups map[int]*tracked // by registration id
	acc    map[Labels]float64
	seen   map[identity]seenInfo // the last observation of each identity
}

type seenInfo struct {
	ticks uint64
	pgid  int
}

type tracked struct {
	pgid   int
	labels Labels
}

// NewRegistry returns an empty Registry reading from src.
func NewRegistry(src Source) *Registry {
	return &Registry{
		src:    src,
		groups: map[int]*tracked{},
		acc:    map[Labels]float64{},
		seen:   map[identity]seenInfo{},
	}
}

// Default is the registry the relay's spawn path registers with.
var Default = NewRegistry(SystemSource())

// Track registers the process group pgid under l and returns the function
// that unregisters it. Calling untrack twice is harmless. The accumulated CPU
// of l stays and keeps being reported after untrack.
func (r *Registry) Track(pgid int, l Labels) (untrack func()) {
	r.mu.Lock()
	r.nextID++
	id := r.nextID
	r.groups[id] = &tracked{pgid: pgid, labels: l}
	if _, ok := r.acc[l]; !ok {
		r.acc[l] = 0
	}
	r.mu.Unlock()
	return func() {
		r.mu.Lock()
		delete(r.groups, id)
		r.mu.Unlock()
	}
}

// Groups lists the groups currently registered, ordered by group id.
func (r *Registry) Groups() []Group {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]Group, 0, len(r.groups))
	for _, g := range r.groups {
		out = append(out, Group{PGID: g.pgid, Labels: g.labels})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].PGID < out[j].PGID })
	return out
}

// Collect reads the host once and returns one Sample per label set that has
// ever been tracked. With nothing tracked it reads nothing.
func (r *Registry) Collect() []Sample {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.acc) == 0 {
		return nil
	}

	byGroup := map[int][]Labels{}
	for _, g := range r.groups {
		byGroup[g.pgid] = append(byGroup[g.pgid], g.labels)
	}

	rss := map[Labels]int64{}
	live := map[Labels]bool{}
	for _, g := range r.groups {
		live[g.labels] = true
	}

	if len(byGroup) > 0 {
		procs, err := r.src.Snapshot()
		if err == nil {
			ticks := r.src.TicksPerSecond()
			page := int64(r.src.PageSize())
			for _, p := range procs {
				owners, ok := byGroup[p.PGrp]
				if !ok {
					continue
				}
				id := identity{p.PID, p.Start}
				// A new identity starts from zero: its CPU since it was
				// spawned is counted once, and a process that began before it
				// was tracked loses nothing.
				prev := r.seen[id].ticks
				delta := p.CPUTicks - prev
				if p.CPUTicks < prev {
					delta = 0
				}
				r.seen[id] = seenInfo{ticks: p.CPUTicks, pgid: p.PGrp}
				// A group registered twice under different labels would
				// double count; the spawn path registers a group once.
				for _, l := range owners {
					r.acc[l] += float64(delta) / ticks
					rss[l] += p.RSSPages * page
				}
			}
		}
	}
	// Identities missing from a snapshot stay while their group is tracked:
	// forgetting one that was only unreadable for a moment would count its CPU
	// twice. They go with the group.
	for id, info := range r.seen {
		if _, ok := byGroup[info.pgid]; !ok {
			delete(r.seen, id)
		}
	}

	out := make([]Sample, 0, len(r.acc))
	for l, cpu := range r.acc {
		out = append(out, Sample{Labels: l, CPUSeconds: cpu, RSSBytes: rss[l], Live: live[l]})
	}
	sort.Slice(out, func(i, j int) bool {
		a, b := out[i].Labels, out[j].Labels
		if a.ChannelID != b.ChannelID {
			return a.ChannelID < b.ChannelID
		}
		if a.Kind != b.Kind {
			return a.Kind < b.Kind
		}
		return a.ProfileID < b.ProfileID
	})
	return out
}
