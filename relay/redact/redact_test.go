package redact

import (
	"errors"
	"fmt"
	"net/url"
	"strings"
	"testing"
)

// The credential is in the PATH and the QUERY, not the userinfo: net/url's
// own String() already masks userinfo, so a test whose secret lived there
// would pass against an unredacted error and prove nothing.
const secretURL = "http://provider.example:8080/live/subscriber/hunter2/9.ts?token=s3cr3t"

func TestErrorStripsTheURLOutOfAURLError(t *testing.T) {
	inner := errors.New("dial tcp 127.0.0.1:1: connect: connection refused")
	err := Error(&url.Error{Op: "Get", URL: secretURL, Err: inner})
	for _, secret := range []string{"hunter2", "s3cr3t", "/live/subscriber"} {
		if strings.Contains(err.Error(), secret) {
			t.Fatalf("the redacted error still carries %q: %s", secret, err)
		}
	}
	if !errors.Is(err, inner) {
		t.Fatalf("the transport's own reason was lost: %v", err)
	}
}

// A wrapped *url.Error is found through the chain, which is what makes the
// function safe to apply to an error that has already been annotated once.
func TestErrorFindsAURLErrorThroughAWrap(t *testing.T) {
	wrapped := fmt.Errorf("connecting: %w", &url.Error{Op: "Get", URL: secretURL, Err: errors.New("refused")})
	if got := Error(wrapped).Error(); strings.Contains(got, "hunter2") {
		t.Fatalf("the wrapped URL survived: %s", got)
	}
}

func TestErrorLeavesAnOrdinaryErrorAlone(t *testing.T) {
	plain := errors.New("exit status 1")
	// Identity is the assertion -- the same error value comes back, not a
	// wrap of it -- so errors.Is would pass against exactly the wrapping
	// this test forbids.
	if got := Error(plain); got != plain { //nolint:errorlint // identity, not equivalence, is the claim
		t.Fatalf("an error with no URL was replaced: %v", got)
	}
	if got := Error(nil); got != nil {
		t.Fatalf("Error(nil) = %v, want nil", got)
	}
}

func TestLineKeepsTheHostAndDropsEverythingElse(t *testing.T) {
	for _, tc := range []struct{ in, want string }{
		{
			// ffmpeg's own preamble line, quoted.
			"Input #0, mpegts, from '" + secretURL + "':",
			"Input #0, mpegts, from 'http://provider.example:8080/[redacted]':",
		},
		{
			// userinfo, path and query all go; only the host stays.
			"opening http://user:pw@host/live/u/p/1.ts?password=x for reading",
			"opening http://host/[redacted] for reading",
		},
		{
			// An HLS segment URL derived from the provider URL: not the exact
			// string the relay was given, still a credentialled path.
			"[hls @ 0x1] Opening 'https://cdn.example/live/subscriber/hunter2/seg-3.ts' for reading",
			"[hls @ 0x1] Opening 'https://cdn.example/[redacted]' for reading",
		},
		{
			// Two URLs on one line, both replaced.
			"a http://one.example/x/y b udp://239.0.0.1:1234?fifo_size=1 c",
			"a http://one.example/[redacted] b udp://239.0.0.1:1234/[redacted] c",
		},
		{
			// No URL, no change.
			"frame=  150 fps=0.0 q=-1.0 size=352KiB time=00:00:05.85 bitrate= 492.2kbits/s speed=11.5x",
			"frame=  150 fps=0.0 q=-1.0 size=352KiB time=00:00:05.85 bitrate= 492.2kbits/s speed=11.5x",
		},
		{
			// A scheme with no authority keeps the scheme only.
			"reading file:///etc/passwd",
			"reading file://[redacted]",
		},
	} {
		if got := Line(tc.in); got != tc.want {
			t.Errorf("Line(%q)\n got %q\nwant %q", tc.in, got, tc.want)
		}
	}
}

// The property the whole package exists for, asserted directly: after Line,
// none of the secret's parts survive, for every spelling of URL the corpus
// and the M3U transform produce.
func TestLineNeverLeavesACredentialBehind(t *testing.T) {
	for _, in := range []string{
		secretURL,
		"http://user:hunter2@host/stream.ts",
		"http://host/get.php?username=subscriber&password=hunter2&type=m3u",
		"rtsp://user:hunter2@cam.example:554/live",
		"'" + secretURL + "'",
		"prefix " + secretURL + " suffix",
	} {
		got := Line(in)
		for _, secret := range []string{"hunter2", "s3cr3t", "subscriber", "password"} {
			if strings.Contains(got, secret) {
				t.Errorf("Line(%q) = %q still carries %q", in, got, secret)
			}
		}
	}
}
