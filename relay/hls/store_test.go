package hls

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"testing"
	"time"
)

var t0 = time.Date(2026, 9, 27, 12, 0, 0, 0, time.UTC)

func publishN(s *Store, gen, n int, from time.Time) {
	for i := 0; i < n; i++ {
		s.publish(gen, from.Add(time.Duration(i)*2*time.Second), map[string]part{
			RenditionVideo: {data: []byte(fmt.Sprintf("v%d", i)), duration: 2},
			RenditionAAC:   {data: []byte(fmt.Sprintf("a%d", i)), duration: 1.984},
		})
	}
}

// D7 / spec § Playlists: the media playlist's tags, the live edge of 10, a
// map per generation, a discontinuity before every later generation's first
// segment, PDT on every segment, and no ENDLIST.
func TestTheMediaPlaylist(t *testing.T) {
	clock := t0
	s := NewStore(func() time.Time { return clock })
	if _, _, ok := s.MediaPlaylist(RenditionVideo); ok {
		t.Fatalf("an empty store rendered a playlist")
	}
	publishN(s, 0, 4, t0)
	publishN(s, 1, 3, t0.Add(10*time.Second))
	clock = t0.Add(time.Minute)
	publishN(s, 2, 1, t0.Add(20*time.Second))
	got, modified, ok := s.MediaPlaylist(RenditionVideo)
	if !ok {
		t.Fatalf("no playlist")
	}
	want := `#EXTM3U
#EXT-X-VERSION:7
#EXT-X-TARGETDURATION:2
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-DISCONTINUITY-SEQUENCE:0
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-MAP:URI="video/init-0.mp4"
#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:00.000Z
#EXTINF:2.000,
video/0.m4s
#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:02.000Z
#EXTINF:2.000,
video/1.m4s
#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:04.000Z
#EXTINF:2.000,
video/2.m4s
#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:06.000Z
#EXTINF:2.000,
video/3.m4s
#EXT-X-DISCONTINUITY
#EXT-X-MAP:URI="video/init-1.mp4"
#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:10.000Z
#EXTINF:2.000,
video/4.m4s
#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:12.000Z
#EXTINF:2.000,
video/5.m4s
#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:14.000Z
#EXTINF:2.000,
video/6.m4s
#EXT-X-DISCONTINUITY
#EXT-X-MAP:URI="video/init-2.mp4"
#EXT-X-PROGRAM-DATE-TIME:2026-09-27T12:00:20.000Z
#EXTINF:2.000,
video/7.m4s
`
	if string(got) != want {
		t.Fatalf("media playlist:\n%s\nwant:\n%s", got, want)
	}
	if !modified.Equal(t0.Add(time.Minute)) {
		t.Errorf("Last-Modified = %v, want the newest segment's publish time", modified)
	}
	audio, _, _ := s.MediaPlaylist(RenditionAAC)
	if !strings.Contains(string(audio), "#EXTINF:1.984,\naac/7.m4s\n") || !strings.Contains(string(audio), `#EXT-X-MAP:URI="aac/init-2.mp4"`) {
		t.Errorf("the audio playlist lists its own durations and maps:\n%s", audio)
	}
	if strings.Contains(string(got), "ENDLIST") {
		t.Errorf("a live playlist carries EXT-X-ENDLIST")
	}
}

// A discontinuity that has left the list is counted in
// EXT-X-DISCONTINUITY-SEQUENCE, and one on the first listed segment is still
// written, so a segment's discontinuity sequence never changes between
// reloads.
func TestTheDiscontinuitySequenceCountsWhatLeftTheList(t *testing.T) {
	s := NewStore(nil)
	publishN(s, 0, 2, t0)
	publishN(s, 1, 2, t0)
	publishN(s, 2, 8, t0) // 12 stored; the first two are past the live edge
	got, _, _ := s.MediaPlaylist(RenditionVideo)
	if !strings.Contains(string(got), "#EXT-X-MEDIA-SEQUENCE:2\n#EXT-X-DISCONTINUITY-SEQUENCE:0\n") {
		t.Fatalf("the edge starts on generation 1's first segment, whose discontinuity is still listed:\n%s", got)
	}
	if !strings.HasPrefix(strings.SplitN(string(got), "#EXT-X-INDEPENDENT-SEGMENTS\n", 2)[1], "#EXT-X-DISCONTINUITY\n#EXT-X-MAP:URI=\"video/init-1.mp4\"") {
		t.Errorf("the first listed segment lost its discontinuity:\n%s", got)
	}
	publishN(s, 2, 1, t0) // generation 1's first segment leaves the list
	got, _, _ = s.MediaPlaylist(RenditionVideo)
	if !strings.Contains(string(got), "#EXT-X-MEDIA-SEQUENCE:3\n#EXT-X-DISCONTINUITY-SEQUENCE:1\n") {
		t.Fatalf("a discontinuity that left the list is not counted:\n%s", got)
	}
	publishN(s, 2, 12, t0) // everything but generation 2 leaves the list
	got, _, _ = s.MediaPlaylist(RenditionVideo)
	if !strings.Contains(string(got), "#EXT-X-DISCONTINUITY-SEQUENCE:2\n") {
		t.Fatalf("a discontinuity evicted from the store is not counted:\n%s", got)
	}
}

// The store keeps StoreSegments segments (R44: RFC 8216 § 6.2.2's availability
// past the live edge) and the init segments of the generations they belong to;
// anything else is a 404.
func TestTheStoreIsBoundedAndServesBySequence(t *testing.T) {
	s := NewStore(nil)
	s.SetInit(RenditionVideo, 0, []byte("init0"))
	publishN(s, 0, 1, t0)
	s.SetInit(RenditionVideo, 1, []byte("init1"))
	publishN(s, 1, StoreSegments+1, t0)
	if _, ok := s.Segment(RenditionVideo, 1); ok {
		t.Errorf("segment 1 is still stored past the StoreSegments bound")
	}
	if data, ok := s.Segment(RenditionVideo, 2); !ok || string(data) != "v1" {
		t.Errorf("segment 2 = %q, %t", data, ok)
	}
	if _, ok := s.Segment(RenditionAC3, 5); ok {
		t.Errorf("a rendition the segment lacks was served")
	}
	if _, ok := s.Segment(RenditionVideo, 99); ok {
		t.Errorf("a future sequence number was served")
	}
	if _, ok := s.Init(RenditionVideo, 0); ok {
		t.Errorf("generation 0's init outlived its segments")
	}
	if data, ok := s.Init(RenditionVideo, 1); !ok || string(data) != "init1" {
		t.Errorf("generation 1's init = %q, %t", data, ok)
	}
	big := NewStore(nil)
	for i := 0; i < 3; i++ {
		big.publish(0, t0, map[string]part{RenditionVideo: {data: make([]byte, StoreBytes/2+1)}})
	}
	if _, ok := big.Segment(RenditionVideo, 1); ok {
		t.Errorf("the byte bound kept more than one oversized segment")
	}
	if _, ok := big.Segment(RenditionVideo, 2); !ok {
		t.Errorf("the byte bound dropped the newest segment")
	}
}

func TestWaitSegment(t *testing.T) {
	s := NewStore(nil)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if err := s.WaitSegment(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("an empty store's wait = %v, want the context's end", err)
	}
	done := make(chan error, 1)
	go func() { done <- s.WaitSegment(context.Background()) }()
	time.Sleep(10 * time.Millisecond)
	publishN(s, 0, 1, t0)
	if err := <-done; err != nil {
		t.Errorf("the wait did not end on the first segment: %v", err)
	}
	closed := NewStore(nil)
	go closed.Close()
	if err := closed.WaitSegment(context.Background()); !errors.Is(err, ErrStoreClosed) {
		t.Errorf("a closed store's wait = %v, want ErrStoreClosed", err)
	}
	closed.Close()
}

// Spec § Playlists: one audio group per declared rendition, AAC first,
// CHANNELS the declared layout, LANGUAGE only when the probe had one, and
// one EXT-X-STREAM-INF per group with CODECS from the init segments.
func TestTheMultivariant(t *testing.T) {
	o := Output{Width: 1920, Height: 1080, FrameRate: Rational{50, 1}, GOP: 100, VideoBitrate: 6_000_000, VideoMaxrate: 8_000_000,
		Audio: []Rendition{{Name: "aac", Channels: 2, Language: "eng"}, {Name: "ac3", Channels: 6}, {Name: "eac3", Channels: 6}}}
	codecs := map[string]string{"video": "avc1.64002a", "aac": "mp4a.40.2", "ac3": "ac-3", "eac3": "ec-3"}
	got := string(Multivariant(o, codecs, "/hls/TOKEN"))
	want := `#EXTM3U
#EXT-X-VERSION:7
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",NAME="Stereo",LANGUAGE="eng",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="2",URI="/hls/TOKEN/aac.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="ac3",NAME="Surround",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="6",URI="/hls/TOKEN/ac3.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="eac3",NAME="Surround",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="6",URI="/hls/TOKEN/eac3.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=8160000,AVERAGE-BANDWIDTH=6160000,CODECS="avc1.64002a,mp4a.40.2",RESOLUTION=1920x1080,FRAME-RATE=50.000,AUDIO="aac"
/hls/TOKEN/video.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=8640000,AVERAGE-BANDWIDTH=6640000,CODECS="avc1.64002a,ac-3",RESOLUTION=1920x1080,FRAME-RATE=50.000,AUDIO="ac3"
/hls/TOKEN/video.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=8640000,AVERAGE-BANDWIDTH=6640000,CODECS="avc1.64002a,ec-3",RESOLUTION=1920x1080,FRAME-RATE=50.000,AUDIO="eac3"
/hls/TOKEN/video.m3u8
`
	if got != want {
		t.Fatalf("multivariant:\n%s\nwant:\n%s", got, want)
	}
	fractional := Output{Width: 1280, Height: 720, FrameRate: Rational{60000, 1001}, VideoBitrate: 4_000_000, VideoMaxrate: 5_000_000,
		Audio: []Rendition{{Name: "aac", Channels: 2}}}
	if got := string(Multivariant(fractional, codecs, "")); !strings.Contains(got, "FRAME-RATE=59.940") || !strings.Contains(got, "BANDWIDTH=5160000") {
		t.Errorf("a 59.94 output:\n%s", got)
	}
}

// PR #529 review (thread on store.go:125): every segment a media playlist
// lists is in the store -- the one just served, and the one served a reload
// earlier -- because the store keeps StoreSegments = LiveEdge + 11 (R44), which
// is also RFC 8216 § 6.2.2's availability after removal (a segment's duration
// plus the playlist's):
// TestARemovedSegmentStaysAvailableForItsDurationPlusThePlaylists pins that
// half.
func TestEverySegmentAListedPlaylistNamesIsStored(t *testing.T) {
	s := NewStore(nil)
	s.SetInit(RenditionVideo, 0, []byte("init0"))
	var previous []byte
	for i := 0; i < 3*StoreSegments; i++ {
		publishN(s, 0, 1, t0.Add(time.Duration(i)*2*time.Second))
		current, _, _ := s.MediaPlaylist(RenditionVideo)
		for _, playlist := range [][]byte{previous, current} {
			for _, line := range strings.Split(string(playlist), "\n") {
				if !strings.HasSuffix(line, ".m4s") {
					continue
				}
				var seq uint64
				if _, err := fmt.Sscanf(line, RenditionVideo+"/%d.m4s", &seq); err != nil {
					t.Fatalf("unparsable URI %q: %v", line, err)
				}
				if _, ok := s.Segment(RenditionVideo, seq); !ok {
					t.Fatalf("after %d publishes the store no longer holds segment %d, which a playlist listed one reload ago or now: the store keeps fewer segments than its playlists advertise", i+1, seq)
				}
			}
		}
		previous = current
	}
}

// Row 43, R44: a segment that leaves the 10-segment list is still fetchable for
// its own duration plus the playlist's (RFC 8216 § 6.2.2): 2 s + 20 s, which
// is 11 publications after it leaves.
func TestARemovedSegmentStaysAvailableForItsDurationPlusThePlaylists(t *testing.T) {
	s := NewStore(nil)
	s.SetInit(RenditionVideo, 0, []byte("init0"))
	publishN(s, 0, 1, t0)        // segment 0: the one under test
	publishN(s, 0, LiveEdge, t0) // segments 1..10: segment 10's publication removes segment 0 from the list
	listed, _, _ := s.MediaPlaylist(RenditionVideo)
	if strings.Contains(string(listed), "video/0.m4s") {
		t.Fatalf("segment 0 is still listed once segment %d is published:\n%s", LiveEdge, listed)
	}
	// Available after each of the 10 publications that follow (s+11 .. s+20)...
	for i := 1; i <= 10; i++ {
		publishN(s, 0, 1, t0)
		if _, ok := s.Segment(RenditionVideo, 0); !ok {
			t.Fatalf("segment 0 was evicted after %d publications past its removal from the list: it must stay available for 22 s at 2 s a segment", i)
		}
	}
	// ...and evicted by the 11th (s+21). Both halves, so a store that keeps
	// more than 21 fails too.
	publishN(s, 0, 1, t0)
	if _, ok := s.Segment(RenditionVideo, 0); ok {
		t.Fatalf("segment 0 is still stored 11 publications past its removal from the list: the store keeps more than StoreSegments = %d", StoreSegments)
	}
}

var targetLine = regexp.MustCompile(`#EXT-X-TARGETDURATION:(\d+)`)

func TestTheMediaPlaylistCarriesThePipelinesTargetDuration(t *testing.T) {
	for _, c := range []struct {
		set  int
		want string
	}{{0, "2"}, {6, "6"}, {4, "4"}} {
		store := NewStore(time.Now)
		if c.set != 0 {
			store.SetTargetDuration(c.set)
		}
		store.publish(0, time.Now(), map[string]part{RenditionVideo: {data: []byte{1}, duration: 2}})
		playlist, _, _ := store.MediaPlaylist(RenditionVideo)
		if m := targetLine.FindStringSubmatch(string(playlist)); m == nil || m[1] != c.want {
			t.Errorf("SetTargetDuration(%d): %v in\n%s\nwant %s", c.set, m, playlist, c.want)
		}
	}
}

// The byte ceiling scales with the target: at 6, twenty-one 9 MiB segments
// (189 MiB) are all kept; at the default target the same run keeps only the
// newest 7 (63 MiB, under 64 MiB).
func TestTheByteCeilingScalesWithTheTargetDuration(t *testing.T) {
	publish := func(store *Store) {
		for i := 0; i < 21; i++ {
			store.publish(0, time.Now(), map[string]part{RenditionVideo: {data: make([]byte, 9<<20), duration: 2}})
		}
	}
	scaled := NewStore(time.Now)
	scaled.SetTargetDuration(6)
	publish(scaled)
	if n := len(scaled.segs); n != 21 {
		t.Errorf("at target 6 the store kept %d segments, want all 21", n)
	}
	plain := NewStore(time.Now)
	publish(plain)
	if n := len(plain.segs); n != 7 {
		t.Errorf("at the default target the store kept %d segments, want the newest 7", n)
	}
}
