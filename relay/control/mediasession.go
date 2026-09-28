package control

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"strings"
)

// MediaSessionVersion is the only media-session token version (Phase 4 spec,
// § The media-session token).
const MediaSessionVersion = "v1"

// The token's part lengths: a 16-byte sid and a 32-byte HMAC, each base64url
// without padding.
const (
	mediaSessionSIDLen = 22
	mediaSessionMACLen = 43
)

var contextMediaSession = []byte("media-session")

// NewMediaSessionID is 16 bytes from crypto/rand, base64url without padding:
// 22 characters. It is the session's key in the relay's table and names no
// channel and no client.
func NewMediaSessionID() (string, error) {
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(raw[:]), nil
}

// mediaSessionMAC is base64url_nopad(HMAC-SHA256(secret,
// "media-session" LF "v1" LF sid)). Its three fields are joined on a literal
// '\n' byte, as the other three contexts' messages are.
func mediaSessionMAC(secret, sid string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(contextMediaSession)
	mac.Write([]byte{'\n'})
	mac.Write([]byte(MediaSessionVersion))
	mac.Write([]byte{'\n'})
	mac.Write([]byte(sid))
	return base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

// MediaSessionToken is "v1." + sid + "." + the MAC above: 69 characters, all
// of them path-safe, so it can sit in a URL's path without escaping.
func MediaSessionToken(secret, sid string) string {
	return MediaSessionVersion + "." + sid + "." + mediaSessionMAC(secret, sid)
}

// VerifyMediaSession splits token on ".", requires exactly three parts, the
// literal "v1", a 22-character sid and a 43-character MAC, all ASCII, and
// compares the MAC with hmac.Equal. It looks nothing up: the session table
// does that, and only after a MAC has passed, so a forged token never reaches
// the table.
func VerifyMediaSession(secret, token string) (sid string, ok bool) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 || parts[0] != MediaSessionVersion {
		return "", false
	}
	sid, mac := parts[1], parts[2]
	if len(sid) != mediaSessionSIDLen || len(mac) != mediaSessionMACLen {
		return "", false
	}
	for i := 0; i < len(sid); i++ {
		if sid[i] >= 0x80 {
			return "", false
		}
	}
	// matches rejects a non-ASCII MAC before comparing, and compares in
	// constant time.
	if !matches(mac, mediaSessionMAC(secret, sid)) {
		return "", false
	}
	return sid, true
}
