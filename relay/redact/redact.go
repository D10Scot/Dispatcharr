// Package redact is the one place a provider URL is stripped before it can
// reach a log line or an error message.
//
// A provider URL is a credential (CLAUDE.md, § Known defects): Xtream URLs
// carry the password in the PATH (/live/<user>/<pass>/<id>.ts), in the QUERY
// (?username=&password=) and sometimes in the userinfo. The Python side is
// policed by scripts/check_credential_logging.py; the Go side is policed by
// relay/internal/credlint, which requires every error-typed argument to a
// formatting or logging call to pass through Error below, or to carry a
// written reason it need not. That is what makes this package the ONE source
// of redaction: a second implementation would be a second thing for the
// linter to know about, and the one it did not know about would be the leak.
package redact

import (
	"errors"
	"net/url"
	"regexp"
	"strings"
)

// Error strips the URL out of an error that carries one.
//
// net/http wraps every client failure in a *url.Error whose Error() prints the
// whole URL, and its own redaction covers ONLY userinfo -- it turns
// http://user:pw@host into http://user:***@host and leaves the path and query
// string untouched, which is exactly where a Dispatcharr provider credential
// lives. The inner error is what is left: "dial tcp 127.0.0.1:1: connect:
// connection refused" names a host and a port and no secret.
//
// Every other error is returned as it came. os/exec's *exec.Error carries the
// program NAME (exec.Command's first argument), never its arguments; an
// *os.PathError from os.StartProcess carries the executable's path. Neither
// is a URL unless an operator set a Stream Profile's command TO a URL, and a
// command that is a URL is a misconfiguration this relay refuses before it
// spawns anything (channel.TranscodeSource). Moved here from
// channel.withoutURL (2c-2) so that one function is the redactor for the
// whole module.
func Error(err error) error {
	var urlErr *url.Error
	if errors.As(err, &urlErr) && urlErr.Err != nil {
		return urlErr.Err
	}
	return err
}

// urlPattern matches anything that looks like a URL with a scheme, up to the
// first whitespace or quote. Quotes end a match because ffmpeg quotes the URL
// it prints ("Input #0, mpegts, from 'http://...':") and a match that swallowed
// the closing quote would also swallow the rest of the line.
var urlPattern = regexp.MustCompile(`[A-Za-z][A-Za-z0-9+.-]*://[^\s'"]+`)

// Placeholder is what replaces the credential-bearing part of a URL.
const Placeholder = "[redacted]"

// Line replaces every URL in a line of text with its scheme and host and the
// placeholder, so "http://user:pw@host:8080/live/u/p/1.ts?token=t" becomes
// "http://host:8080/[redacted]".
//
// STRUCTURAL, NOT EXACT-MATCH, and the difference is what a stderr line
// needs. ffmpeg prints the URL it was given verbatim in its preamble, and
// that exact string could be replaced by a lookup. But the HLS demuxer also
// prints every segment URL it opens ("[hls @ 0x...] Opening 'http://host/
// path/seg-3.ts' for reading"), and those are DERIVED from the provider URL
// -- same credentialled path, different tail -- so an exact-match strip
// leaves the credential in every segment line. Anything with a scheme is
// treated as a URL, and only its host survives.
//
// The host is kept because it is what an operator needs to tell one provider
// from another in a log, and it is not a credential: the same host appears
// in the M3U account's own configuration.
func Line(s string) string {
	return urlPattern.ReplaceAllStringFunc(s, func(match string) string {
		parsed, err := url.Parse(match)
		if err != nil || parsed.Host == "" {
			// Unparseable, or a scheme with no authority (udp://... parses
			// with a host; "file:///x" has none): nothing to keep safely.
			scheme, _, found := strings.Cut(match, "://")
			if !found {
				return Placeholder
			}
			return scheme + "://" + Placeholder
		}
		return parsed.Scheme + "://" + parsed.Host + "/" + Placeholder
	})
}
