package control

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"regexp"
	"strings"
	"testing"
)

const mediaSessionTestSecret = "media-session-test-secret"

var mediaSessionShape = regexp.MustCompile(`^v1\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}$`)

func TestAMediaSessionTokenHasTheSpecsShape(t *testing.T) {
	sid, err := NewMediaSessionID()
	if err != nil {
		t.Fatal(err)
	}
	token := MediaSessionToken(mediaSessionTestSecret, sid)
	if len(token) != 69 {
		t.Fatalf("token length %d, want 69: %q", len(token), token)
	}
	if !mediaSessionShape.MatchString(token) {
		t.Fatalf("token %q is not v1.<22>.<43> of base64url characters", token)
	}

	// THE ORACLE IS THE STANDARD LIBRARY, never the code under test: the MAC is
	// recomputed here over the spec's literal message.
	mac := hmac.New(sha256.New, []byte(mediaSessionTestSecret))
	mac.Write([]byte("media-session\nv1\n" + sid))
	want := "v1." + sid + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	if token != want {
		t.Fatalf("token %q, want %q", token, want)
	}

	got, ok := VerifyMediaSession(mediaSessionTestSecret, token)
	if !ok || got != sid {
		t.Fatalf("a genuine token did not verify: sid %q ok %t", got, ok)
	}
}

func TestAMediaSessionTokenIsRefusedWhenForgedOrTampered(t *testing.T) {
	sid, err := NewMediaSessionID()
	if err != nil {
		t.Fatal(err)
	}
	token := MediaSessionToken(mediaSessionTestSecret, sid)
	if _, ok := VerifyMediaSession(mediaSessionTestSecret, token); !ok {
		t.Fatal("the genuine token did not verify")
	}

	parts := strings.Split(token, ".")
	otherSID, err := NewMediaSessionID()
	if err != nil {
		t.Fatal(err)
	}
	flipped := []byte(parts[2])
	if flipped[0] == 'A' {
		flipped[0] = 'B'
	} else {
		flipped[0] = 'A'
	}

	cases := []struct{ name, token string }{
		{"a token whose version is v2", "v2." + parts[1] + "." + parts[2]},
		{"a token whose MAC was tampered", parts[0] + "." + parts[1] + "." + string(flipped)},
		{"another secret's MAC", MediaSessionToken("another-secret", sid)},
		{"a changed sid under the original MAC", parts[0] + "." + otherSID + "." + parts[2]},
		{"a fourth segment", token + ".x"},
		{"a non-ASCII byte in the MAC", parts[0] + "." + parts[1] + "." + parts[2][:42] + "é"},
		{"a padded MAC", parts[0] + "." + parts[1] + "." + parts[2][:42] + "="},
		{"an empty token", ""},
		{"an over-long sid", parts[0] + "." + parts[1] + "A." + parts[2]},
		{"an over-long MAC", parts[0] + "." + parts[1] + "." + parts[2] + "A"},
		{"a short sid", parts[0] + "." + parts[1][:21] + "." + parts[2]},
		{"an empty sid", parts[0] + ".." + parts[2]},
		{"the bare MAC", parts[2]},
	}
	for _, c := range cases {
		if got, ok := VerifyMediaSession(mediaSessionTestSecret, c.token); ok {
			t.Errorf("%s verified (sid %q), want refused", c.name, got)
		}
	}
}

func TestNewMediaSessionIDsAreDistinctAnd128Bit(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 1000; i++ {
		sid, err := NewMediaSessionID()
		if err != nil {
			t.Fatal(err)
		}
		raw, err := base64.RawURLEncoding.DecodeString(sid)
		if err != nil || len(raw) != 16 {
			t.Fatalf("sid %q decodes to %d bytes, err %v; want 16", sid, len(raw), err)
		}
		if seen[sid] {
			t.Fatalf("sid %q repeated within 1000 draws", sid)
		}
		seen[sid] = true
	}
}
