package telemetry

import (
	"regexp"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// The pattern classes of D9, used ONLY for log message bodies (R-Q17). They
// are best effort and no stronger than stdout: a bare secret that matches no
// class passes. They are documented as that, and their tests are policy tests,
// not proofs.
var (
	// key=value secrets.
	secretKV = regexp.MustCompile(`(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|auth|authorization|username)=[^\s&'"]+`)
	// An HLS media-session token: "v1." + a 22-character sid + "." + a
	// 43-character MAC (relay/control/mediasession.go).
	hlsToken = regexp.MustCompile(`\bv1\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}\b`)
	// Any UUID.
	uuidPattern = regexp.MustCompile(`(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`)
	// Runs of 32 or more hex digits.
	longHex = regexp.MustCompile(`(?i)\b[0-9a-f]{32,}\b`)
	// A scheme-less path: a slash that starts the text or follows whitespace,
	// a quote, '=', '(' or '['.
	barePath = regexp.MustCompile(`(^|[\s'"=(\[,])/[^\s'"]+`)
)

// scrub is the message-body scrubber: relay/redact.Line (absolute URLs, host
// kept) and then the pattern classes.
func scrub(s string) string {
	s = redact.Line(s)
	s = secretKV.ReplaceAllString(s, "${1}=[redacted]")
	s = hlsToken.ReplaceAllString(s, "[token]")
	s = uuidPattern.ReplaceAllString(s, "[uuid]")
	s = longHex.ReplaceAllString(s, "[hex]")
	s = barePath.ReplaceAllString(s, "${1}[path]")
	return s
}
