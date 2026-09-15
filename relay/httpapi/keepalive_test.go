package httpapi

import (
	"io"
	"net/http"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// nullPID is the PID of the keepalive and error packets (utils.py:87-92).
const nullPID = 0x1FFF

func pidOf(packet []byte) int { return int(packet[1]&0x1f)<<8 | int(packet[2]) }

// packetsUntil reads whole packets until `stop` returns true for one, the
// body ends, or the deadline passes -- at which point the body is closed so
// the reader returns -- and hands back the packets with the time each
// arrived. The reading goroutine owns the slices until it is done, so the
// race detector has nothing to say.
func packetsUntil(t *testing.T, body io.ReadCloser, deadline time.Duration, stop func([]byte) bool) ([][]byte, []time.Time) {
	t.Helper()
	type result struct {
		packets [][]byte
		at      []time.Time
	}
	done := make(chan result, 1)
	go func() {
		var out result
		defer func() { done <- out }()
		for {
			packet := make([]byte, buffer.TSPacketSize)
			if _, err := io.ReadFull(body, packet); err != nil {
				return
			}
			out.packets = append(out.packets, packet)
			out.at = append(out.at, time.Now())
			if stop(packet) {
				return
			}
		}
	}()
	select {
	case r := <-done:
		return r.packets, r.at
	case <-time.After(deadline):
		_ = body.Close()
		r := <-done
		return r.packets, r.at
	}
}

// KEEPALIVES ARE GATED ON THE HEALTH FLAG (output/ts/generator.py:387-405,
// :542-551): a client waiting at the buffer head receives null packets only
// once the channel is UNHEALTHY, and never while it is merely quiet. The
// primary goes silent after three chunks with CONNECTION_TIMEOUT at 5s, so
// the channel stays healthy for five seconds of silence -- in which no null
// packet may arrive -- and unhealthy after, at which point they must, at
// KEEPALIVE_INTERVAL. The control plane is slowed so the failover does not
// end the wait early.
func TestAnUnhealthyChannelSendsKeepalivesAtTheBufferHeadAndAHealthyOneDoesNot(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4, DeadAirAfterBytes: rigChunkBytes * 3}, map[string]any{
		"CONNECTION_TIMEOUT": 5, "HEALTH_CHECK_INTERVAL": 0.05, "KEEPALIVE_INTERVAL": 0.05,
	})
	r.Control.SetDelay(4 * time.Second)
	response := r.tuneAs(t, "c-keepalive", "client-a")
	defer func() { _ = response.Body.Close() }()

	// Everything the primary sends, up to the last asset packet before
	// the silence, plus whatever follows within eight seconds.
	packets, at := packetsUntil(t, response.Body, 8*time.Second, func([]byte) bool { return false })
	var lastAsset, firstNull time.Time
	nulls := 0
	for i, p := range packets {
		if pidOf(p) == nullPID {
			nulls++
			if firstNull.IsZero() {
				firstNull = at[i]
			}
			continue
		}
		if !firstNull.IsZero() {
			// A resumed asset packet after keepalives is the reconnect the
			// failed failover falls back to; fine, and not this test's.
			break
		}
		lastAsset = at[i]
	}
	if nulls == 0 {
		t.Fatal("no keepalive packet arrived on an unhealthy channel")
	}
	if quiet := firstNull.Sub(lastAsset); quiet < 5*time.Second {
		t.Fatalf("the first keepalive came %s after the last asset packet, while the channel was still HEALTHY (CONNECTION_TIMEOUT 5s): the health gate is not applied", quiet)
	}
	if nulls < 5 {
		t.Fatalf("only %d keepalives in the window; at a 50 ms interval there should be many", nulls)
	}
	for _, p := range packets {
		if pidOf(p) == nullPID && (p[0] != 0x47 || p[1] != 0x1F || p[2] != 0xFF || p[3] != 0x00) {
			t.Fatalf("a keepalive packet is not create_ts_packet's: % x", p[:4])
		}
	}
}

// THE KEEPALIVE CAP (output/ts/generator.py:371-380): keepalives refresh the
// timer _is_timeout reads, so a permanently failed stream would hold a client
// forever; MAX_KEEPALIVE_DURATION ends it. Compressed to half a second, with
// the control plane too slow to ever switch: the response ends, and the
// client count goes to zero.
func TestAClientIsDroppedOnceTheKeepaliveCapIsReached(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4, DeadAirAfterBytes: rigChunkBytes * 3}, map[string]any{
		"CONNECTION_TIMEOUT": 0.3, "HEALTH_CHECK_INTERVAL": 0.05, "KEEPALIVE_INTERVAL": 0.05, "MAX_KEEPALIVE_DURATION": 0.5,
	})
	r.Control.SetDelay(6 * time.Second)
	response := r.tuneAs(t, "c-cap", "client-a")
	defer func() { _ = response.Body.Close() }()

	started := time.Now()
	packets, _ := packetsUntil(t, response.Body, 15*time.Second, func([]byte) bool { return false })
	if elapsed := time.Since(started); elapsed > 12*time.Second {
		t.Fatalf("the response did not end within %s: the keepalive cap did not drop the client", elapsed)
	}
	nulls := 0
	for _, p := range packets {
		if pidOf(p) == nullPID {
			nulls++
		}
	}
	if nulls == 0 {
		t.Fatal("the client was dropped without any keepalive: something other than the cap ended it")
	}
	waitFor(t, "the client count to reach zero", 5*time.Second, func() bool {
		ch := r.Manager.Get("c-cap")
		return ch == nil || ch.Clients() == 0
	})
}

// `healthy` on GET /proxy/relay/channels (channel_status.py:527-529): true
// while data flows, false once the monitor has seen none for the threshold,
// and present on every channel this relay holds. The 2c-3 golden's
// NOT_SERVED_YET entry for it goes with this test.
func TestHealthyOnTheListPayloadFollowsTheHealthMonitor(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4, DeadAirAfterBytes: rigChunkBytes * 3}, map[string]any{
		"CONNECTION_TIMEOUT": 0.3, "HEALTH_CHECK_INTERVAL": 0.05,
	})
	r.Control.SetDelay(4 * time.Second)
	response := r.tuneAs(t, "c-healthy", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-healthy", 1)
	if got := listedChannel(t, r)["healthy"]; got != true {
		t.Fatalf("healthy = %v while data flows, want true", got)
	}
	waitFor(t, "healthy to go false on dead air", 5*time.Second, func() bool {
		return listedChannel(t, r)["healthy"] == false
	})
	status, _ := r.listChannels(t, "")
	if status != http.StatusOK {
		t.Fatalf("the list endpoint answered %d", status)
	}
}

// THE ERROR PACKET (output/ts/generator.py:235-239; parity-matrix row 3's
// Python pin reads it): a client that received nothing when its channel
// ended in error gets exactly one 188-byte packet on the null PID carrying
// "Error: <message>", with the message run()'s finally block would have
// written -- and then the body ends. Amendment A2.5 recorded 2c-2 as
// answering with zero bytes here.
func TestAClientWithNoBytesGetsAnErrorPacketWhenEverySourceFails(t *testing.T) {
	r := fanRig(t, relaytest.Config{Status: 404}, nil)
	response := r.tuneAs(t, "c-error-packet", "client-a")
	defer func() { _ = response.Body.Close() }()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("reading the body: %v", err)
	}
	if len(body) != buffer.TSPacketSize {
		t.Fatalf("the body is %d bytes, want exactly one error packet", len(body))
	}
	if pidOf(body) != nullPID || body[0] != 0x47 {
		t.Fatalf("the packet is not on the null PID: % x", body[:4])
	}
	want := "Error: All 1 stream options failed"
	if got := string(body[4 : 4+len(want)]); got != want {
		t.Fatalf("the packet carries %q, want %q", got, want)
	}
	if r.Upstream.Requests() != 3 {
		t.Fatalf("the provider saw %d requests, want 3", r.Upstream.Requests())
	}
}
