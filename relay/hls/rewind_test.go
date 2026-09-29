package hls

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"
)

// testClock is a store's injected clock.
type testClock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *testClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

func (c *testClock) Advance(d time.Duration) {
	c.mu.Lock()
	c.t = c.t.Add(d)
	c.mu.Unlock()
}

// lockedBuffer is a log sink several goroutines write to.
type lockedBuffer struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *lockedBuffer) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}

func (l *lockedBuffer) String() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.String()
}

// testFS is OSFS with a log of every call, a hook that fails chosen ones, and a
// gate WriteFile waits behind.
type testFS struct {
	OSFS
	mu    sync.Mutex
	ops   []string
	calls map[string]int
	// fail is asked before each call with the operation's name and its 1-based
	// call number; a non-nil answer is the call's error.
	fail func(op string, n int) error
	// gate, when non-nil, holds every WriteFile until it is closed.
	gate chan struct{}
}

func newTestFS() *testFS { return &testFS{calls: map[string]int{}} }

func (f *testFS) enter(op string, args ...string) error {
	f.mu.Lock()
	f.calls[op]++
	n := f.calls[op]
	f.ops = append(f.ops, op+" "+strings.Join(args, " "))
	fail := f.fail
	f.mu.Unlock()
	if fail != nil {
		return fail(op, n)
	}
	return nil
}

func (f *testFS) opsMatching(prefix, contains string) []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []string
	for _, op := range f.ops {
		if strings.HasPrefix(op, prefix) && strings.Contains(op, contains) {
			out = append(out, op)
		}
	}
	return out
}

func (f *testFS) count(op string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.calls[op]
}

func (f *testFS) MkdirAll(dir string) error {
	if err := f.enter("MkdirAll", dir); err != nil {
		return err
	}
	return f.OSFS.MkdirAll(dir)
}

func (f *testFS) WriteFile(name string, data []byte) error {
	if f.gate != nil {
		<-f.gate
	}
	if err := f.enter("WriteFile", name); err != nil {
		return err
	}
	return f.OSFS.WriteFile(name, data)
}

func (f *testFS) Rename(from, to string) error {
	if err := f.enter("Rename", from, to); err != nil {
		return err
	}
	return f.OSFS.Rename(from, to)
}

func (f *testFS) ReadFile(name string) ([]byte, error) {
	if err := f.enter("ReadFile", name); err != nil {
		return nil, err
	}
	return f.OSFS.ReadFile(name)
}

func (f *testFS) Remove(name string) error {
	if err := f.enter("Remove", name); err != nil {
		return err
	}
	return f.OSFS.Remove(name)
}

func (f *testFS) RemoveAll(dir string) error {
	if err := f.enter("RemoveAll", dir); err != nil {
		return err
	}
	return f.OSFS.RemoveAll(dir)
}

func (f *testFS) ReadDir(dir string) ([]string, error) {
	if err := f.enter("ReadDir", dir); err != nil {
		return nil, err
	}
	return f.OSFS.ReadDir(dir)
}

// rewindRig is a Rewind under a temporary root with a captured log.
type rewindRig struct {
	t     *testing.T
	r     *Rewind
	fs    *testFS
	log   *lockedBuffer
	clock *testClock
}

func newRewindRig(t *testing.T) *rewindRig {
	t.Helper()
	rig := &rewindRig{t: t, fs: newTestFS(), log: &lockedBuffer{}, clock: &testClock{t: t0}}
	rig.r = NewRewind(RewindConfig{
		Root:   t.TempDir(),
		FS:     rig.fs,
		BootID: "boot",
		Log:    slog.New(slog.NewTextHandler(rig.log, &slog.HandlerOptions{Level: slog.LevelDebug})),
	})
	rig.r.joinWait = 5 * time.Second
	t.Cleanup(rig.r.Close)
	return rig
}

// store is a new store with a window of the given depth, on the rig's clock.
func (g *rewindRig) store(channel string, depth time.Duration) *Store {
	s := NewStore(g.clock.Now)
	g.r.open(channel, depth, s)
	return s
}

func (g *rewindRig) sync() {
	g.t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := g.r.Sync(ctx); err != nil {
		g.t.Fatalf("the writer's batch did not complete: %v", err)
	}
}

func testCtx(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	t.Cleanup(cancel)
	return ctx
}

// pub publishes one segment of the given generation and size, at pdt.
func pub(s *Store, gen int, pdt time.Time, size int) uint64 {
	s.mu.Lock()
	seq := s.nextSeq
	s.mu.Unlock()
	return s.publish(gen, pdt, map[string]part{
		RenditionVideo: {data: []byte(fmt.Sprintf("v%06d", seq) + strings.Repeat("x", max(0, size-7))), duration: 2},
	})
}

// pubBoth publishes a two-rendition segment whose data names its sequence.
func pubBoth(s *Store, gen int, pdt time.Time) uint64 {
	s.mu.Lock()
	seq := s.nextSeq
	s.mu.Unlock()
	return s.publish(gen, pdt, map[string]part{
		RenditionVideo: {data: []byte(fmt.Sprintf("video-%d", seq)), duration: 2},
		RenditionAAC:   {data: []byte(fmt.Sprintf("aac-%d", seq)), duration: 1.984},
	})
}

// publishDurable publishes n one-rendition segments 2 s apart from `from` and
// waits for each to reach the disk, so the writer's queue never fills.
func publishDurable(t *testing.T, s *Store, gen, n int, from time.Time, size int) {
	t.Helper()
	for i := 0; i < n; i++ {
		seq := pub(s, gen, from.Add(time.Duration(i)*2*time.Second), size)
		if err := s.WaitDurable(testCtx(t), seq); err != nil {
			t.Fatalf("segment %d never reached the disk: %v", seq, err)
		}
	}
}

func mediaSequence(t *testing.T, s *Store) (first uint64, listed int) {
	t.Helper()
	body, _, ok := s.MediaPlaylist(RenditionVideo)
	if !ok {
		t.Fatalf("no media playlist")
	}
	m := regexp.MustCompile(`#EXT-X-MEDIA-SEQUENCE:(\d+)`).FindStringSubmatch(string(body))
	if m == nil {
		t.Fatalf("no media sequence in\n%s", body)
	}
	first, _ = strconv.ParseUint(m[1], 10, 64)
	return first, strings.Count(string(body), "#EXTINF:")
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// Row ⟨G⟩, Global constraint 2: publish queues and returns; the writer writes
// each segment once, under a temporary name and then renamed, off the
// segmenter's goroutine.
func TestTheWindowWritesEachSegmentOnceOffTheSegmentersGoroutine(t *testing.T) {
	g := newRewindRig(t)
	g.fs.gate = make(chan struct{})
	released := false
	release := func() {
		if !released {
			released = true
			close(g.fs.gate)
		}
	}
	t.Cleanup(release)
	s := g.store("chan", time.Hour)
	s.SetInit(RenditionVideo, 0, []byte("vinit"))
	s.SetInit(RenditionAAC, 0, []byte("ainit"))
	done := make(chan struct{})
	go func() {
		for i := 0; i < 3; i++ {
			pubBoth(s, 0, t0.Add(time.Duration(i)*2*time.Second))
		}
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatalf("publish blocked behind the disk")
	}
	if first, listed := mediaSequence(t, s); first != 0 || listed != 3 {
		t.Fatalf("with the gate shut the playlist lists %d from %d, want 3 from 0", listed, first)
	}
	release()
	if err := s.WaitDurable(testCtx(t), 2); err != nil {
		t.Fatal(err)
	}
	for seq := 0; seq < 3; seq++ {
		for _, rendition := range []string{RenditionVideo, RenditionAAC} {
			name := filepath.Join(g.r.BootDir(), "chan", "1", "0", rendition, strconv.Itoa(seq)+".m4s")
			w := g.fs.opsMatching("WriteFile", name+".tmp")
			r := g.fs.opsMatching("Rename", name+".tmp "+name)
			if len(w) != 1 || len(r) != 1 {
				t.Errorf("segment %d %s: %d writes and %d renames of its files, want one each\n%v", seq, rendition, len(w), len(r), g.fs.ops)
			}
		}
	}
	for _, rendition := range []string{RenditionVideo, RenditionAAC} {
		if n := len(g.fs.opsMatching("Rename", filepath.Join(rendition, "init.mp4.tmp"))); n != 1 {
			t.Errorf("%s: %d init.mp4 renames, want one", rendition, n)
		}
	}
}

// The newest 21 are served from memory: no read of the disk.
func TestTheLiveEdgeIsServedFromMemory(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, 30, t0, 64)
	for seq := uint64(9); seq < 30; seq++ {
		if _, ok := s.Segment(RenditionVideo, seq); !ok {
			t.Fatalf("segment %d is not served", seq)
		}
	}
	if n := g.fs.count("ReadFile"); n != 0 {
		t.Fatalf("the newest 21 made %d disk reads, want none", n)
	}
	if _, ok := s.Segment(RenditionVideo, 0); !ok {
		t.Fatalf("segment 0 is not served")
	}
	if n := g.fs.count("ReadFile"); n != 1 {
		t.Fatalf("segment 0 made %d disk reads, want one", n)
	}
}

func TestAnOldSegmentIsReadFromDisk(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, 30, t0, 64)
	s.mu.Lock()
	held := s.segs[0].held || s.segs[0].parts[RenditionVideo].data != nil
	s.mu.Unlock()
	if held {
		t.Fatalf("segment 0 still holds its data in memory")
	}
	data, ok := s.Segment(RenditionVideo, 0)
	if !ok || !strings.HasPrefix(string(data), "v000000") || len(data) != 64 {
		t.Fatalf("segment 0 from disk = %q, %t", data, ok)
	}
}

// Row ⟨G⟩: every segment within the depth is listed, by PDT rather than by
// count, and a discontinuity that left is counted.
func TestTheWindowListsEverySegmentWithinTheDepth(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", 60*time.Second)
	publishDurable(t, s, 0, 40, t0, 32)
	body, _, _ := s.MediaPlaylist(RenditionVideo)
	if first, listed := mediaSequence(t, s); first != 9 || listed != 31 {
		t.Fatalf("depth 60 s over 40 segments 2 s apart: lists %d from %d, want 31 from 9", listed, first)
	}
	if strings.Contains(string(body), "PLAYLIST-TYPE") || strings.Count(string(body), "#EXT-X-PROGRAM-DATE-TIME:") != 31 {
		t.Fatalf("the window carries a playlist type or misses a PDT:\n%s", body)
	}

	// A generation re-anchors its PDTs, as a new one does: the sweep follows
	// the PDT rule, not a count of segments.
	g2 := g.store("chan2", 60*time.Second)
	publishDurable(t, g2, 0, 10, t0, 32)
	publishDurable(t, g2, 1, 10, t0.Add(48*time.Second), 32)
	publishDurable(t, g2, 2, 30, t0.Add(96*time.Second), 32)
	if first, listed := mediaSequence(t, g2); first != 20 || listed != 30 {
		t.Fatalf("re-anchored generations: lists %d from %d, want 30 from 20 (a count would list 31 from 19)", listed, first)
	}
	body, _, _ = g2.MediaPlaylist(RenditionVideo)
	if !strings.Contains(string(body), "#EXT-X-DISCONTINUITY-SEQUENCE:1\n") {
		t.Fatalf("a discontinuity that left the window is not counted:\n%s", body)
	}
}

// Row ⟨G⟩, R83: a segment that leaves the playlist by depth stays fetchable
// for the retention and is then unlinked.
func TestADepthRetiredSegmentStaysFetchableForTheRetention(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", 60*time.Second)
	publishDurable(t, s, 0, 32, t0, 32) // segment 31 retires segment 0 at t0
	path := filepath.Join(g.r.BootDir(), "chan", "1", "0", RenditionVideo, "0.m4s")
	if body, _, _ := s.MediaPlaylist(RenditionVideo); strings.Contains(string(body), "video/0.m4s") {
		t.Fatalf("segment 0 is still listed")
	}
	s.mu.Lock()
	retention := s.unlistedRetentionLocked()
	s.mu.Unlock()
	if retention != 22*time.Second {
		t.Fatalf("the retention at target 2 is %v, want 22 s", retention)
	}
	g.clock.Advance(retention - time.Millisecond)
	publishDurable(t, s, 0, 1, t0.Add(64*time.Second), 32)
	g.sync()
	if !exists(path) {
		t.Fatalf("the retired segment was unlinked inside the retention")
	}
	if data, ok := s.Segment(RenditionVideo, 0); !ok || len(data) != 32 {
		t.Fatalf("the retired segment is not fetchable inside the retention: %q, %t", data, ok)
	}
	g.clock.Advance(time.Millisecond)
	publishDurable(t, s, 0, 1, t0.Add(66*time.Second), 32)
	g.sync()
	if exists(path) {
		t.Fatalf("the retired segment's file is still there past the retention")
	}
	if _, ok := s.Segment(RenditionVideo, 0); ok {
		t.Fatalf("the retired segment is still served past the retention")
	}
}

// Row ⟨G⟩: the cap's order is retired segments, then a lingering window's
// oldest, then any window's oldest.
func TestTheCapEvictsRetiredThenLingeringThenOldest(t *testing.T) {
	g := newRewindRig(t)
	const size = 1000
	b := g.store("B", 44*time.Second)
	publishDurable(t, b, 0, 24, t0, size) // seg 0 retired by depth; 1..23 listed
	a := g.store("A", time.Hour)
	a.SetLingering(true)
	publishDurable(t, a, 0, 22, t0.Add(time.Hour), size)
	g.sync()
	total := g.r.Bytes()
	if total != 46*size {
		t.Fatalf("on disk = %d, want %d", total, 46*size)
	}
	g.r.SetCap(total - 3*size + 1)
	g.sync()
	removes := g.fs.opsMatching("Remove", ".m4s")
	if len(removes) != 3 {
		t.Fatalf("the cap made %d evictions, want 3:\n%v", len(removes), removes)
	}
	order := []string{
		filepath.Join("B", "1", "0", RenditionVideo, "0.m4s"),
		filepath.Join("A", "2", "0", RenditionVideo, "0.m4s"),
		filepath.Join("B", "1", "0", RenditionVideo, "1.m4s"),
	}
	for i, suffix := range order {
		if !strings.HasSuffix(removes[i], suffix) {
			t.Errorf("eviction %d removed %s, want ...%s (retired, then the lingering window's oldest, then the oldest)", i+1, removes[i], suffix)
		}
	}
}

// Decision 6: a pending segment has no file yet and is never a victim, and a
// window whose head is pending contributes no listed victim.
func TestTheCapSkipsAPendingSegment(t *testing.T) {
	g := newRewindRig(t)
	g.r.Close() // no writer: the state below is built by hand
	s := g.store("chan", time.Hour)
	for i := 0; i < StoreSegments+1; i++ {
		// published with the window closed to the queue, so nothing degrades
		s.mu.Lock()
		w := s.window
		s.mu.Unlock()
		s.publish(0, t0.Add(time.Duration(i)*2*time.Second), map[string]part{RenditionVideo: {data: []byte("x"), duration: 2}})
		s.mu.Lock()
		w.pending, w.queue = 0, nil
		s.mu.Unlock()
	}
	s.mu.Lock()
	w := s.window
	head := s.segs[0]
	head.pending, head.onDisk, head.bytes = true, false, 1000
	w.pending = 1
	retired := &segment{seq: 999, gen: 0, pdt: t0.Add(-time.Hour), bytes: 1000, onDisk: true, parts: map[string]part{RenditionVideo: {duration: 2}}}
	s.retired = []*segment{retired}
	path := w.segPath(0, RenditionVideo, 999)
	s.mu.Unlock()
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, make([]byte, 1000), 0o600); err != nil {
		t.Fatal(err)
	}
	g.r.total.Store(2000)
	g.r.SetCap(500)
	g.r.enforceCap()
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.retired) != 0 || exists(path) {
		t.Errorf("the retired segment was not evicted first")
	}
	if s.segs[0] != head || !head.pending {
		t.Errorf("the pending head left the listing or stopped being pending")
	}
	removes := g.fs.opsMatching("Remove", "")
	if len(removes) != 1 || !strings.HasSuffix(removes[0], "999.m4s") {
		t.Errorf("Remove calls = %v, want only the retired segment's file", removes)
	}
	if g.r.Bytes() != 1000 {
		t.Errorf("on disk = %d, want the pending head's 1000 left", g.r.Bytes())
	}
	if n := strings.Count(g.log.String(), "cap cannot be met"); n != 1 {
		t.Errorf("the unmet cap was logged %d times, want once", n)
	}
}

// Decision 6: the newest 21 are never evicted, and an unmet cap logs once.
func TestTheCapNeverEvictsTheInMemoryEdge(t *testing.T) {
	g := newRewindRig(t)
	a, b := g.store("A", time.Hour), g.store("B", time.Hour)
	g.r.SetCap(1)
	for round := 0; round < 3; round++ {
		pub(a, 0, t0.Add(time.Duration(round)*2*time.Second), 100)
		pub(b, 0, t0.Add(time.Duration(round)*2*time.Second), 100)
		g.sync() // a batch that started after both publishes: it writes them, then meets the cap
	}
	stores := map[string]*Store{"A": a, "B": b}
	for name, run := range map[string]string{"A": "1", "B": "2"} {
		for seq := 0; seq < 3; seq++ {
			if path := filepath.Join(g.r.BootDir(), name, run, "0", RenditionVideo, strconv.Itoa(seq)+".m4s"); !exists(path) {
				t.Errorf("the cap removed segment %d of window %s, which is among its window's newest 21", seq, name)
			}
		}
		if first, listed := mediaSequence(t, stores[name]); first != 0 || listed != 3 {
			t.Errorf("window %s: the listing changed under an unmeetable cap: %d from %d", name, listed, first)
		}
	}
	if n := len(g.fs.opsMatching("Remove", "")); n != 0 {
		t.Errorf("the cap made %d Remove calls against the in-memory edge", n)
	}
	if n := strings.Count(g.log.String(), "cap cannot be met"); n != 1 {
		t.Errorf("the unmet cap was logged %d times over three batches, want once", n)
	}
}

// Global constraint 4: a read in flight is never unlinked under it.
func TestAReadInFlightIsNeverUnlinkedUnderItsReader(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, StoreSegments+1, t0, 64)
	entered, release := make(chan struct{}), make(chan struct{})
	s.beforeDiskRead = func() {
		close(entered)
		<-release
	}
	type result struct {
		data []byte
		ok   bool
	}
	got := make(chan result, 1)
	go func() {
		data, ok := s.Segment(RenditionVideo, 0)
		got <- result{data, ok}
	}()
	<-entered
	path := filepath.Join(g.r.BootDir(), "chan", "1", "0", RenditionVideo, "0.m4s")
	g.r.SetCap(1)
	g.sync()
	if first, _ := mediaSequence(t, s); first != 1 {
		t.Fatalf("segment 0 is still listed after the cap evicted it")
	}
	if !exists(path) {
		t.Fatalf("the file was unlinked under its reader")
	}
	close(release)
	res := <-got
	if !res.ok || !strings.HasPrefix(string(res.data), "v000000") {
		t.Fatalf("the read answered %q, %t, want the published bytes", res.data, res.ok)
	}
	g.sync()
	if exists(path) {
		t.Fatalf("the doomed segment's file outlived its last reader")
	}
}

// Row ⟨H⟩: a directory, write or rename error degrades the window and nothing
// else.
func TestAWriteErrorDegradesTheWindowNotTheOutput(t *testing.T) {
	for _, op := range []string{"MkdirAll", "WriteFile", "Rename"} {
		t.Run(op, func(t *testing.T) {
			g := newRewindRig(t)
			g.fs.fail = func(o string, n int) error {
				if o == op && n == 5 {
					return &fs.PathError{Op: op, Path: "x", Err: syscall.ENOSPC}
				}
				return nil
			}
			s := g.store("chan", time.Hour)
			for gen := 0; gen < 4; gen++ {
				s.SetInit(RenditionVideo, gen, []byte("vinit"))
				s.SetInit(RenditionAAC, gen, []byte("ainit"))
			}
			for i := 0; i < 4; i++ {
				pubBoth(s, i, t0.Add(time.Duration(i)*2*time.Second))
				g.sync()
			}
			if err := s.WaitDegraded(testCtx(t)); err != nil {
				t.Fatal(err)
			}
			if !s.WindowStatus().Degraded {
				t.Fatalf("the window did not degrade")
			}
			if _, _, ok := s.MediaPlaylist(RenditionVideo); !ok {
				t.Fatalf("the playlist stopped rendering")
			}
			before := len(g.fs.opsMatching("", filepath.Join(g.r.BootDir(), "chan")))
			pubBoth(s, 4, t0.Add(20*time.Second))
			pubBoth(s, 4, t0.Add(22*time.Second))
			g.sync()
			if after := len(g.fs.opsMatching("", filepath.Join(g.r.BootDir(), "chan"))); after != before {
				t.Errorf("the degraded window made %d further disk calls", after-before)
			}
			logged := g.log.String()
			if n := strings.Count(logged, "stopped persisting"); n != 1 || !strings.Contains(logged, "channel=chan") || !strings.Contains(logged, "run=1") {
				t.Errorf("want one warning naming the channel and the run, got %d:\n%s", n, logged)
			}
		})
	}
}

// Row ⟨H⟩, Decision 4: a window that degraded lists its disk run only while it
// is contiguous with the live edge, then the live edge alone.
func TestADegradedWindowListsItsDiskRunThenOnlyTheLiveEdge(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, 26, t0, 32)
	g.fs.mu.Lock()
	g.fs.fail = func(op string, _ int) error {
		if op == "WriteFile" {
			return syscall.ENOSPC
		}
		return nil
	}
	g.fs.mu.Unlock()
	at := func(i int) time.Time { return t0.Add(time.Duration(i) * 2 * time.Second) }
	pub(s, 0, at(26), 32)
	if err := s.WaitDegraded(testCtx(t)); err != nil {
		t.Fatal(err)
	}
	if first, _ := mediaSequence(t, s); first != 0 {
		t.Fatalf("right after the degradation the playlist starts at %d, want 0", first)
	}
	for i := 27; i < 37; i++ {
		pub(s, 0, at(i), 32)
	}
	if first, _ := mediaSequence(t, s); first != 27 {
		t.Fatalf("10 publications later the playlist starts at %d, want 27", first)
	}
	if _, ok := s.Segment(RenditionVideo, 26); !ok {
		t.Fatalf("segment 26 left memory while it was still within the store")
	}
	for i := 37; i < 48; i++ {
		pub(s, 0, at(i), 32)
	}
	if _, listed := mediaSequence(t, s); listed != LiveEdge {
		t.Fatalf("11 more publications later the playlist lists %d, want exactly %d", listed, LiveEdge)
	}
}

// Row ⟨H⟩, Decision 3: a writer a whole store behind degrades the window at the
// 22nd unwritten segment.
func TestAFullWriterQueueDegradesTheWindow(t *testing.T) {
	g := newRewindRig(t)
	g.fs.gate = make(chan struct{})
	t.Cleanup(func() { close(g.fs.gate) })
	s := g.store("chan", time.Hour)
	for i := 0; i < StoreSegments; i++ {
		pub(s, 0, t0.Add(time.Duration(i)*2*time.Second), 32)
	}
	if s.WindowStatus().Degraded {
		t.Fatalf("the window degraded before its queue was full")
	}
	pub(s, 0, t0.Add(time.Hour), 32)
	if !s.WindowStatus().Degraded {
		t.Fatalf("the 22nd unwritten segment did not degrade the window")
	}
	if !strings.Contains(g.log.String(), "the writer queue is full") {
		t.Errorf("the degradation's reason was not logged:\n%s", g.log.String())
	}
}

// Row ⟨H⟩, Decision 9: the boot directory is retried, so a window opened after
// it becomes makeable writes.
func TestTheBootDirectoryIsRetriedAtEveryWindowOpen(t *testing.T) {
	g := newRewindRig(t)
	g.fs.fail = func(op string, n int) error {
		if op == "MkdirAll" && n == 1 {
			return syscall.EACCES
		}
		return nil
	}
	first := g.store("one", time.Hour)
	pub(first, 0, t0, 32)
	if err := first.WaitDegraded(testCtx(t)); err != nil {
		t.Fatal(err)
	}
	second := g.store("two", time.Hour)
	seq := pub(second, 0, t0, 32)
	if err := second.WaitDurable(testCtx(t), seq); err != nil {
		t.Fatalf("the second window did not write: %v", err)
	}
	if second.WindowStatus().Degraded {
		t.Fatalf("the second window degraded")
	}
}

func TestStartUpRemovesEveryOtherBootDirectory(t *testing.T) {
	root := t.TempDir()
	for _, dir := range []string{"stale1/chan/1", "stale2/chan/1", "boot/chan/1"} {
		if err := os.MkdirAll(filepath.Join(root, dir), 0o750); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(root, "stray"), []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	r := NewRewind(RewindConfig{Root: root, BootID: "boot"})
	defer r.Close()
	r.CleanStale()
	entries, _ := os.ReadDir(root)
	if len(entries) != 1 || entries[0].Name() != "boot" {
		t.Fatalf("the root holds %v, want only this boot's directory", entries)
	}
	if !exists(filepath.Join(root, "boot", "chan", "1")) {
		t.Fatalf("this boot's contents were removed")
	}
}

func TestCleanStaleReportsAFailureOnceAndAnAbsentRootNot(t *testing.T) {
	g := newRewindRig(t)
	g.r.root = filepath.Join(t.TempDir(), "absent")
	g.r.CleanStale()
	if strings.Contains(g.log.String(), "WARN") {
		t.Fatalf("an absent root warned:\n%s", g.log.String())
	}
	root := t.TempDir()
	for _, name := range []string{"a", "b"} {
		_ = os.Mkdir(filepath.Join(root, name), 0o750)
	}
	g.r.root = root
	g.fs.fail = func(op string, _ int) error {
		if op == "RemoveAll" {
			return syscall.EBUSY
		}
		return nil
	}
	g.r.CleanStale()
	if n := strings.Count(g.log.String(), "could not remove a stale rewind directory"); n != 1 {
		t.Fatalf("two failing removals were logged %d times, want once", n)
	}
	g.fs.fail = func(op string, _ int) error {
		if op == "ReadDir" {
			return syscall.EIO
		}
		return nil
	}
	g.r.CleanStale()
	if !strings.Contains(g.log.String(), "could not list the rewind directory") {
		t.Fatalf("a listing failure was not logged:\n%s", g.log.String())
	}
}

func TestRemoveBootDeletesTheBootDirectory(t *testing.T) {
	g := newRewindRig(t)
	if err := os.MkdirAll(filepath.Join(g.r.BootDir(), "chan", "1"), 0o750); err != nil {
		t.Fatal(err)
	}
	g.r.RemoveBoot()
	if exists(g.r.BootDir()) {
		t.Fatalf("the boot directory survived RemoveBoot")
	}
	select {
	case <-g.r.exited:
	default:
		t.Fatalf("the writer is still running after RemoveBoot")
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := g.r.Sync(ctx); err == nil {
		t.Fatalf("a Sync on a stopped writer answered nil")
	}
	g.fs.fail = func(string, int) error { return syscall.EBUSY }
	g.r.RemoveBoot()
	if !strings.Contains(g.log.String(), "could not remove the rewind directory") {
		t.Fatalf("a failed removal was not logged:\n%s", g.log.String())
	}
}

func TestCloseGivesUpOnAWriterThatWillNotStop(t *testing.T) {
	g := newRewindRig(t)
	g.fs.gate = make(chan struct{})
	t.Cleanup(func() { close(g.fs.gate) })
	g.r.joinWait = 50 * time.Millisecond
	s := g.store("chan", time.Hour)
	pub(s, 0, t0, 32)
	deadline := time.Now().Add(5 * time.Second)
	for g.fs.count("MkdirAll") == 0 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	g.r.Close()
	if !strings.Contains(g.log.String(), "did not stop in time") {
		t.Fatalf("a stuck writer's Close did not report it:\n%s", g.log.String())
	}
}

// A window whose pipeline stopped is removed once no read holds it.
func TestAStoppedPipelinesWindowIsRemovedOnceUnread(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, StoreSegments+1, t0, 64)
	entered, release := make(chan struct{}), make(chan struct{})
	s.beforeDiskRead = func() {
		close(entered)
		<-release
	}
	done := make(chan struct{})
	go func() {
		s.Segment(RenditionVideo, 0)
		close(done)
	}()
	<-entered
	s.Close()
	g.sync()
	runDir := filepath.Join(g.r.BootDir(), "chan", "1")
	if !exists(runDir) {
		t.Fatalf("the run directory was removed under a read")
	}
	close(release)
	<-done
	g.sync()
	if exists(runDir) {
		t.Fatalf("the run directory outlived its last read")
	}
	if g.r.Bytes() != 0 {
		t.Fatalf("Bytes() = %d after the window's removal, want 0", g.r.Bytes())
	}
}

// Decision 7: once the removal is decided no disk read starts.
func TestAClosingWindowRefusesANewDiskRead(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, StoreSegments+1, t0, 64)
	if _, ok := s.Segment(RenditionVideo, 0); !ok {
		t.Fatalf("segment 0 was not read from the disk before the close")
	}
	reads := g.fs.count("ReadFile")
	s.Close()
	g.sync()
	if _, ok := s.Segment(RenditionVideo, 0); ok {
		t.Fatalf("a closed window served a disk read")
	}
	if g.fs.count("ReadFile") != reads {
		t.Fatalf("a closed window made a disk read")
	}
}

func TestTheChannelDirectoryNameIsSafe(t *testing.T) {
	uuid := "8f1c2a4e-9b7d-4e1f-a6c3-0d5e2b7a9c11"
	if got := channelDir(uuid); got != uuid {
		t.Errorf("a UUID became %q", got)
	}
	for _, id := range []string{"../x", "", strings.Repeat("a", 65)} {
		got := channelDir(id)
		if !regexp.MustCompile(`^x[0-9a-f]{16}$`).MatchString(got) {
			t.Errorf("channelDir(%q) = %q, want x and 16 hex characters", id, got)
		}
	}
}

// The rendered playlist is reused until the store changes, and every kind of
// change counts.
func TestTheRenderedPlaylistIsReusedUntilTheStoreChanges(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, StoreSegments+1, t0, 64)
	render := func() string {
		body, _, _ := s.MediaPlaylist(RenditionVideo)
		return string(body)
	}
	before := render()
	rendersBefore := s.renders
	if render() != before || s.renders != rendersBefore {
		t.Fatalf("a second render with no change was not the cached one")
	}
	pub(s, 0, t0.Add(time.Hour), 64)
	afterPublish := render()
	if afterPublish == before || s.renders != rendersBefore+1 {
		t.Fatalf("a publish did not make the next render fresh")
	}
	g.r.SetCap(1)
	g.sync()
	afterEvict := render()
	if afterEvict == afterPublish || s.renders != rendersBefore+2 {
		t.Fatalf("a cap eviction did not make the next render fresh")
	}

	// A degradation, on a store whose segments are still pending.
	h := newRewindRig(t)
	h.fs.gate = make(chan struct{})
	t.Cleanup(func() { close(h.fs.gate) })
	d := h.store("chan", time.Hour)
	for i := 0; i < 12; i++ {
		pub(d, 0, t0.Add(time.Duration(i)*2*time.Second), 32)
	}
	beforeDegrade, _, _ := d.MediaPlaylist(RenditionVideo)
	h.r.degrade(d.window, errors.New("boom"), "")
	afterDegrade, _, _ := d.MediaPlaylist(RenditionVideo)
	if string(beforeDegrade) == string(afterDegrade) {
		t.Fatalf("a degradation did not change the playlist")
	}
}

func TestSetCapIgnoresANonPositiveValue(t *testing.T) {
	g := newRewindRig(t)
	g.r.SetCap(1 << 30)
	g.r.SetCap(0)
	g.r.SetCap(-1)
	if g.r.Cap() != 1<<30 {
		t.Fatalf("Cap() = %d after non-positive values, want it unchanged", g.r.Cap())
	}
}

func TestSegmentAtReportsHowFarBehindTheNewestItIs(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, 10, t0, 32)
	if _, behind, ok := s.SegmentAt(RenditionVideo, 3); !ok || behind != 12*time.Second {
		t.Fatalf("segment 3 of 10: behind = %v, %t, want 12 s", behind, ok)
	}
	if _, behind, ok := s.SegmentAt(RenditionVideo, 9); !ok || behind != 0 {
		t.Fatalf("the newest: behind = %v, %t, want 0", behind, ok)
	}
	if _, _, ok := s.SegmentAt("ac3", 9); ok {
		t.Fatalf("a rendition the segment lacks was served")
	}
	if _, _, ok := s.SegmentAt(RenditionVideo, 99); ok {
		t.Fatalf("a future sequence was served")
	}
}

func TestAReadThatFailsAnswersNotFound(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, StoreSegments+1, t0, 64)
	g.fs.fail = func(op string, _ int) error {
		if op == "ReadFile" {
			return syscall.EIO
		}
		return nil
	}
	if _, ok := s.Segment(RenditionVideo, 0); ok {
		t.Fatalf("a failed read was served")
	}
	if !strings.Contains(g.log.String(), "could not read a rewind segment") {
		t.Fatalf("the failed read was not logged:\n%s", g.log.String())
	}
}

func TestWaitDurableAnswersAtOnceWhereItCannotWait(t *testing.T) {
	plain := NewStore(nil)
	if err := plain.WaitDurable(context.Background(), 0); !errors.Is(err, ErrNoWindow) {
		t.Errorf("no window: %v, want ErrNoWindow", err)
	}
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, StoreSegments+3, t0, 64)
	// segment 0 is still retained (a retired or listed segment); a future
	// sequence waits for its context
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if err := s.WaitDurable(ctx, 500); !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("a future sequence: %v, want to wait out its context", err)
	}
	g.r.degrade(s.window, errors.New("boom"), "")
	if err := s.WaitDurable(context.Background(), 0); !errors.Is(err, ErrWindowDegraded) {
		t.Errorf("degraded: %v, want ErrWindowDegraded", err)
	}
	h := g.store("other", time.Hour)
	publishDurable(t, h, 0, 1, t0, 64)
	h.Close()
	if err := h.WaitDurable(context.Background(), 0); !errors.Is(err, ErrStoreClosed) {
		t.Errorf("closed: %v, want ErrStoreClosed", err)
	}
	k := g.store("third", 20*time.Second)
	publishDurable(t, k, 0, 40, t0, 64)
	g.clock.Advance(time.Hour)
	publishDurable(t, k, 0, 1, t0.Add(time.Hour), 64)
	g.sync()
	if err := k.WaitDurable(context.Background(), 0); !errors.Is(err, ErrSegmentGone) {
		t.Errorf("a segment that left the store: %v, want ErrSegmentGone", err)
	}
}

func TestWaitDegradedWaitsOutItsContext(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if err := s.WaitDegraded(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("a healthy window's WaitDegraded = %v, want its context's end", err)
	}
	if err := NewStore(nil).WaitDegraded(ctx); err == nil {
		t.Fatalf("a store with no window reported degraded")
	}
}

func TestSyncWaitsOutItsContext(t *testing.T) {
	g := newRewindRig(t)
	g.fs.gate = make(chan struct{})
	t.Cleanup(func() { close(g.fs.gate) })
	s := g.store("chan", time.Hour)
	pub(s, 0, t0, 32)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if err := g.r.Sync(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Sync against a stuck writer = %v, want its context's end", err)
	}
}

// A segment that left the store while its write was in flight is not counted
// and its files are queued for unlink at once.
func TestACommitForASegmentThatLeftTheStoreCountsNothing(t *testing.T) {
	g := newRewindRig(t)
	g.r.Close()
	s := g.store("chan", time.Hour)
	w := s.window
	gone := &segment{seq: 77, gen: 0, bytes: 500, pending: true, parts: map[string]part{RenditionVideo: {duration: 2}}}
	g.r.commit(w, gone, 12)
	s.mu.Lock()
	defer s.mu.Unlock()
	if gone.onDisk || g.r.Bytes() != 12 {
		t.Errorf("an orphan was counted: onDisk %t, bytes %d (only its init's 12 belong to the window)", gone.onDisk, g.r.Bytes())
	}
	if len(w.unlinks) != 1 || !strings.HasSuffix(w.unlinks[0], "77.m4s") {
		t.Errorf("unlinks = %v, want the orphan's file", w.unlinks)
	}
}

// A retired segment still queued for the disk is dropped from the queue when its
// retention passes, so the writer never writes a file it is about to unlink.
func TestARetiredPendingSegmentIsDroppedFromTheQueueAtItsRetention(t *testing.T) {
	g := newRewindRig(t)
	g.r.Close()
	s := g.store("chan", 10*time.Second)
	for i := 0; i < StoreSegments+3; i++ {
		s.mu.Lock()
		s.window.pending, s.window.queue = 0, nil
		s.mu.Unlock()
		pub(s, 0, t0.Add(time.Duration(i)*4*time.Second), 32)
	}
	s.mu.Lock()
	w := s.window
	var retired *segment
	if len(s.retired) > 0 {
		retired = s.retired[0]
	}
	if retired == nil {
		s.mu.Unlock()
		t.Fatalf("the depth sweep retired nothing")
	}
	for _, seg := range s.segs {
		seg.pending = false
	}
	for _, seg := range s.retired {
		seg.pending = false
	}
	retired.pending = true
	w.pending = 1
	w.queue = []*segment{retired}
	s.mu.Unlock()
	g.clock.Advance(time.Hour)
	jobs, _, _ := g.r.collect(w)
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, job := range jobs {
		if job.seg == retired {
			t.Errorf("the retired segment is still queued for a write")
		}
	}
	if w.pending != 0 || retired.held {
		t.Errorf("pending = %d, held = %t: the dropped segment was not released", w.pending, retired.held)
	}
}

// A Rewind needs no configuration: the production root, a random boot id and
// the OS disk, and building one touches nothing.
func TestANewRewindNeedsNoConfiguration(t *testing.T) {
	r := NewRewind(RewindConfig{})
	t.Cleanup(r.Close)
	if got, want := filepath.Dir(r.BootDir()), DefaultRewindRoot; got != want {
		t.Fatalf("the boot directory is under %s, want %s", got, want)
	}
	if !regexp.MustCompile(`^[0-9a-f]{16}$`).MatchString(filepath.Base(r.BootDir())) {
		t.Fatalf("the boot id %q is not 16 hex characters", filepath.Base(r.BootDir()))
	}
	other := NewRewind(RewindConfig{})
	t.Cleanup(other.Close)
	if other.BootDir() == r.BootDir() {
		t.Fatalf("two boots share the id %s", filepath.Base(r.BootDir()))
	}
	if r.Cap() != math.MaxInt64 || r.Bytes() != 0 {
		t.Fatalf("a fresh store has cap %d and %d bytes, want unlimited and none", r.Cap(), r.Bytes())
	}
}

// heldRetiredPending builds a window, with no writer, whose oldest retired
// segment is still queued for the disk: what the cap, a degradation and a late
// write each have to handle.
func heldRetiredPending(t *testing.T, g *rewindRig) (*Store, *window, *segment) {
	t.Helper()
	g.r.Close()
	s := g.store("chan", 10*time.Second)
	for i := 0; i < StoreSegments+3; i++ {
		s.mu.Lock()
		s.window.pending, s.window.queue = 0, nil
		s.mu.Unlock()
		pub(s, 0, t0.Add(time.Duration(i)*4*time.Second), 32)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.retired) == 0 {
		t.Fatalf("the depth sweep retired nothing")
	}
	for _, seg := range s.segs {
		seg.pending = false
	}
	for _, seg := range s.retired {
		seg.pending = false
	}
	retired := s.retired[0]
	retired.pending = true
	s.window.pending = 1
	s.window.queue = []*segment{retired}
	return s, s.window, retired
}

// A degradation drops a retired segment that was still queued, releasing its
// bytes: the disk will never hold it.
func TestADegradationDropsAQueuedRetiredSegment(t *testing.T) {
	g := newRewindRig(t)
	s, w, retired := heldRetiredPending(t, g)
	g.r.degrade(w, errors.New("boom"), "")
	s.mu.Lock()
	defer s.mu.Unlock()
	if slices.Contains(s.retired, retired) || retired.held || retired.pending {
		t.Fatalf("the queued retired segment survived the degradation: listed %t, held %t, pending %t",
			slices.Contains(s.retired, retired), retired.held, retired.pending)
	}
}

// A retired segment whose write lands after its retirement is on disk and gives
// its data up.
func TestALateWriteOfARetiredSegmentReleasesItsData(t *testing.T) {
	g := newRewindRig(t)
	s, w, retired := heldRetiredPending(t, g)
	g.r.commit(w, retired, 0)
	s.mu.Lock()
	defer s.mu.Unlock()
	if !retired.onDisk || retired.held || retired.pending || w.pending != 0 {
		t.Fatalf("after its late write: onDisk %t, held %t, pending %t, w.pending %d; want on disk, released, settled",
			retired.onDisk, retired.held, retired.pending, w.pending)
	}
}

func TestAnUnlinkFailureIsLoggedAtDebugAndNotFatal(t *testing.T) {
	g := newRewindRig(t)
	g.fs.fail = func(op string, _ int) error {
		if op == "Remove" {
			return syscall.EBUSY
		}
		return nil
	}
	g.r.unlink("/nowhere/1.m4s")
	if !strings.Contains(g.log.String(), "could not remove a rewind segment") {
		t.Fatalf("a failed unlink was not logged:\n%s", g.log.String())
	}
	g.fs.fail = func(op string, _ int) error {
		if op == "Remove" {
			return fs.ErrNotExist
		}
		return nil
	}
	before := len(g.log.String())
	g.r.unlink("/nowhere/2.m4s")
	if len(g.log.String()) != before {
		t.Fatalf("an unlink of a file already gone was logged:\n%s", g.log.String()[before:])
	}
}

func TestAFailedWindowRemovalIsLoggedAndForgotten(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, 2, t0, 64)
	g.fs.fail = func(op string, _ int) error {
		if op == "RemoveAll" {
			return syscall.EBUSY
		}
		return nil
	}
	s.Close()
	g.sync()
	if !strings.Contains(g.log.String(), "could not remove a rewind window") {
		t.Fatalf("a failed removal was not logged:\n%s", g.log.String())
	}
	g.r.mu.Lock()
	windows := len(g.r.windows)
	g.r.mu.Unlock()
	if windows != 0 || g.r.Bytes() != 0 {
		t.Fatalf("the window is still accounted after its removal: %d windows, %d bytes", windows, g.r.Bytes())
	}
}

// evict re-checks its victim under the lock: one that moved since it was picked
// is left alone, and a listed head that carried a discontinuity counts it.
func TestEvictLeavesAVictimThatMovedAndCountsADiscontinuity(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, StoreSegments+1, t0, 64)
	s.mu.Lock()
	w, head := s.window, s.segs[0]
	s.mu.Unlock()

	stale := &segment{seq: 5000, onDisk: true, parts: map[string]part{RenditionVideo: {}}}
	if paths := g.r.evict(victim{w: w, seg: stale, tier: 1, retired: true}); paths != nil {
		t.Fatalf("evicting a retired victim that is not listed removed %v", paths)
	}
	if paths := g.r.evict(victim{w: w, seg: stale, tier: 3}); paths != nil {
		t.Fatalf("evicting a head that is not the head removed %v", paths)
	}
	s.mu.Lock()
	head.discontinuity = true
	before := s.discontinuitiesGone
	s.mu.Unlock()
	if paths := g.r.evict(victim{w: w, seg: head, tier: 3}); len(paths) != 1 {
		t.Fatalf("evicting the head answered %v, want its one file", paths)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.discontinuitiesGone != before+1 {
		t.Fatalf("discontinuitiesGone = %d, want %d: a discontinuity that left was not counted", s.discontinuitiesGone, before+1)
	}
}

// The byte ceiling gives an on-disk segment's data up before it retires one,
// and retires the head when nothing is on disk.
func TestTheByteCeilingReleasesADiskSegmentBeforeItRetiresAnything(t *testing.T) {
	const big = 20 << 20
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, 4, t0, big) // 80 MiB against the 64 MiB ceiling: all written, so one gives its data up
	s.mu.Lock()
	held := 0
	for _, seg := range s.segs {
		if seg.held {
			held++
		}
	}
	listed := len(s.segs)
	s.mu.Unlock()
	if held != 3 || listed != 4 {
		t.Fatalf("with every segment on disk %d of %d held their data, want 3 of 4 and none retired", held, listed)
	}

	// Queued segments are never retired for their bytes: nothing is freed by it,
	// and once the writer has written them the same rule releases their data.
	h := newRewindRig(t)
	h.fs.gate = make(chan struct{})
	release := sync.OnceFunc(func() { close(h.fs.gate) })
	t.Cleanup(release)
	p := h.store("chan", time.Hour)
	for i := 0; i < 4; i++ {
		pub(p, 0, t0.Add(time.Duration(i)*2*time.Second), big)
	}
	p.mu.Lock()
	kept, retired := len(p.segs), len(p.retired)
	p.mu.Unlock()
	if kept != 4 || retired != 0 {
		t.Fatalf("with every segment queued the ceiling left %d listed and %d retired, want all 4 listed", kept, retired)
	}
	release()
	if err := p.WaitDurable(testCtx(t), 3); err != nil {
		t.Fatal(err)
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if held := p.heldLocked(); held != 3 {
		t.Fatalf("after the writer caught up %d segments held their data, want 3", held)
	}
}

// A window degrades once: a second failure neither logs again nor re-drops what
// is already dropped.
func TestAWindowDegradesOnce(t *testing.T) {
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	g.r.degrade(s.window, errors.New("first"), "")
	g.r.degrade(s.window, errors.New("second"), "the writer queue is full")
	if n := strings.Count(g.log.String(), "stopped persisting"); n != 1 {
		t.Fatalf("two failures logged %d degradations, want one:\n%s", n, g.log.String())
	}
}

// Queued segments past the byte ceiling never cost the window its on-disk
// history: retiring listed segments frees nothing while every held byte is queued.
func TestQueuedSegmentsPastTheCeilingKeepTheDurableWindow(t *testing.T) {
	const big = 20 << 20
	g := newRewindRig(t)
	s := g.store("chan", time.Hour)
	publishDurable(t, s, 0, 25, t0, 64)
	g.fs.gate = make(chan struct{})
	t.Cleanup(func() { close(g.fs.gate) })
	for i := 25; i < 29; i++ {
		pub(s, 0, t0.Add(time.Duration(i)*2*time.Second), big)
	}
	if first, listed := mediaSequence(t, s); first != 0 || listed != 29 {
		t.Fatalf("the playlist lists %d from %d after queued segments passed the ceiling, want 29 from 0", listed, first)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.retired) != 0 {
		t.Fatalf("%d segments were retired for bytes that retiring cannot free", len(s.retired))
	}
}
