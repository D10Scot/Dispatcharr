package hls

import (
	"sync"
	"time"
)

// track is one encoder output of one generation, as its reader fills it.
type track struct {
	name     string
	info     Track
	haveInit bool
	// frags is the queue of fragments read but not yet in a segment, tfdt
	// already on the generation's shared timeline.
	frags []Fragment
	// maxStart is the latest fragment start ever read, so "has this track
	// reached time t" survives the queue being consumed.
	maxStart uint64
	seen     bool
	eof      bool
	// read counts every fragment ever read.
	read int
}

// videoSegment is a cut but unpublished video segment: [start, end) in video
// ticks, the fragments that make it, and when it was cut.
type videoSegment struct {
	frags      []Fragment
	start, end uint64
	cut        time.Time
}

// AudioWait bounds how long a cut video segment waits for an audio rendition
// that has not yet read past its end: two target durations. The audio
// outputs normally run ahead of the video (200 ms fragments against 2 s
// ones), so the wait is only ever reached by an audio output that stopped,
// and the video must not stall behind it. It is wall-clock time, deliberately
// not a count of video segments: when a generation catches up its JoinBehind
// backlog faster than real time, the video reader can be several segments
// ahead of an audio reader that simply has not been scheduled yet.
const AudioWait = 2 * TargetDuration * time.Second

// segmenter cuts one generation's outputs into segments and publishes them
// (spec D6). The video fragments are accumulated until the 2 s grid is
// reached, and a segment is only ever cut before a fragment whose first
// sample is a sync sample, so every segment starts with one (Apple 7.4) --
// which is also what makes a stray non-IDR keyframe from the encoder harmless
// (Q1). Each audio rendition's segment holds the audio fragments whose start
// falls in its video segment's span; a silent rendition's is written from its
// canned frame.
//
// Readers call init, fragment and finish from their own goroutines; run is
// the one goroutine that cuts and publishes.
type segmenter struct {
	store *Store
	gen   int
	// anchor is the ring arrival time of the generation's first chunk (D7):
	// EXT-X-PROGRAM-DATE-TIME is the anchor plus the segment's media time.
	anchorMu   sync.Mutex
	anchor     time.Time
	haveAnchor bool
	now        func() time.Time
	// audioWait is AudioWait unless a test shortened it.
	audioWait time.Duration
	// onFirst is called once, on the segmenter's goroutine and so before
	// the attempt returns, when the first segment is published. It must not
	// block.
	onFirst func()

	// The three fields below are set by the attempt after newSegmenter and
	// before run, for a generation whose video is COPIED (4a-1d): target is
	// the run's target duration in seconds, copied says the copy cut and the
	// over-long check apply, and onOverlong is called once, on the
	// segmenter's goroutine and never with the lock held, when a copied
	// segment would round above the target. It must not block.
	target     uint64
	copied     bool
	onOverlong func()

	mu      sync.Mutex
	changed chan struct{}
	video   *track
	audio   []*track
	silence map[string]*silenceClock

	// The fields below belong to run alone.
	v0        uint64
	haveV0    bool
	grid      uint64 // the index of the next 2 s grid line, from v0
	pending   []Fragment
	ready     []videoSegment
	tailDone  bool
	published int
	// overlong is set (under mu) by the first copied span that reaches
	// target + 0.5 s; overlongFire asks run to call onOverlong once.
	overlong     bool
	overlongFire bool
}

func newSegmenter(store *Store, gen int, audio []string, silence map[string]*silenceClock, now func() time.Time, audioWait time.Duration, onFirst func()) *segmenter {
	if audioWait <= 0 {
		audioWait = AudioWait
	}
	s := &segmenter{
		store:     store,
		gen:       gen,
		now:       now,
		audioWait: audioWait,
		onFirst:   onFirst,
		changed:   make(chan struct{}),
		video:     &track{name: RenditionVideo},
		silence:   silence,
	}
	for _, name := range audio {
		s.audio = append(s.audio, &track{name: name})
	}
	return s
}

func (s *segmenter) notifyLocked() {
	close(s.changed)
	s.changed = make(chan struct{})
}

func (s *segmenter) track(name string) *track {
	if name == RenditionVideo {
		return s.video
	}
	for _, t := range s.audio {
		if t.name == name {
			return t
		}
	}
	return nil
}

// setAnchor records the arrival time of the first chunk the generation was
// fed.
func (s *segmenter) setAnchor(at time.Time) {
	s.anchorMu.Lock()
	defer s.anchorMu.Unlock()
	if !s.haveAnchor {
		s.anchor, s.haveAnchor = at, true
	}
}

func (s *segmenter) pdtAnchor() time.Time {
	s.anchorMu.Lock()
	defer s.anchorMu.Unlock()
	if s.haveAnchor {
		return s.anchor
	}
	return s.now()
}

// init records a track's parsed init segment.
func (s *segmenter) init(name string, info Track) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if t := s.track(name); t != nil {
		t.info, t.haveInit = info, true
	}
	s.notifyLocked()
}

// fragment queues one fragment.
func (s *segmenter) fragment(name string, f Fragment) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if t := s.track(name); t != nil {
		t.frags = append(t.frags, f)
		t.read++
		if !t.seen || f.Start > t.maxStart {
			t.maxStart, t.seen = f.Start, true
		}
	}
	s.notifyLocked()
}

// VideoFragments is how many video fragments the encoder has written: the
// stall watchdog's measure of progress.
func (s *segmenter) VideoFragments() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.video.read
}

// Overlong reports whether the generation ended because a copied segment
// would have rounded above the target duration (RFC 8216 § 4.3.3.1).
func (s *segmenter) Overlong() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.overlong
}

// finish marks a track's output at EOF.
func (s *segmenter) finish(name string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if t := s.track(name); t != nil {
		t.eof = true
	}
	s.notifyLocked()
}

// Published is how many segments the generation has published.
func (s *segmenter) Published() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.published
}

// run cuts and publishes until every output is at EOF and everything cut
// has been published.
func (s *segmenter) run() {
	for {
		s.mu.Lock()
		s.cutLocked()
		progressed, wake := s.publishLocked()
		finished := s.video.eof && len(s.ready) == 0 && s.audioAtEOFLocked()
		ch := s.changed
		fire := s.overlongFire
		s.overlongFire = false
		s.mu.Unlock()
		if fire && s.onOverlong != nil {
			s.onOverlong()
		}
		switch {
		case finished:
			return
		case progressed:
		case wake > 0:
			timer := time.NewTimer(wake)
			select {
			case <-ch:
			case <-timer.C:
			}
			timer.Stop()
		default:
			<-ch
		}
	}
}

func (s *segmenter) audioAtEOFLocked() bool {
	for _, t := range s.audio {
		if !t.eof {
			return false
		}
	}
	return true
}

// gridTicks is one target duration in video ticks.
func (s *segmenter) gridTicks() uint64 {
	return uint64(TargetDuration) * uint64(s.video.info.Timescale)
}

// cutLocked moves queued video fragments into cut segments. A segment is
// closed before a sync fragment that starts at or after the next grid line,
// measured from the generation's first video tfdt, and the next grid line is
// then the first one after that fragment's start. At EOF the pending
// fragments become the generation's last segment, whose end is its last
// fragment's tfdt plus its sample durations -- never an assumed 2 s.
func (s *segmenter) cutLocked() {
	v := s.video
	for len(v.frags) > 0 {
		f := v.frags[0]
		v.frags = v.frags[1:]
		if s.tailDone {
			// The generation is over -- an over-long copy ended it -- and
			// whatever the encoder still writes is discarded.
			continue
		}
		if !s.haveV0 {
			if !f.Sync {
				// Nothing before the first sync sample can start a
				// segment; an encoder's output always opens with one.
				continue
			}
			s.v0, s.haveV0, s.grid = f.Start, true, 1
			s.pending = []Fragment{f}
			for _, clock := range s.silence {
				clock.base = f.Start * uint64(clock.canned.Track.Timescale) / uint64(v.info.Timescale)
			}
			s.checkOverlongLocked()
			continue
		}
		if f.Sync && (f.Start >= s.v0+s.grid*s.gridTicks() || s.copyOverrunLocked(f)) {
			s.closeLocked(f.Start)
			s.grid = (f.Start-s.v0)/s.gridTicks() + 1
			s.pending = []Fragment{f}
		} else {
			s.pending = append(s.pending, f)
		}
		s.checkOverlongLocked()
	}
	if v.eof && !s.tailDone {
		s.tailDone = true
		if len(s.pending) > 0 {
			s.closeLocked(s.pending[len(s.pending)-1].End())
		}
	}
}

// spanReachesLocked reports whether the video from the pending segment's start
// to end is at least target + 0.5 s: the length at which RFC 8216 § 4.3.3.1
// rounds EXTINF above the target. Integer ticks:
// 2 x (end - start) >= (2 x target + 1) x Tv.
func (s *segmenter) spanReachesLocked(end uint64) bool {
	target := s.target
	if target == 0 {
		target = TargetDuration
	}
	return 2*(end-s.pending[0].Start) >= (2*target+1)*uint64(s.video.info.Timescale)
}

// copyOverrunLocked is the copy cut: a copied generation closes the pending
// segment before a sync fragment that would take it to target + 0.5 s, so a
// source whose GOP is a little under the grid (1.92 s against a target of 2)
// gets segments of one GOP each rather than of two. Encoded generations never
// take it.
func (s *segmenter) copyOverrunLocked(f Fragment) bool {
	return s.copied && len(s.pending) > 0 && s.spanReachesLocked(f.End())
}

// checkOverlongLocked is the over-long check of a copied generation: after a
// fragment joins pending, a span that has reached target + 0.5 s cannot be
// published as a segment of this run's target. That happens only to a single
// keyframe fragment longer than the target allows (the copy cut closes before
// any that would join a shorter one), and it ends the generation: pending,
// which holds it, is dropped and never published, no further segment is cut
// (tailDone), and onOverlong is fired once by run. Segments already cut stay in
// ready and publish through the normal path.
func (s *segmenter) checkOverlongLocked() {
	if !s.copied || s.overlong || len(s.pending) == 0 {
		return
	}
	if s.spanReachesLocked(s.pending[len(s.pending)-1].End()) {
		s.overlong, s.overlongFire, s.tailDone = true, true, true
		s.pending = nil
	}
}

func (s *segmenter) closeLocked(end uint64) {
	s.ready = append(s.ready, videoSegment{frags: s.pending, start: s.pending[0].Start, end: end, cut: time.Now()})
	s.pending = nil
}

// reached reports whether audio track t has read past video time vend, or
// can read no further.
func (s *segmenter) reached(t *track, vend uint64) bool {
	if t.eof {
		return true
	}
	if !t.haveInit || !t.seen {
		return false
	}
	return t.maxStart*uint64(s.video.info.Timescale) >= vend*uint64(t.info.Timescale)
}

// publishLocked publishes every cut segment whose audio is complete, or has
// waited AudioWait for it. It returns whether it published anything, and
// otherwise how long until the oldest waiting segment stops waiting.
func (s *segmenter) publishLocked() (bool, time.Duration) {
	progressed := false
	for len(s.ready) > 0 {
		seg := s.ready[0]
		waited := time.Since(seg.cut)
		for _, t := range s.audio {
			if !s.reached(t, seg.end) && waited < s.audioWait {
				return progressed, s.audioWait - waited
			}
		}
		s.ready = s.ready[1:]
		s.publishOneLocked(seg, s.tailDone && len(s.ready) == 0)
		progressed = true
	}
	return progressed, 0
}

func (s *segmenter) publishOneLocked(seg videoSegment, last bool) {
	tv := uint64(s.video.info.Timescale)
	parts := map[string]part{}
	var video []byte
	for _, f := range seg.frags {
		video = append(video, f.Data...)
	}
	parts[RenditionVideo] = part{data: video, duration: ticksToSeconds(seg.end-seg.start, tv)}

	var empty []string
	for _, t := range s.audio {
		ta, id := uint64(t.info.Timescale), t.info.ID
		if !t.haveInit {
			// An output that never wrote its init within AudioWait: its
			// placeholder fragment is at the timescale and track every
			// audio output here has.
			ta, id = AudioTimescale, 1
		}
		var data []byte
		var ticks uint64
		for len(t.frags) > 0 {
			f := t.frags[0]
			if f.Start*tv < seg.start*ta {
				t.frags = t.frags[1:]
				continue
			}
			if f.Start*tv >= seg.end*ta {
				break
			}
			data = append(data, f.Data...)
			ticks += f.Duration
			t.frags = t.frags[1:]
		}
		duration := ticksToSeconds(ticks, ta)
		if len(data) == 0 {
			if last {
				empty = append(empty, t.name)
				continue
			}
			// Mid-generation, the encoder wrote no audio for this span:
			// its audio output stopped, and publishLocked waited AudioWait
			// for it. The rendition still needs a segment at this
			// sequence number, and the video must not stall behind it, so
			// it gets an empty fragment of its own track at the span's
			// start: a gap a player plays through. The start is rounded UP
			// to a whole audio tick, as the silence clock rounds
			// (silence.go), so the fragment never starts before its span
			// (PR #529 review).
			data = synthFragment(1, id, (seg.start*ta+tv-1)/tv, nil, 0, 1024)
			duration = parts[RenditionVideo].duration
		}
		parts[t.name] = part{data: data, duration: duration}
	}
	if len(empty) > 0 {
		// The generation's last segment -- its flushed tail after stdin
		// EOF, whose final video frames outlast the audio -- has no audio
		// on some rendition. An empty fragment there stalled AVPlayer's
		// E-AC-3 path on the iOS 27 Simulator at the discontinuity
		// (measured; dropping the tail cured it), so the tail is not
		// published at all: no sequence number is used, and what is lost
		// is the generation's last segment -- usually a short flushed
		// tail, but up to a full segment when an audio output ended a
		// whole segment before the video did.
		return
	}
	for name, clock := range s.silence {
		data, ticks := clock.segment(seg.end-s.v0, s.video.info.Timescale)
		parts[name] = part{data: data, duration: ticksToSeconds(ticks, uint64(clock.canned.Track.Timescale))}
	}

	pdt := s.pdtAnchor().Add(ticksToDuration(seg.start, tv))
	s.store.publish(s.gen, pdt, parts)
	s.published++
	if s.published == 1 && s.onFirst != nil {
		s.onFirst()
	}
}

func ticksToSeconds(ticks, timescale uint64) float64 {
	if timescale == 0 {
		return 0
	}
	return float64(ticks) / float64(timescale)
}

// ticksToDuration converts without the overflow ticks*1e9 would hit after a
// day of 90 kHz ticks.
func ticksToDuration(ticks, timescale uint64) time.Duration {
	if timescale == 0 {
		return 0
	}
	whole, rem := ticks/timescale, ticks%timescale
	return time.Duration(whole)*time.Second + time.Duration(rem*uint64(time.Second)/timescale) // #nosec G115 -- rem < timescale, so rem*1e9 fits
}
