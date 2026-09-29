package hls

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// StoreSegments and StoreBytes bound an hls.Store: 21 segments per rendition
// (ruling R44), and a byte ceiling above that which only a runaway would
// reach. LiveEdge is how many of them a media playlist lists (D7).
//
// THE ARITHMETIC IS RFC 8216 § 6.2.2's: a segment removed from the playlist
// must stay available for its own duration plus the playlist's. At a target
// duration of 2 s the live edge lists 10 segments, 20 s, so a removed segment
// must stay fetchable for 2 s + 20 s, which is 11 publications after it
// leaves the list -- the store keeps 10 + 11 = 21. About 46 MB per channel at
// D8's top rate with AAC and AC-3, under StoreBytes' 64 MiB.
const (
	StoreSegments = 21
	StoreBytes    = 64 << 20
	LiveEdge      = 10
	// TargetDuration is transcode mode's EXT-X-TARGETDURATION, in seconds,
	// and the default of a store nothing has called SetTargetDuration on.
	// An automatic run's is its pipeline's own (Store.SetTargetDuration).
	TargetDuration = 2
)

// ErrStoreClosed is a wait on a store whose pipeline has ended.
var ErrStoreClosed = errors.New("hls: the pipeline has ended")

// part is one rendition's piece of one segment.
type part struct {
	data []byte
	// duration is the EXTINF value, in seconds.
	duration float64
}

// segment is one media sequence number across every rendition. All
// renditions share it: an audio segment holds the audio whose start falls in
// its video segment's span (spec § Playlists).
type segment struct {
	seq           uint64
	gen           int
	discontinuity bool
	pdt           time.Time
	published     time.Time
	parts         map[string]part
	// bytes is the total size of every rendition's part, whether or not the
	// data is still held in memory.
	bytes int
	// held is whether the parts' data is in memory. A segment that has left the
	// newest StoreSegments and is on disk gives its data up (4a-3).
	held bool
	// onDisk, pending and doomed are the rewind window's bookkeeping (4a-3):
	// written, queued and not yet written, and evicted while a read was in
	// flight (its files are unlinked when the last reader leaves). readers is
	// how many reads of its files are in flight. retiredAt is when it left
	// the playlist, for the unlink retention.
	onDisk, pending, doomed bool
	readers                 int
	retiredAt               time.Time
}

type initKey struct {
	rendition string
	gen       int
}

// Store is one HLS pipeline's segments: per rendition, keyed by media
// sequence, with each generation's init segments and discontinuity markers
// (spec § State). Everything a 4a-1b handler serves comes from it, and it
// renders every playlist (D7).
type Store struct {
	mu      sync.Mutex
	changed chan struct{}
	segs    []*segment
	bytes   int
	nextSeq uint64
	// discontinuitiesGone counts discontinuity-carrying segments that have
	// left the store, for EXT-X-DISCONTINUITY-SEQUENCE.
	discontinuitiesGone uint64
	lastGen             int
	published           bool
	inits               map[initKey][]byte
	closed              bool
	now                 func() time.Time
	// target is the pipeline's target duration in seconds, 0 meaning the
	// default (TargetDuration). SetTargetDuration sets it once, before any
	// publish.
	target int

	// The rewind window's half (4a-3). window is nil when the window is off,
	// and then every field below is idle. retired holds the segments that left
	// the playlist and are still fetchable, oldest first. version moves with
	// every change a playlist or a read would notice, and cache is the
	// rendered playlists it validates.
	window  *window
	retired []*segment
	version uint64
	cache   map[string]rendered
	renders int
	// beforeDiskRead runs between a read's pin and its file read, with no lock
	// held; tests use it to hold a read in flight.
	beforeDiskRead func()
}

type rendered struct {
	version  uint64
	body     []byte
	modified time.Time
}

// ErrNoWindow, ErrWindowDegraded and ErrSegmentGone are WaitDurable's answers.
var (
	ErrNoWindow       = errors.New("hls: the store has no rewind window")
	ErrWindowDegraded = errors.New("hls: the rewind window stopped persisting")
	ErrSegmentGone    = errors.New("hls: the segment has left the store")
)

// NewStore is an empty store. now is the clock for Last-Modified (nil means
// time.Now).
func NewStore(now func() time.Time) *Store {
	if now == nil {
		now = time.Now
	}
	return &Store{changed: make(chan struct{}), inits: map[initKey][]byte{}, now: now, cache: map[string]rendered{}}
}

// notifyLocked wakes every waiter and invalidates every rendered playlist: it
// is called by every path that changes what a playlist or a read would answer.
func (s *Store) notifyLocked() {
	s.version++
	close(s.changed)
	s.changed = make(chan struct{})
}

// SetTargetDuration fixes the store's target duration in seconds (4a-1d): the
// value its media playlists carry as EXT-X-TARGETDURATION, and the scale of
// the byte ceiling, which is StoreBytes at TargetDuration and grows with it,
// because a copied segment at a target of 6 is three times the bytes of one at
// 2. It is called once, when the run's output is decided, before any publish.
// A store it was never called on behaves exactly as it always has.
func (s *Store) SetTargetDuration(target int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.target = target
	s.notifyLocked()
}

// targetLocked is the target duration in force.
func (s *Store) targetLocked() int {
	if s.target > 0 {
		return s.target
	}
	return TargetDuration
}

// byteLimitLocked is the byte ceiling: StoreBytes scaled by target over the
// default target. It stays the runaway guard the segment count is not: at 2 s
// the 21 segments fit far below it, and at 6 s they fit up to about 12 Mb/s.
func (s *Store) byteLimitLocked() int {
	return StoreBytes * s.targetLocked() / TargetDuration
}

// SetInit records a generation's init segment for a rendition.
func (s *Store) SetInit(rendition string, gen int, data []byte) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.inits[initKey{rendition, gen}] = data
	s.notifyLocked()
}

// Init is a generation's init segment for a rendition.
func (s *Store) Init(rendition string, gen int) ([]byte, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	data, ok := s.inits[initKey{rendition, gen}]
	return data, ok
}

// unlistedRetentionLocked is how long a segment that left the playlist by
// depth stays fetchable before the writer unlinks it: RFC 8216 § 6.2.2's
// availability at the live edge's arithmetic (R44, R83), StoreSegments minus
// LiveEdge target durations, 22 s at a target of 2.
func (s *Store) unlistedRetentionLocked() time.Duration {
	return time.Duration(StoreSegments-LiveEdge) * time.Duration(s.targetLocked()) * time.Second
}

// publish appends one segment across every rendition. The first segment of
// a generation other than the previous segment's carries a discontinuity
// (D10), so the media sequence continues across generations and a player is
// told where a new EXT-X-MAP and timeline begin.
//
// With a rewind window the segment is only queued for the disk writer and a
// non-blocking wake-up sent: publish runs on the segmenter's goroutine under
// s.mu and does no disk I/O (4a-3, Global constraint 2).
func (s *Store) publish(gen int, pdt time.Time, parts map[string]part) uint64 {
	s.mu.Lock()
	seg := &segment{
		seq:           s.nextSeq,
		gen:           gen,
		discontinuity: s.published && gen != s.lastGen,
		pdt:           pdt,
		published:     s.now(),
		parts:         parts,
		held:          true,
	}
	for _, p := range parts {
		seg.bytes += len(p.data)
	}
	s.nextSeq++
	s.lastGen, s.published = gen, true
	s.segs = append(s.segs, seg)
	s.bytes += seg.bytes
	var degraded *degradation
	if w := s.window; w != nil && !w.degraded {
		if w.pending >= StoreSegments {
			degraded = s.degradeLocked(w, nil, "the writer queue is full")
		} else {
			seg.pending = true
			w.pending++
			w.queue = append(w.queue, seg)
			w.r.wake()
		}
	}
	s.trimLocked()
	s.evictInitsLocked()
	s.notifyLocked()
	s.mu.Unlock()
	degraded.warn()
	return seg.seq
}

// durable is whether a segment is on disk or queued for it.
func durable(seg *segment) bool { return seg.onDisk || seg.pending }

// releaseLocked drops a segment's data from memory, keeping each part's
// duration for the playlists.
func (s *Store) releaseLocked(seg *segment) {
	if !seg.held {
		return
	}
	for name, p := range seg.parts {
		seg.parts[name] = part{duration: p.duration}
	}
	seg.held = false
	s.bytes -= seg.bytes
}

// retireHeadLocked takes the oldest segment out of the playlist. One that is on
// disk or queued becomes retired, fetchable until the writer unlinks it; any
// other is gone, as it was before 4a-3.
func (s *Store) retireHeadLocked() {
	gone := s.segs[0]
	s.segs[0] = nil
	s.segs = s.segs[1:]
	if gone.discontinuity {
		s.discontinuitiesGone++
	}
	if s.window != nil && durable(gone) {
		gone.retiredAt = s.now()
		s.retired = append(s.retired, gone)
		if !gone.pending {
			s.releaseLocked(gone)
		}
		return
	}
	s.releaseLocked(gone)
}

// heldLocked is how many listed segments hold their data in memory.
func (s *Store) heldLocked() int {
	n := 0
	for _, seg := range s.segs {
		if seg.held {
			n++
		}
	}
	return n
}

// trimLocked is the store's one eviction rule (4a-3), run after every publish
// and every written segment:
//
//  1. depth: with a window, the head leaves the playlist while it is outside the
//     newest StoreSegments and more than the window's depth older than the
//     newest by PDT;
//  2. memory: below the newest StoreSegments a segment on disk gives its data up
//     and a queued one keeps it until written, while one that is neither can
//     never be listed again and leaves, with everything older;
//  3. the byte ceiling: an on-disk segment gives its data up, else the head
//     leaves, unless it is still queued for the disk (its bytes are not freed
//     by leaving, and the writer will free them).
//
// With no window rule 1 never applies and 2 and 3 are the eviction loop this
// replaced.
func (s *Store) trimLocked() {
	if w := s.window; w != nil {
		for len(s.segs) > StoreSegments && s.segs[len(s.segs)-1].pdt.Sub(s.segs[0].pdt) > w.depth {
			s.retireHeadLocked()
		}
	}
	if edge := len(s.segs) - StoreSegments; edge > 0 {
		for i := edge - 1; i >= 0; i-- {
			if !durable(s.segs[i]) {
				for j := 0; j <= i; j++ {
					s.retireHeadLocked()
				}
				break
			}
		}
		for i, edge := 0, len(s.segs)-StoreSegments; i < edge; i++ {
			if seg := s.segs[i]; seg.onDisk {
				s.releaseLocked(seg)
			}
		}
	}
	for s.bytes > s.byteLimitLocked() && s.heldLocked() > 1 {
		var oldest *segment
		for _, seg := range s.segs {
			if seg.onDisk && seg.held {
				oldest = seg
				break
			}
		}
		if oldest != nil {
			s.releaseLocked(oldest)
			continue
		}
		if s.segs[0].pending {
			// Queued segments are the newest, and their bytes leave memory
			// when the writer has written them: retiring one would free
			// none, and lose it from the playlist for nothing.
			break
		}
		s.retireHeadLocked()
	}
}

// evictInitsLocked drops the init segments of generations no stored or retired
// segment refers to, except the newest generation's, which the next segment
// will.
func (s *Store) evictInitsLocked() {
	live := map[int]bool{s.lastGen: true}
	for _, seg := range s.segs {
		live[seg.gen] = true
	}
	for _, seg := range s.retired {
		live[seg.gen] = true
	}
	for key := range s.inits {
		if !live[key.gen] && key.gen < s.lastGen {
			delete(s.inits, key)
		}
	}
}

// Close marks the store ended and wakes every waiter. A window is closed with
// it: the writer removes its directory once no read is in flight.
func (s *Store) Close() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.closed {
		s.closed = true
		if w := s.window; w != nil {
			w.closed = true
			w.r.wake()
		}
		s.notifyLocked()
	}
}

// findLocked is the listed or retired segment at seq. Listed sequence numbers
// are contiguous, so that lookup is arithmetic.
func (s *Store) findLocked(seq uint64) *segment {
	if n := len(s.segs); n > 0 && seq >= s.segs[0].seq && seq <= s.segs[n-1].seq {
		return s.segs[seq-s.segs[0].seq]
	}
	for _, seg := range s.retired {
		if seg.seq == seq {
			return seg
		}
	}
	return nil
}

// Segment is one rendition's segment at seq, and false when seq is outside
// the store (a 404, spec § Session resources).
func (s *Store) Segment(rendition string, seq uint64) ([]byte, bool) {
	data, _, ok := s.SegmentAt(rendition, seq)
	return data, ok
}

// SegmentAt is Segment with how far behind the newest segment the one served
// is, by PDT (4a-3: the handler records it on the session, which decides
// behind live from it). A segment held in memory answers from it; one only on
// disk is read from there, pinned so that nothing unlinks it under the read.
func (s *Store) SegmentAt(rendition string, seq uint64) ([]byte, time.Duration, bool) {
	s.mu.Lock()
	seg := s.findLocked(seq)
	if seg == nil {
		s.mu.Unlock()
		return nil, 0, false
	}
	p, ok := seg.parts[rendition]
	if !ok {
		s.mu.Unlock()
		return nil, 0, false
	}
	var behind time.Duration
	if n := len(s.segs); n > 0 {
		behind = s.segs[n-1].pdt.Sub(seg.pdt)
	}
	if seg.held {
		s.mu.Unlock()
		return p.data, behind, true
	}
	w := s.window
	if w == nil || !seg.onDisk || w.closed || w.removing {
		s.mu.Unlock()
		return nil, 0, false
	}
	seg.readers++
	w.pins++
	path := w.segPath(seg.gen, rendition, seq)
	hook := s.beforeDiskRead
	s.mu.Unlock()
	if hook != nil {
		hook()
	}
	data, err := w.r.fs.ReadFile(path)
	s.mu.Lock()
	s.unpinLocked(w, seg)
	s.mu.Unlock()
	if err != nil {
		w.r.log.Debug("could not read a rewind segment", "channel", w.channel, "sequence", seq, "error", redact.Error(err))
		return nil, 0, false
	}
	return data, behind, true
}

// unpinLocked ends one read of a segment's file. The last read of a doomed
// segment queues its unlink, and the last read under a closed window wakes the
// writer to remove the window's directory.
func (s *Store) unpinLocked(w *window, seg *segment) {
	seg.readers--
	w.pins--
	switch {
	case seg.doomed && seg.readers == 0:
		w.unlinks = append(w.unlinks, w.segPaths(seg)...)
		w.r.wake()
	case w.closed && w.pins == 0:
		w.r.wake()
	}
}

// WaitSegment blocks until the store holds at least one segment, the context
// ends, or the pipeline does (D7: a media playlist request waits for its
// rendition's first segment; 4a-1b bounds the wait at 20 s).
func (s *Store) WaitSegment(ctx context.Context) error {
	for {
		s.mu.Lock()
		have, closed, ch := len(s.segs) > 0, s.closed, s.changed
		s.mu.Unlock()
		switch {
		case have:
			return nil
		case closed:
			return ErrStoreClosed
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ch:
		}
	}
}

// WaitDurable blocks until segment seq is on disk. It answers an error at once
// when the store has no window, the window is degraded or closed, or seq has
// left the store; a seq not yet published is waited for. For tests.
func (s *Store) WaitDurable(ctx context.Context, seq uint64) error {
	for {
		s.mu.Lock()
		w := s.window
		var err error
		switch {
		case w == nil:
			err = ErrNoWindow
		case w.degraded:
			err = ErrWindowDegraded
		case w.closed:
			err = ErrStoreClosed
		default:
			if seg := s.findLocked(seq); seg != nil {
				if seg.onDisk {
					s.mu.Unlock()
					return nil
				}
			} else if seq < s.nextSeq {
				err = ErrSegmentGone
			}
		}
		ch := s.changed
		s.mu.Unlock()
		if err != nil {
			return err
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ch:
		}
	}
}

// WaitDegraded blocks until the window is degraded. For tests.
func (s *Store) WaitDegraded(ctx context.Context) error {
	for {
		s.mu.Lock()
		w, ch := s.window, s.changed
		degraded := w != nil && w.degraded
		s.mu.Unlock()
		if degraded {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ch:
		}
	}
}

// SetLingering tells the store its window's channel is lingering, which the
// disk cap's eviction order prefers to evict from (spec D14). A no-op without
// a window.
func (s *Store) SetLingering(on bool) {
	s.mu.Lock()
	w := s.window
	s.mu.Unlock()
	if w != nil {
		w.lingering.Store(on)
	}
}

// WindowStatus is what the channel payload reports of a rewind window.
type WindowStatus struct {
	// Enabled is whether the store has a window at all.
	Enabled bool
	// Seconds is the summed duration of the listed video segments: the window's
	// span, or the live edge's when there is no window.
	Seconds float64
	// Degraded is whether the window stopped persisting.
	Degraded bool
}

// WindowStatus reports the listed span, which is the whole window when the store
// has one and the live edge when it has not, and whether the window degraded.
func (s *Store) WindowStatus() WindowStatus {
	s.mu.Lock()
	defer s.mu.Unlock()
	st := WindowStatus{}
	if w := s.window; w != nil {
		st.Enabled, st.Degraded = true, w.degraded
	}
	for _, seg := range s.segs[s.renderFromLocked():] {
		st.Seconds += seg.parts[RenditionVideo].duration
	}
	return st
}

// renderFromLocked is the index of the first listed segment: the smallest from
// which every segment is durable or among the newest LiveEdge. RFC 8216
// § 6.2.2 forbids listing a segment the store will not keep for a playlist's
// length, so what only memory holds is listed only while it is at the live
// edge. With no window that is the seed's live edge exactly, and with a healthy
// one it is 0.
func (s *Store) renderFromLocked() int {
	n := len(s.segs)
	k := n
	for i := n - 1; i >= 0; i-- {
		if !durable(s.segs[i]) && i < n-LiveEdge {
			break
		}
		k = i
	}
	return k
}

// MediaPlaylist renders one rendition's media playlist (spec § Playlists) and
// the newest segment's publish time, which is the response's Last-Modified
// (Apple 8.24). ok is false while the store holds no segment.
//
// Without a rewind window the last LiveEdge segments are listed; with one, the
// whole window is (renderFromLocked). EXT-X-PROGRAM-DATE-TIME is on every
// segment; EXT-X-MAP opens each generation's run and carries that
// generation's init; EXT-X-DISCONTINUITY precedes the first segment of every
// generation after the first, including when that segment is the first one
// listed, so a segment's discontinuity sequence number never changes between
// reloads; EXT-X-DISCONTINUITY-SEQUENCE counts the discontinuities that have
// left the list. EXT-X-ENDLIST and EXT-X-PLAYLIST-TYPE are never written. The
// body is cached per rendition until the store next changes.
func (s *Store) MediaPlaylist(rendition string) ([]byte, time.Time, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.segs) == 0 {
		return nil, time.Time{}, false
	}
	if c, ok := s.cache[rendition]; ok && c.version == s.version {
		return c.body, c.modified, true
	}
	s.renders++
	first := s.renderFromLocked()
	listed := s.segs[first:]
	gone := s.discontinuitiesGone
	for _, seg := range s.segs[:first] {
		if seg.discontinuity {
			gone++
		}
	}
	var b strings.Builder
	b.WriteString("#EXTM3U\n#EXT-X-VERSION:7\n")
	fmt.Fprintf(&b, "#EXT-X-TARGETDURATION:%d\n", s.targetLocked())
	fmt.Fprintf(&b, "#EXT-X-MEDIA-SEQUENCE:%d\n", listed[0].seq)
	fmt.Fprintf(&b, "#EXT-X-DISCONTINUITY-SEQUENCE:%d\n", gone)
	b.WriteString("#EXT-X-INDEPENDENT-SEGMENTS\n")
	for i, seg := range listed {
		if seg.discontinuity {
			b.WriteString("#EXT-X-DISCONTINUITY\n")
		}
		if i == 0 || seg.gen != listed[i-1].gen {
			fmt.Fprintf(&b, "#EXT-X-MAP:URI=\"%s/init-%d.mp4\"\n", rendition, seg.gen)
		}
		fmt.Fprintf(&b, "#EXT-X-PROGRAM-DATE-TIME:%s\n", seg.pdt.UTC().Format("2006-01-02T15:04:05.000Z"))
		fmt.Fprintf(&b, "#EXTINF:%.3f,\n", seg.parts[rendition].duration)
		fmt.Fprintf(&b, "%s/%d.m4s\n", rendition, seg.seq)
	}
	c := rendered{version: s.version, body: []byte(b.String()), modified: listed[len(listed)-1].published}
	s.cache[rendition] = c
	return c.body, c.modified, true
}
