package hls

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io/fs"
	"log/slog"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// DefaultRewindRoot is where the rewind windows live (spec D14);
// docker/init/03-init-dispatcharr.sh creates it.
const DefaultRewindRoot = "/data/cache/rewind"

// FS is the disk as the rewind store uses it: OSFS in production, a
// fault-injecting one in tests (spec: "Tests inject the writer").
type FS interface {
	MkdirAll(dir string) error                // 0o755
	WriteFile(name string, data []byte) error // create or truncate, 0o644
	Rename(from, to string) error
	ReadFile(name string) ([]byte, error)
	Remove(name string) error
	RemoveAll(dir string) error
	ReadDir(dir string) ([]string, error) // entry names
}

// OSFS is FS over package os.
type OSFS struct{}

// MkdirAll creates dir and its parents.
func (OSFS) MkdirAll(dir string) error {
	return os.MkdirAll(dir, 0o755) //nolint:gosec // the window is the relay's own cache, read by the same user; 0o755 is the layout the container's init script gives /data/cache
}

// WriteFile creates or truncates name.
func (OSFS) WriteFile(name string, data []byte) error {
	return os.WriteFile(name, data, 0o644) //nolint:gosec // as MkdirAll: a cache file of the relay's own
}

// Rename moves a file.
func (OSFS) Rename(from, to string) error { return os.Rename(from, to) }

// ReadFile reads a whole file.
func (OSFS) ReadFile(name string) ([]byte, error) {
	return os.ReadFile(name) //nolint:gosec // name is always a path the store built under its own boot directory
}

// Remove unlinks a file.
func (OSFS) Remove(name string) error { return os.Remove(name) }

// RemoveAll removes a tree.
func (OSFS) RemoveAll(dir string) error { return os.RemoveAll(dir) }

// ReadDir lists a directory's entry names.
func (OSFS) ReadDir(dir string) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	names := make([]string, len(entries))
	for i, e := range entries {
		names[i] = e.Name()
	}
	return names, nil
}

// RewindConfig is a Rewind's configuration.
type RewindConfig struct {
	Root   string       // DefaultRewindRoot when empty
	FS     FS           // OSFS{} when nil
	Log    *slog.Logger // slog.Default() when nil
	BootID string       // tests only; 16 random hex characters when empty
}

// Rewind is the process-wide on-disk rewind store (spec D14): one boot
// directory, one writer goroutine that does every disk operation for every
// window, and the cap across every window. The windows' bytes stay in memory
// until written, so a slow disk loses nothing; a disk failure degrades a
// window and never the output (4a-3, § The design).
type Rewind struct {
	root, bootID, bootDir string
	fs                    FS
	log                   *slog.Logger
	// joinWait bounds RemoveBoot's and Close's wait for the writer.
	joinWait time.Duration

	kick     chan struct{}
	stop     chan struct{}
	exited   chan struct{}
	stopOnce sync.Once

	mu       sync.Mutex
	windows  map[*window]struct{}
	capBytes int64
	// started and done count batches; batchDone is closed at each batch's end.
	started, done uint64
	batchDone     chan struct{}

	total   atomic.Int64
	nextRun atomic.Uint64
	// bootReady and capWarned belong to the writer goroutine.
	bootReady bool
	capWarned bool
}

// NewRewind builds the store and starts its writer. It never fails and never
// touches the disk: the boot directory is made by the writer, on first use.
func NewRewind(cfg RewindConfig) *Rewind {
	root := cfg.Root
	if root == "" {
		root = DefaultRewindRoot
	}
	var fsys FS = OSFS{}
	if cfg.FS != nil {
		fsys = cfg.FS
	}
	log := cfg.Log
	if log == nil {
		log = slog.Default()
	}
	boot := cfg.BootID
	if boot == "" {
		var b [8]byte
		// crypto/rand.Read never returns an error (Go 1.24).
		_, _ = rand.Read(b[:])
		boot = hex.EncodeToString(b[:])
	}
	r := &Rewind{
		root:      root,
		bootID:    boot,
		bootDir:   filepath.Join(root, boot),
		fs:        fsys,
		log:       log,
		joinWait:  stopJoinWait,
		kick:      make(chan struct{}, 1),
		stop:      make(chan struct{}),
		exited:    make(chan struct{}),
		windows:   map[*window]struct{}{},
		capBytes:  math.MaxInt64,
		batchDone: make(chan struct{}),
	}
	go r.loop()
	return r
}

// BootDir is this boot's directory.
func (r *Rewind) BootDir() string { return r.bootDir }

// wake asks the writer for a batch. It never blocks.
func (r *Rewind) wake() {
	select {
	case r.kick <- struct{}{}:
	default:
	}
}

// SetCap sets the process-wide disk cap in bytes. A value <= 0 is ignored.
func (r *Rewind) SetCap(bytes int64) {
	if bytes <= 0 {
		return
	}
	r.mu.Lock()
	r.capBytes = bytes
	r.mu.Unlock()
	r.wake()
}

// Cap is the disk cap in bytes; math.MaxInt64 until a tune has set it.
func (r *Rewind) Cap() int64 {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.capBytes
}

// Bytes is what is on disk now, as accounted.
func (r *Rewind) Bytes() int64 { return r.total.Load() }

// CleanStale removes every entry under the root but this boot's directory: the
// windows of an earlier boot are lost by design and never read (R10). A failure
// is logged once.
func (r *Rewind) CleanStale() {
	names, err := r.fs.ReadDir(r.root)
	if err != nil {
		if !errors.Is(err, fs.ErrNotExist) {
			r.log.Warn("could not list the rewind directory", "error", redact.Error(err))
		}
		return
	}
	warned := false
	for _, name := range names {
		if name == r.bootID {
			continue
		}
		if err := r.fs.RemoveAll(filepath.Join(r.root, name)); err != nil && !warned {
			warned = true
			r.log.Warn("could not remove a stale rewind directory", "error", redact.Error(err))
		}
	}
}

// RemoveBoot is the drain's step: it stops the writer, waiting at most
// stopJoinWait, then removes this boot's directory, best effort.
func (r *Rewind) RemoveBoot() {
	r.Close()
	if err := r.fs.RemoveAll(r.bootDir); err != nil {
		r.log.Warn("could not remove the rewind directory", "error", redact.Error(err))
	}
}

// Close stops the writer, waiting at most stopJoinWait.
func (r *Rewind) Close() {
	r.stopOnce.Do(func() { close(r.stop) })
	select {
	case <-r.exited:
	case <-time.After(r.joinWait):
		r.log.Warn("the rewind writer did not stop in time")
	}
}

// Sync kicks the writer and waits until a batch that STARTED after the call has
// completed (writes, unlinks and evictions included), or ctx ends. For tests:
// every test that observes the writer's effects waits on it, never on a count
// or a sleep.
func (r *Rewind) Sync(ctx context.Context) error {
	r.mu.Lock()
	target := r.started + 1
	r.mu.Unlock()
	r.wake()
	for {
		r.mu.Lock()
		if r.done >= target {
			r.mu.Unlock()
			return nil
		}
		ch := r.batchDone
		r.mu.Unlock()
		select {
		case <-ch:
		case <-ctx.Done():
			return ctx.Err()
		case <-r.exited:
			return errors.New("hls: the rewind writer has stopped")
		}
	}
}

var safeChannel = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

// channelDir is a channel's directory name: its id when that is safe as one,
// else x and the first 16 hex characters of its SHA-256.
func channelDir(id string) string {
	if safeChannel.MatchString(id) {
		return id
	}
	sum := sha256.Sum256([]byte(id))
	return "x" + hex.EncodeToString(sum[:])[:16]
}

// window is one pipeline's rewind window. Its fields, but for lingering and
// the writer-owned maps, belong to its store's mutex.
type window struct {
	r       *Rewind
	s       *Store
	channel string
	run     uint64
	runDir  string
	depth   time.Duration

	queue     []*segment
	pending   int
	unlinks   []string
	pins      int
	diskBytes int64
	degraded  bool
	closed    bool
	removing  bool
	lingering atomic.Bool

	// wroteInit and dirs are the writer's alone.
	wroteInit map[initKey]bool
	dirs      map[string]bool
}

// open gives store a window under this boot. It does no disk I/O: the writer
// makes the directories, so the caller may hold a lock.
func (r *Rewind) open(channelID string, depth time.Duration, store *Store) *window {
	run := r.nextRun.Add(1)
	w := &window{
		r:         r,
		s:         store,
		channel:   channelID,
		run:       run,
		runDir:    filepath.Join(r.bootDir, channelDir(channelID), strconv.FormatUint(run, 10)),
		depth:     depth,
		wroteInit: map[initKey]bool{},
		dirs:      map[string]bool{},
	}
	store.mu.Lock()
	store.window = w
	store.mu.Unlock()
	r.mu.Lock()
	r.windows[w] = struct{}{}
	r.mu.Unlock()
	return w
}

// segPath is one rendition part's file.
func (w *window) segPath(gen int, rendition string, seq uint64) string {
	return filepath.Join(w.runDir, strconv.Itoa(gen), rendition, strconv.FormatUint(seq, 10)+".m4s")
}

// segPaths is every file of a segment.
func (w *window) segPaths(seg *segment) []string {
	paths := make([]string, 0, len(seg.parts))
	for name := range seg.parts {
		paths = append(paths, w.segPath(seg.gen, name, seg.seq))
	}
	slices.Sort(paths)
	return paths
}

// degradation is what a window's first failure logs, after its store's lock is
// released.
type degradation struct {
	w   *window
	err error
	why string
}

// warn logs the degradation, once per window. A nil receiver does nothing.
func (d *degradation) warn() {
	if d == nil {
		return
	}
	attrs := []any{"channel", d.w.channel, "run", d.w.run}
	if d.err != nil {
		attrs = append(attrs, "error", redact.Error(d.err))
	}
	if d.why != "" {
		attrs = append(attrs, "reason", d.why)
	}
	d.w.r.log.Warn("the rewind window stopped persisting; the live edge is unaffected", attrs...)
}

// degradeLocked stops a window persisting for the rest of its run: its pending
// segments become non-durable, its queue is dropped, and the playlist shrinks to
// the live edge as they age out. It answers the degradation to log, or nil when
// the window had already degraded.
func (s *Store) degradeLocked(w *window, err error, why string) *degradation {
	if w.degraded {
		return nil
	}
	w.degraded = true
	for _, seg := range s.segs {
		seg.pending = false
	}
	kept := s.retired[:0]
	for _, seg := range s.retired {
		if seg.pending {
			seg.pending = false
			s.releaseLocked(seg)
			continue
		}
		kept = append(kept, seg)
	}
	s.retired = kept
	w.pending, w.queue = 0, nil
	s.trimLocked()
	s.notifyLocked()
	return &degradation{w: w, err: err, why: why}
}

// degrade is degradeLocked for the writer, which holds no lock.
func (r *Rewind) degrade(w *window, err error, why string) {
	w.s.mu.Lock()
	d := w.s.degradeLocked(w, err, why)
	w.s.mu.Unlock()
	d.warn()
}

func (r *Rewind) loop() {
	defer close(r.exited)
	for {
		select {
		case <-r.stop:
			return
		case <-r.kick:
			r.work()
		}
	}
}

// writeJob is one queued segment as the writer sees it: the bytes to write
// under each rendition, with the generation's init where none is on disk yet.
type writeJob struct {
	seg   *segment
	parts []jobPart
}

type jobPart struct {
	rendition string
	data      []byte
	init      []byte
	key       initKey
}

// work is one batch: for every window its retirements, removal, writes and
// unlinks, then the cap.
func (r *Rewind) work() {
	r.mu.Lock()
	r.started++
	windows := make([]*window, 0, len(r.windows))
	for w := range r.windows {
		windows = append(windows, w)
	}
	r.mu.Unlock()
	for _, w := range windows {
		jobs, unlinks, remove := r.collect(w)
		if remove {
			r.removeWindow(w)
			continue
		}
		if len(jobs) > 0 {
			r.writeAll(w, jobs)
		}
		for _, path := range unlinks {
			r.unlink(path)
		}
	}
	r.enforceCap()
	r.mu.Lock()
	r.done++
	close(r.batchDone)
	r.batchDone = make(chan struct{})
	r.mu.Unlock()
}

func (r *Rewind) unlink(path string) {
	if err := r.fs.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
		r.log.Debug("could not remove a rewind segment", "error", redact.Error(err))
	}
}

// collect takes, under the window's store lock, what the batch must do for it:
// the segments to write, the files to unlink (queued ones, and retired ones
// whose retention has passed and which no read holds), and whether the window
// is to be removed, which it is marked for in the same critical section, after
// which no disk read of it starts.
func (r *Rewind) collect(w *window) (jobs []writeJob, unlinks []string, remove bool) {
	s := w.s
	s.mu.Lock()
	defer s.mu.Unlock()
	now, retention := s.now(), s.unlistedRetentionLocked()
	kept := s.retired[:0]
	changed := false
	for _, seg := range s.retired {
		if now.Sub(seg.retiredAt) < retention || seg.readers > 0 {
			kept = append(kept, seg)
			continue
		}
		changed = true
		if seg.pending {
			seg.pending = false
			w.pending--
			w.queue = slices.DeleteFunc(w.queue, func(q *segment) bool { return q == seg })
			s.releaseLocked(seg)
		} else if seg.onDisk {
			seg.onDisk = false
			w.diskBytes -= int64(seg.bytes)
			r.total.Add(-int64(seg.bytes))
			unlinks = append(unlinks, w.segPaths(seg)...)
		}
	}
	s.retired = kept
	if changed {
		s.notifyLocked()
	}
	unlinks = append(unlinks, w.unlinks...)
	w.unlinks = nil
	if w.closed && w.pins == 0 {
		w.removing = true
		return nil, nil, true
	}
	if w.degraded {
		return nil, unlinks, false
	}
	planned := map[initKey]bool{}
	for _, seg := range w.queue {
		job := writeJob{seg: seg}
		names := make([]string, 0, len(seg.parts))
		for name := range seg.parts {
			names = append(names, name)
		}
		slices.Sort(names)
		for _, name := range names {
			part := jobPart{rendition: name, data: seg.parts[name].data, key: initKey{name, seg.gen}}
			if !w.wroteInit[part.key] && !planned[part.key] {
				part.init = s.inits[part.key]
				planned[part.key] = part.init != nil
			}
			job.parts = append(job.parts, part)
		}
		jobs = append(jobs, job)
	}
	w.queue = nil
	return jobs, unlinks, false
}

// removeWindow deletes a stopped window's run directory and forgets it.
func (r *Rewind) removeWindow(w *window) {
	if err := r.fs.RemoveAll(w.runDir); err != nil {
		r.log.Warn("could not remove a rewind window", "channel", w.channel, "run", w.run, "error", redact.Error(err))
	}
	w.s.mu.Lock()
	bytes := w.diskBytes
	w.diskBytes = 0
	w.s.mu.Unlock()
	r.total.Add(-bytes)
	r.mu.Lock()
	delete(r.windows, w)
	r.mu.Unlock()
}

// writeAll writes a window's jobs in order. The first error degrades the window
// and ends its batch.
func (r *Rewind) writeAll(w *window, jobs []writeJob) {
	if !r.bootReady {
		if err := r.fs.MkdirAll(r.bootDir); err != nil {
			r.degrade(w, err, "")
			return
		}
		r.bootReady = true
	}
	for _, job := range jobs {
		initBytes, err := r.writeJob(w, job)
		if err != nil {
			r.degrade(w, err, "")
			return
		}
		r.commit(w, job.seg, initBytes)
	}
}

// writeJob writes one segment's files, each under a temporary name and then
// renamed into place (R85), and answers the bytes of init segments it wrote.
func (r *Rewind) writeJob(w *window, job writeJob) (initBytes int64, err error) {
	for _, part := range job.parts {
		dir := filepath.Join(w.runDir, strconv.Itoa(job.seg.gen), part.rendition)
		if !w.dirs[dir] {
			if err := r.fs.MkdirAll(dir); err != nil {
				return initBytes, err
			}
			w.dirs[dir] = true
		}
		if part.init != nil {
			if err := r.put(filepath.Join(dir, "init.mp4"), part.init); err != nil {
				return initBytes, err
			}
			w.wroteInit[part.key] = true
			initBytes += int64(len(part.init))
		}
		if err := r.put(w.segPath(job.seg.gen, part.rendition, job.seg.seq), part.data); err != nil {
			return initBytes, err
		}
	}
	return initBytes, nil
}

// put writes a file under a temporary name and renames it into place.
func (r *Rewind) put(name string, data []byte) error {
	tmp := name + ".tmp"
	if err := r.fs.WriteFile(tmp, data); err != nil {
		return err
	}
	return r.fs.Rename(tmp, name)
}

// commit records a written segment. A window that degraded meanwhile ignores
// the result (its files go with the run directory); a segment that has left
// the store is not counted and its files are queued for unlink at once, so no
// orphan is ever counted against the cap.
func (r *Rewind) commit(w *window, seg *segment, initBytes int64) {
	s := w.s
	s.mu.Lock()
	defer s.mu.Unlock()
	if w.degraded {
		return
	}
	w.diskBytes += initBytes
	r.total.Add(initBytes)
	listed := false
	if n := len(s.segs); n > 0 && seg.seq >= s.segs[0].seq && seg.seq <= s.segs[n-1].seq {
		listed = true
	}
	if !listed && !slices.Contains(s.retired, seg) {
		w.unlinks = append(w.unlinks, w.segPaths(seg)...)
		r.wake()
		return
	}
	seg.pending = false
	w.pending--
	seg.onDisk = true
	w.diskBytes += int64(seg.bytes)
	r.total.Add(int64(seg.bytes))
	if !listed {
		s.releaseLocked(seg)
	}
	s.trimLocked()
	s.notifyLocked()
}

// victim is the segment the cap will evict next.
type victim struct {
	w       *window
	seg     *segment
	tier    int
	retired bool
}

// enforceCap evicts until the disk is within the cap: retired segments of any
// window, oldest first; then the oldest listed segment of a lingering window;
// then the oldest listed segment of any window. Only segments outside a window's
// newest StoreSegments are ever evicted, and only those on disk. If nothing is
// evictable it logs once until the cap has been met again.
func (r *Rewind) enforceCap() {
	limit := r.Cap()
	for r.total.Load() > limit {
		v, ok := r.pickVictim()
		if !ok {
			if !r.capWarned {
				r.capWarned = true
				r.log.Warn("the rewind disk cap cannot be met: only in-memory segments are left to evict", "bytes", r.total.Load(), "cap", limit)
			}
			return
		}
		for _, path := range r.evict(v) {
			r.unlink(path)
		}
	}
	r.capWarned = false
}

// pickVictim chooses the next eviction, each window peeked under its own store
// lock, never two at once.
func (r *Rewind) pickVictim() (victim, bool) {
	r.mu.Lock()
	windows := make([]*window, 0, len(r.windows))
	for w := range r.windows {
		windows = append(windows, w)
	}
	r.mu.Unlock()
	var best victim
	found := false
	consider := func(v victim) {
		if !found || v.tier < best.tier || (v.tier == best.tier && v.seg.pdt.Before(best.seg.pdt)) {
			best, found = v, true
		}
	}
	for _, w := range windows {
		w.s.mu.Lock()
		for _, seg := range w.s.retired {
			if seg.onDisk {
				consider(victim{w: w, seg: seg, tier: 1, retired: true})
				break
			}
		}
		if segs := w.s.segs; len(segs) > StoreSegments && segs[0].onDisk {
			tier := 3
			if w.lingering.Load() {
				tier = 2
			}
			consider(victim{w: w, seg: segs[0], tier: tier})
		}
		w.s.mu.Unlock()
	}
	return best, found
}

// evict takes v out of its window's lists and accounting under the store lock,
// and answers the files to unlink, which the caller removes with no lock held.
// A victim under a read in flight is doomed instead: its files go when the last
// read ends. A victim that moved since it was picked is left, and the caller's
// next pick sees the new state.
func (r *Rewind) evict(v victim) []string {
	w, s := v.w, v.w.s
	s.mu.Lock()
	defer s.mu.Unlock()
	if v.retired {
		i := slices.Index(s.retired, v.seg)
		if i < 0 {
			return nil
		}
		s.retired = slices.Delete(s.retired, i, i+1)
	} else {
		if len(s.segs) <= StoreSegments || s.segs[0] != v.seg {
			return nil
		}
		s.segs[0] = nil
		s.segs = s.segs[1:]
		if v.seg.discontinuity {
			s.discontinuitiesGone++
		}
	}
	v.seg.onDisk = false
	w.diskBytes -= int64(v.seg.bytes)
	r.total.Add(-int64(v.seg.bytes))
	s.notifyLocked()
	if v.seg.readers > 0 {
		v.seg.doomed = true
		return nil
	}
	return w.segPaths(v.seg)
}
