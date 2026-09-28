package hls

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"
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
	// TargetDuration is transcode mode's EXT-X-TARGETDURATION, in seconds.
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
	bytes         int
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
}

// NewStore is an empty store. now is the clock for Last-Modified (nil means
// time.Now).
func NewStore(now func() time.Time) *Store {
	if now == nil {
		now = time.Now
	}
	return &Store{changed: make(chan struct{}), inits: map[initKey][]byte{}, now: now}
}

func (s *Store) notifyLocked() {
	close(s.changed)
	s.changed = make(chan struct{})
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

// publish appends one segment across every rendition. The first segment of
// a generation other than the previous segment's carries a discontinuity
// (D10), so the media sequence continues across generations and a player is
// told where a new EXT-X-MAP and timeline begin.
func (s *Store) publish(gen int, pdt time.Time, parts map[string]part) uint64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	seg := &segment{
		seq:           s.nextSeq,
		gen:           gen,
		discontinuity: s.published && gen != s.lastGen,
		pdt:           pdt,
		published:     s.now(),
		parts:         parts,
	}
	for _, p := range parts {
		seg.bytes += len(p.data)
	}
	s.nextSeq++
	s.lastGen, s.published = gen, true
	s.segs = append(s.segs, seg)
	s.bytes += seg.bytes
	for len(s.segs) > StoreSegments || (s.bytes > StoreBytes && len(s.segs) > 1) {
		gone := s.segs[0]
		if gone.discontinuity {
			s.discontinuitiesGone++
		}
		s.bytes -= gone.bytes
		s.segs = s.segs[1:]
	}
	s.evictInitsLocked()
	s.notifyLocked()
	return seg.seq
}

// evictInitsLocked drops the init segments of generations no stored segment
// refers to, except the newest generation's, which the next segment will.
func (s *Store) evictInitsLocked() {
	live := map[int]bool{s.lastGen: true}
	for _, seg := range s.segs {
		live[seg.gen] = true
	}
	for key := range s.inits {
		if !live[key.gen] && key.gen < s.lastGen {
			delete(s.inits, key)
		}
	}
}

// Close marks the store ended and wakes every waiter.
func (s *Store) Close() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.closed {
		s.closed = true
		s.notifyLocked()
	}
}

// Segment is one rendition's segment at seq, and false when seq is outside
// the store (a 404, spec § Session resources).
func (s *Store) Segment(rendition string, seq uint64) ([]byte, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, seg := range s.segs {
		if seg.seq == seq {
			p, ok := seg.parts[rendition]
			return p.data, ok
		}
	}
	return nil, false
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

// MediaPlaylist renders one rendition's live-edge media playlist (spec
// § Playlists) and the newest segment's publish time, which is the response's
// Last-Modified (Apple 8.24). ok is false while the store holds no segment.
//
// The last LiveEdge segments are listed. EXT-X-PROGRAM-DATE-TIME is on every
// segment; EXT-X-MAP opens each generation's run and carries that
// generation's init; EXT-X-DISCONTINUITY precedes the first segment of every
// generation after the first, including when that segment is the first one
// listed, so a segment's discontinuity sequence number never changes between
// reloads; EXT-X-DISCONTINUITY-SEQUENCE counts the discontinuities that have
// left the list. EXT-X-ENDLIST is never written.
func (s *Store) MediaPlaylist(rendition string) ([]byte, time.Time, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.segs) == 0 {
		return nil, time.Time{}, false
	}
	first := max(0, len(s.segs)-LiveEdge)
	listed := s.segs[first:]
	gone := s.discontinuitiesGone
	for _, seg := range s.segs[:first] {
		if seg.discontinuity {
			gone++
		}
	}
	var b strings.Builder
	b.WriteString("#EXTM3U\n#EXT-X-VERSION:7\n")
	fmt.Fprintf(&b, "#EXT-X-TARGETDURATION:%d\n", TargetDuration)
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
	return []byte(b.String()), listed[len(listed)-1].published, true
}
