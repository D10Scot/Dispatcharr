package httpapi

import (
	"net/http"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
	"github.com/D10Scot/Dispatcharr/relay/output"
)

// tuneXC opens an XC live root over the trusted path: the hop has resolved
// the numeric id to a uuid and put it on X-Relay-Channel, exactly as
// stream_xc hands decision.channel_uuid to stream_ts.
func (r *rig) tuneXC(t *testing.T, root, channelUUID, clientID string) *http.Response {
	t.Helper()
	header := http.Header{}
	header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	header.Set("X-Relay-Channel", channelUUID)
	header.Set("X-Relay-Client", clientID)
	header.Set("X-Relay-Client-IP", "198.51.100.4")
	header.Set("X-Relay-User", "7")
	return r.tune(t, root, header)
}

// ROW 15: an XC tune serves the channel the hop resolved, is authorized
// once, and mints no second client id.
//
// THE CHANNEL ASSERTION IS THE ONE THAT CAN FAIL LOUDEST: the path carries
// the numeric Xtream id and the header carries the uuid, and a relay that
// used the path would tune a channel nobody authorized -- and could not, in
// fact, tune anything, since the numeric id maps to a uuid only through an
// ORM query this process cannot make.
func TestAnXCTuneServesTheHopsChannelAndAuthorizesOnce(t *testing.T) {
	for _, root := range []string{
		"/live/xcuser/xcpass/12345",
		"/xcuser/xcpass/12345",
	} {
		t.Run(root, func(t *testing.T) {
			r := fanRig(t, relaytest.Config{}, nil)
			response := r.tuneXC(t, root, "c-xc-uuid", "client-from-the-hop")
			defer func() { _ = response.Body.Close() }()
			if response.StatusCode != http.StatusOK {
				t.Fatalf("the XC tune answered %d, want 200", response.StatusCode)
			}
			packetRun(t, "the XC client", response.Body, 1)

			if r.Manager.Get("c-xc-uuid") == nil {
				t.Fatalf("the relay is running %v, not the uuid the hop resolved", runningIDs(r))
			}
			if r.Manager.Get("12345") != nil {
				t.Fatalf("the relay tuned the numeric path id, which it cannot map to a uuid")
			}
			// AUTHORIZED ONCE: a trusted XC tune asks the control plane
			// nothing, exactly as a trusted native tune does. A relay that
			// re-authorized here would make every XC tune cost a hop Django
			// already paid for.
			if got := r.Control.AuthorizeRequests(); len(got) != 0 {
				t.Errorf("a trusted XC tune made %d authorize calls, want 0", len(got))
			}
			// AND NO SECOND CLIENT ID: the id the hop minted is the id the
			// registry holds.
			clients := r.Manager.Get("c-xc-uuid").ClientSnapshot()
			if len(clients) != 1 || clients[0].ID != "client-from-the-hop" {
				t.Errorf("the registry holds %v, want exactly the hop's client id", clients)
			}
		})
	}
}

// The extension overrides the output format the hop resolved, and only the
// two extensions views.py:872-878 names do.
//
// FOUR ROWS, and the third and fourth are what make it able to fail: a
// relay that ignored the extension would pass a test that only checked
// ".mp4 is fmp4" if the hop had already said fmp4.
func TestTheXCExtensionOverridesTheHopsOutputFormat(t *testing.T) {
	for _, tc := range []struct {
		id       string
		hopSaid  string
		wantFmt  string
		wantCode int
	}{
		{"12345.mp4", OutputFormatMPEGTS, output.FormatFMP4, http.StatusOK},
		{"12345.ts", output.FormatFMP4, OutputFormatMPEGTS, http.StatusOK},
		// No extension: the hop's own answer stands.
		{"12345", output.FormatFMP4, output.FormatFMP4, http.StatusOK},
		// An extension that is neither leaves it standing too.
		{"12345.m3u8", OutputFormatMPEGTS, OutputFormatMPEGTS, http.StatusOK},
	} {
		t.Run(tc.id, func(t *testing.T) {
			r := fanRig(t, relaytest.Config{Rate: 4}, nil,
				withRemux(standInRemux(t, "--fmp4-fragments", "200", "--fmp4-interval", "0.02")))
			header := http.Header{}
			header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
			header.Set("X-Relay-Channel", "c-xc-fmt")
			header.Set("X-Relay-Client", "client-a")
			header.Set("X-Relay-Output-Format", tc.hopSaid)
			response := r.tune(t, "/live/u/p/"+tc.id, header)
			defer func() { _ = response.Body.Close() }()
			if response.StatusCode != tc.wantCode {
				t.Fatalf("the XC tune answered %d, want %d", response.StatusCode, tc.wantCode)
			}

			// The format is read off the CLIENT REGISTRY, which is what the
			// status surfaces render -- not off the Content-Type, which is a
			// second derivation of the same fact.
			waitFor(t, "the client to register", 15*time.Second, func() bool {
				ch := r.Manager.Get("c-xc-fmt")
				return ch != nil && ch.Clients() == 1
			})
			got := r.Manager.Get("c-xc-fmt").ClientSnapshot()[0].OutputFormat
			if got != tc.wantFmt {
				t.Fatalf("the client's output_format is %q, want %q", got, tc.wantFmt)
			}
		})
	}
}

// A path Django's own resolver would not match is a 404 here.
//
// XC_STREAM_ID_PATTERN is digits with an optional extension; anything else
// falls through to the SPA catch-all there and has nowhere to fall through
// to here, so the handler applies the pattern itself.
func TestAnXCPathDjangoWouldNotResolveIs404(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	for _, id := range []string{"not-a-number", "12345.", "12345.mp4.extra", ""} {
		response := r.tuneXC(t, "/live/u/p/"+id, "c-xc-uuid", "client-a")
		status := response.StatusCode
		_ = response.Body.Close()
		if status != http.StatusNotFound {
			t.Errorf("the XC root with id %q answered %d, want 404", id, status)
		}
	}
	// And nothing was tuned by any of them.
	if got := len(r.Manager.Snapshot()); got != 0 {
		t.Errorf("the relay is running %d channels after four refused XC paths", got)
	}
}

// The bare three-segment XC root does NOT shadow the internal control
// collection route, which has exactly three segments too.
//
// net/http's mux prefers the more specific pattern, and this asserts that
// rather than trusting it: /proxy/relay/channels reaching XCHandler would
// answer 404 for every stats poll in the deployment.
func TestTheBareXCRootDoesNotShadowTheControlRoutes(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	status, raw := r.listChannels(t, "")
	if status != http.StatusOK {
		t.Fatalf("GET /proxy/relay/channels answered %d, want 200: the bare XC root shadowed "+
			"it -- %s", status, raw)
	}
	if _, present := decodeObject(t, raw)["channels"]; !present {
		t.Fatalf("GET /proxy/relay/channels answered %s, which is not the list payload", raw)
	}
}
