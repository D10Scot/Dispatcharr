package httpapi

import (
	"net/http"
	"path"
	"regexp"
	"strings"

	"github.com/D10Scot/Dispatcharr/relay/output"
)

// XCStreamIDPattern is dispatcharr/utils.py:115's XC_STREAM_ID_PATTERN,
// anchored: digits with an optional extension, and nothing else.
//
// Django's URL resolver applies it, so a path that does not match reaches
// stream_xc never -- it falls through to the SPA catch-all. This relay has no
// catch-all, so the handler applies the pattern itself and answers 404, which
// is the same outcome from the client's side.
var XCStreamIDPattern = regexp.MustCompile(`\A\d+(?:\.[A-Za-z0-9]+)?\z`)

// XCHandler serves the two XC live roots: /live/<user>/<pass>/<id> and the
// bare /<user>/<pass>/<id>.
//
// WHY THIS IS A WRAPPER AND NOT A SECOND HANDLER. stream_xc authorizes ONCE
// and passes its decision into stream_ts (views.py:862-889), so an XC tune is
// not authorized twice and does not mint a second client id for one
// connection -- parity-matrix row 15. The Go shape is the same: the channel
// this serves is the one the authorize hop resolved (X-Relay-Channel) or the
// one the dev fallback's decision named, NEVER the numeric id in the path,
// which this relay cannot map to a uuid because that mapping is an ORM query.
//
// The extension is the ONE thing the path contributes, and it contributes it
// to the output format rather than to the channel: `.mp4` forces fMP4 and
// `.ts` forces MPEG-TS (:873-878), overriding whatever the hop resolved.
// authorize_stream's resolve_output_format takes a `force` parameter and the
// hop never passes it, "because the hop authorizes a URI and the override is
// a property of the view's call" (apps/proxy/authorize.py:236-246) -- so the
// override has to be applied here, on both relays, for the same reason.
func XCHandler(deps StreamDeps) http.Handler {
	inner := StreamHandler(deps)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw := r.PathValue("channelID")
		if !XCStreamIDPattern.MatchString(raw) {
			// Django's resolver would not have matched this path at all.
			http.NotFound(w, r)
			return
		}
		if force := xcForcedFormat(raw); force != "" {
			// Applied by REWRITING THE HEADER the hop set, so identify()
			// keeps one source for the client's format and this stays the
			// only place the extension is read. Set on the request the
			// inner handler sees, never on the client's own: a rewrite is
			// only legitimate because the extension is part of the URI the
			// hop already authorized.
			r.Header.Set("X-Relay-Output-Format", force)
		}
		inner(w, r)
	})
}

// xcForcedFormat is views.py:872-878's extension override, lowercased as it
// lowercases. An extension that is neither returns "", which leaves the hop's
// own X-Relay-Output-Format standing.
func xcForcedFormat(id string) string {
	switch strings.ToLower(path.Ext(id)) {
	case ".mp4":
		return output.FormatFMP4
	case ".ts":
		return OutputFormatMPEGTS
	}
	return ""
}
