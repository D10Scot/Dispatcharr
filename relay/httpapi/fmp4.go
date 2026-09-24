package httpapi

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/output"
)

// ContentTypeFMP4 is what an fMP4 tune answers with: views.py:805's
// "video/mp4", where the TS path sends "video/mp2t" (:817).
const ContentTypeFMP4 = "video/mp4"

// serveFMP4 is the fMP4 half of the stream handler: start (or join) the
// channel's remux, send the init segment, then the fragments.
//
// THE 200 IS WRITTEN BEFORE THE INIT SEGMENT IS WAITED FOR, and that ordering
// is parity rather than convenience. views.py:799-810 builds a
// StreamingHttpResponse whose generator does the waiting, and WSGI calls
// start_response before it iterates -- so a client whose remux never produces
// an init segment receives a 200 with an EMPTY BODY, which is what
// apps/proxy/live_proxy/tests/test_fmp4_output.py's own docstring records as
// the failure shape. The 500 is reserved for the case Python reserves it for:
// ensure_output_format failing BEFORE the response exists (:789-798), which
// here is a remux that could not be spawned.
func serveFMP4(
	w http.ResponseWriter,
	r *http.Request,
	deps StreamDeps,
	ch *channel.Channel,
	client *channel.Client,
	source *buffer.Ring,
	log *slog.Logger,
) {
	// THE KEY CARRIES THE PROFILE AND THE SOURCE IS THE PROFILE'S RING, both
	// 2c-7's and both straight off views.py: :731-734 composes the format key
	// as f'{fmt}:p{id}' when a profile is active, and :790-792 hands
	// ensure_output_format the profile's buffer as the remux's input. So an
	// fMP4 client on an Output Profile runs TWO chained processes -- the
	// transcode under `mpegts:p3` writing a TS ring, and this remux under
	// `fmp4:p3` reading it -- and an fMP4 client with no profile runs one.
	key := output.FormatKey(output.FormatFMP4, client.OutputProfileID)
	pipeline, releaseOutput, err := ch.AttachOutput(key, channel.OutputSpec{Remux: deps.Remux, Source: source})
	if err != nil {
		// views.py:789-798's JsonResponse({"error": ...}, status=500), body and
		// all: a relay that answered a bare 500 here would be distinguishable
		// from the Python relay by any client that reads the body, and this is
		// one of the few error bodies views.py spells out in full.
		log.Error("the fMP4 remux could not be started", "channel", ch.ID())
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(`{"error": "Failed to start output format remux"}`))
		return
	}
	defer releaseOutput()

	fragments := pipeline.Fragments()

	w.Header().Set("Content-Type", ContentTypeFMP4)
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(http.StatusOK)
	rc := http.NewResponseController(w)
	if err := rc.Flush(); err != nil {
		return
	}

	// _wait_for_fmp4_ready (generator.py:175-200): up to INIT_SEGMENT_TIMEOUT
	// for the segment, and give up early if the channel is going. The buffer's
	// own close covers the second condition -- Close wakes WaitInit -- so there
	// is one wait here where Python has a 0.1s poll testing two keys.
	waitCtx, cancel := context.WithTimeout(r.Context(), output.InitSegmentTimeout)
	initErr := fragments.WaitInit(waitCtx)
	cancel()
	if initErr != nil {
		if errors.Is(initErr, buffer.ErrClosed) {
			log.Info("the fMP4 remux ended before it produced an init segment", "channel", ch.ID(), "client", client.ID)
		} else if errors.Is(initErr, context.DeadlineExceeded) {
			log.Error("timed out waiting for the fMP4 init segment",
				"channel", ch.ID(), "client", client.ID, "timeout", output.InitSegmentTimeout)
		}
		return
	}

	init := fragments.Init()
	if len(init) == 0 {
		// generator.py:131-134's "fMP4 init segment disappeared, aborting". Not
		// reachable through this buffer -- SetInit is the only writer and Close
		// does not clear it -- and kept because the check is one line and the
		// alternative is a client handed a valid 200 carrying fragments no
		// player can decode without a moov.
		log.Error("the fMP4 init segment disappeared", "channel", ch.ID(), "client", client.ID)
		return
	}
	// client_connect, at generator.py:113-127's own point: after
	// _wait_for_fmp4_ready and _setup_streaming have both succeeded and
	// BEFORE the init segment is yielded (:129-134). Amendment A6.5 owes
	// this to both client types and this is the fMP4 half.
	emitClientConnect(ch, client)

	if !writeChunks(w, rc, [][]byte{init}) {
		return
	}

	serveFMP4Client(r.Context(), w, rc, ch, client, fragments, log)
}

// serveFMP4Client is the fMP4 client loop: the port of
// _stream_data_generator and _is_timeout (output/fmp4/generator.py:268-357),
// with issue #222 fixed.
//
// IT LEAVES A CLIENT ON THE SAME EXIT serveClient DOES, which is what
// parity-matrix row 12 now records. Python's fMP4 generator dropped a client
// on elapsed time since its last fragment ALONE -- no health check, no
// keepalive -- so a stall that left a TS viewer on the same channel
// connected dropped an fMP4 viewer stream_timeout + failover_grace_period
// (40s by default) in, including in the middle of a slow failover. Set this
// beside serveClient:
//
//   - THE HEALTH GATE. A healthy channel never times its clients out: a
//     remux that has merely stalled while the upstream is fine is waited
//     for, as serveClient waits (output/ts/generator.py:592's
//     `not stream_manager.healthy`).
//   - THE KEEPALIVE CAP, WITHOUT THE KEEPALIVE BYTES. On an unhealthy
//     channel serveClient sends a null TS packet every KeepaliveInterval,
//     each refreshing the timer ClientTimeout reads, so its reachable exit
//     is MaxKeepalive and never ClientTimeout. An fMP4 byte stream has no
//     null packet a player is known to skip, so nothing is written here --
//     and the exit is the same one: MaxKeepalive of an unhealthy channel with
//     nothing to send, counted from the first such read and cleared by the
//     next fragment, as serveClient's keepaliveStart is. The one timing
//     difference is where the clock starts: serveClient waits five empty
//     reads first (at most 1.5s of its backoff), this loop starts it on the
//     first.
//
// Neither loop has the url_switching exemption, for the reason serveClient's
// own branch gives.
func serveFMP4Client(
	ctx context.Context,
	w http.ResponseWriter,
	rc *http.ResponseController,
	ch *channel.Channel,
	client *channel.Client,
	fragments *buffer.Fragments,
	log *slog.Logger,
) {
	tuning := ch.Tuning()

	// POSITIONED ONCE, through the FRAGMENT buffer's own Join, whose two
	// fallbacks differ from the TS ring's -- see buffer.Fragments.Join. Python
	// has a third branch here, `channel_initializing` -> index 0
	// (generator.py:217-220), and it is not ported as a branch because it
	// cannot produce a different answer: the client that initialised the
	// channel is the client whose remux was spawned moments earlier, so its
	// fragment buffer holds nothing older than the wait it just finished, and
	// Join's own "nothing is that old" fallback already returns the oldest
	// fragment minus one. Pinned by
	// TestAnFMP4ClientOnAFreshBufferStartsAtTheFirstFragment.
	cursor := fragments.Join(tuning.JoinBehind)

	// stallStart is when this client last found nothing to send on an
	// UNHEALTHY channel after having been fed: serveClient's keepaliveStart,
	// with no keepalive to send.
	var stallStart time.Time
	for {
		if ctx.Err() != nil {
			// serveClient's reason: the admin stop and the hang-up both
			// land here, and a buffer that always has a fragment never
			// reaches the wait below.
			return
		}
		frags, next, skipped := fragments.Read(cursor)
		if skipped > 0 {
			log.Warn("fMP4 client fell behind the fragment buffer",
				"channel", ch.ID(), "client", client.ID,
				"skipped", skipped, "head", fragments.Head())
		}
		if len(frags) > 0 {
			cursor = next
			if !writeChunks(w, rc, frags) {
				return
			}
			stallStart = time.Time{}
			// Touch, not Sent: the fMP4 generator writes last_active and no
			// byte counter (output/fmp4/generator.py:288-295), so an fMP4
			// client's detail row carries no bytes_sent, avg_rate_KBps or
			// current_rate_KBps -- reproduced as an absence with a
			// mechanism rather than a format check in the renderer.
			client.Touch(time.Now())
			continue
		}

		// generator.py:299's gevent.sleep(0.05) between empty reads, as a
		// bounded wait rather than a sleep: a fragment that lands mid-wait
		// wakes the reader immediately, and the bound is what makes the
		// timeout below reachable on a buffer that has gone quiet.
		waitCtx, cancel := context.WithTimeout(ctx, fmp4EmptyReadWait)
		err := fragments.Wait(waitCtx, cursor)
		cancel()
		switch {
		case err == nil:
			continue
		case errors.Is(err, buffer.ErrClosed):
			// The remux ended. One last read, for serveClient's reason: a
			// fragment published between the Read above and Close would
			// otherwise be dropped.
			if final, _, _ := fragments.Read(cursor); len(final) > 0 {
				writeChunks(w, rc, final)
			}
			return
		case errors.Is(err, context.DeadlineExceeded) && ctx.Err() == nil:
			// ROW 12, issue #222: serveClient's exit, as the doc comment says.
			if ch.Healthy() {
				continue
			}
			if stallStart.IsZero() {
				stallStart = time.Now()
			}
			if time.Since(stallStart) > tuning.MaxKeepalive {
				log.Warn("fMP4 client waited out the keepalive cap with no stream recovery, disconnecting",
					"channel", ch.ID(), "client", client.ID, "max", tuning.MaxKeepalive)
				return
			}
			continue
		}
		return
	}
}

// fmp4EmptyReadWait is generator.py:299's gevent.sleep(0.05): how long the loop
// waits for a fragment before looking at the clock again. A FIXED interval,
// where serveClient's TS loop backs off to a second
// (output/ts/generator.py:400-403's min(0.1 * consecutive_empty, 1.0)) --
// _stream_data_generator has no such backoff, and the difference is
// observable as how promptly the keepalive cap's clock starts once a stall
// begins.
const fmp4EmptyReadWait = 50 * time.Millisecond
