package httpapi

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// controlLog and controlClock are the two nil-defaults every control handler
// applies, in one place rather than four.
func controlLog(deps ControlDeps) *slog.Logger {
	if deps.Log == nil {
		return slog.Default()
	}
	return deps.Log
}

func controlClock(deps ControlDeps) func() time.Time {
	if deps.Now == nil {
		return time.Now
	}
	return deps.Now
}

// writeJSON writes a 200 with body as JSON.
func writeJSON(w http.ResponseWriter, log *slog.Logger, body any) {
	writeJSONStatus(w, log, http.StatusOK, body)
}

// writeJSONStatus writes status with body as JSON.
//
// The encode happens BEFORE the header is written, so an encoding failure --
// unreachable, every field is a plain type -- answers 500 rather than a
// half-written 200 with a status already committed.
func writeJSONStatus(w http.ResponseWriter, log *slog.Logger, status int, body any) {
	encoded, err := json.Marshal(body)
	if err != nil {
		log.Error("encoding a control response failed", "error", err) // credential-logging: ok - encoding/json reports a TYPE it cannot encode, never a field's value
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(encoded)
}

// stopPayload is RelayStopResponseSerializer, field for field and in its
// declaration order. Both DELETE routes answer with it.
//
// `status` is the service layer's own 'success' or 'error' travelling in the
// BODY rather than as an HTTP status, and the serializer's docstring says
// why: the relay answered, and "this channel is not running here" is an
// answer, not a refusal. The Django-side wrapper turns it into the 404 the
// admin API has always returned (live_proxy/views.py:1126-1129, :1179-1180).
type stopPayload struct {
	Status         string         `json:"status"`
	Message        string         `json:"message,omitempty"`
	ChannelID      string         `json:"channel_id,omitempty"`
	ClientID       string         `json:"client_id,omitempty"`
	PreviousState  *previousState `json:"previous_state,omitempty"`
	ModelReleased  *bool          `json:"model_released,omitempty"`
	LocallyHandled *bool          `json:"locally_processed,omitempty"`
	StopKeySet     *bool          `json:"stop_key_set,omitempty"`
	EventPublished *bool          `json:"event_published,omitempty"`
}

// previousState is the one-key dict ChannelService.stop_channel snapshots
// before the teardown (services/channel_service.py:606-615), which
// /proxy/ts/stop/<id> passes straight back to its caller.
type previousState struct {
	State string `json:"state"`
}

// stopResponse is ChannelService.stop_channel (services/channel_service.py:
// 588-630) over the in-memory map.
//
// The Redis half of that function -- the stopping key, the broadcast to
// other workers, the key sweep and the ownership release -- is deleted by
// D2 rather than ported: there is no second worker to tell and no key to
// delete. What remains is the part an admin can observe: the previous
// state, and the teardown itself.
func stopResponse(channels *channel.Manager, id string) stopPayload {
	ch := channels.Get(id)
	if ch == nil {
		// :603-604, verbatim. The two keys the success shape carries are
		// absent here exactly as they are there.
		return stopPayload{Status: "error", Message: "Channel not found"}
	}
	state := string(ch.State())
	released := channels.Stop(id)
	return stopPayload{
		Status:        "success",
		Message:       "Channel stop request sent",
		ChannelID:     id,
		PreviousState: &previousState{State: state},
		// bool(local_result) at :628. Manager.Stop reports whether it still
		// held the channel when it took the map entry, which is the same
		// question ProxyServer.stop_channel's return answers.
		ModelReleased: &released,
	}
}

// ClientHandler serves DELETE /proxy/relay/channels/{channelID}/clients/
// {clientID}: ChannelService.stop_client (services/channel_service.py:
// 653-714), which relay_client.stop_client calls and /proxy/ts/stop_client/
// wraps.
//
// THREE OF THE FOUR BOOLEANS MEAN SOMETHING DIFFERENT HERE, and each is
// answered honestly rather than faked:
//
//	stop_key_set     there, whether the SETEX of the client's stop key
//	                 succeeded -- attempted BEFORE the channel is looked up,
//	                 so it is true even for a channel that does not exist.
//	                 Here, whether a client of that id was signalled, because
//	                 the signal lives ON the client and cannot exist without
//	                 one.
//	locally_processed there, whether the client was on THIS worker. Here,
//	                 whether it was registered at all -- with one process the
//	                 two questions are the same question.
//	event_published  there, whether the stop was published over live:events
//	                 for another worker to act on. Always FALSE here: D2
//	                 deletes the pub/sub, and there is no other worker.
func ClientHandler(deps ControlDeps) http.HandlerFunc {
	log := controlLog(deps)
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("channelID")
		clientID := r.PathValue("clientID")
		ch := deps.Channels.Get(id)
		if ch == nil {
			// :679-684, including the stop_key_set the caller gets back.
			never := false
			writeJSON(w, log, stopPayload{
				Status:     "error",
				Message:    "Channel not found",
				StopKeySet: &never,
			})
			return
		}
		signalled := ch.StopClient(clientID)
		published := false
		writeJSON(w, log, stopPayload{
			Status:         "success",
			Message:        "Client stop request processed",
			ChannelID:      id,
			ClientID:       clientID,
			LocallyHandled: &signalled,
			StopKeySet:     &signalled,
			EventPublished: &published,
		})
	}
}

// advanceRequest is RelayAdvanceRequestSerializer plus the three fields 2c-8
// adds to it, which are what make this route servable by a relay that builds
// no command line (Amendment A4.1).
//
// url is required there (`serializers.CharField()` with no required=False)
// and so is stream_profile here: without it the relay has no argv to spawn
// and no way to tell a Proxy switch from a transcode one. Django holds both
// at every producer -- change_stream and next_stream each resolve the source
// in the API process before they call this route (ruling 11).
type advanceRequest struct {
	URL            string                    `json:"url"`
	UserAgent      string                    `json:"user_agent"`
	StreamID       *int                      `json:"stream_id"`
	M3UProfileID   *int                      `json:"m3u_profile_id"`
	StreamName     string                    `json:"stream_name"`
	ChannelName    string                    `json:"channel_name"`
	M3UProfileName string                    `json:"m3u_profile_name"`
	ResetTried     bool                      `json:"reset_tried"`
	Transcode      bool                      `json:"transcode"`
	StreamProfile  *control.StreamProfileRef `json:"stream_profile"`
	FFmpegProfile  *control.StreamProfileRef `json:"ffmpeg_stream_profile"`
}

// advancePayload is RelayAdvanceResponseSerializer, field for field and in
// its declaration order.
//
// THREE OF ITS FIELDS CANNOT BE SET BY THIS RELAY, and each is absent rather
// than invented:
//
//	confirmed   present only when the owner never answered within
//	            STREAM_SWITCH_CONFIRM_TIMEOUT (:566-570) -- a wait for a
//	            worker that no longer exists. The Django wrapper maps its
//	            absence to 502 and its presence to 504, so never setting it
//	            means a failed switch answers 502, which is the shape a
//	            direct (owner) update already has there.
//	event_published the pub/sub branch, deleted with the followers.
//	worker_id   proxy_server.worker_id. There is no worker to name, and
//	            change_stream reads its OWN process's worker id into the
//	            response it builds (views.py:1000, :1010) rather than this
//	            one, so nothing consumes it.
type advancePayload struct {
	Status          string         `json:"status"`
	Success         *bool          `json:"success,omitempty"`
	Message         string         `json:"message,omitempty"`
	DirectUpdate    *bool          `json:"direct_update,omitempty"`
	MetadataUpdated *bool          `json:"metadata_updated,omitempty"`
	Diagnostics     map[string]any `json:"diagnostics,omitempty"`
}

// AdvanceHandler serves POST /proxy/relay/channels/{channelID}/advance.
func AdvanceHandler(deps ControlDeps) http.HandlerFunc {
	log := controlLog(deps)
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("channelID")

		var req advanceRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			// DRF's own answer to a body that does not parse, and
			// relay_client maps a 4xx to RelayRefused, which change_stream
			// answers 502 for -- "the relay refused the request", which is
			// what happened.
			log.Error("the advance body did not decode", "channel", id, "error", redact.Error(err))
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}
		if req.URL == "" || req.StreamProfile == nil {
			// payload.is_valid(raise_exception=True) at relay_views.py:234
			// for a missing required field. stream_profile joins url as
			// required in 2c-8: see advanceRequest.
			log.Error("the advance body is missing a required field", "channel", id,
				"url_present", req.URL != "", "stream_profile_present", req.StreamProfile != nil)
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}

		ch := deps.Channels.Get(id)
		if ch == nil {
			// :477-482's not-found branch. Its diagnostics carry
			// in_local_managers, in_local_buffers and a Redis key list; the
			// first two are false here for the same reason they are false
			// there, and the third names a scan there is no Redis for.
			writeJSON(w, log, advancePayload{
				Status:  "error",
				Message: "Channel not found",
				Diagnostics: map[string]any{
					"in_local_managers": false,
					"in_local_buffers":  false,
				},
			})
			return
		}

		candidate := advanceSource(&req)
		build, ok := builderFor(ch)
		if !ok {
			log.Error("the channel has no resolver, so an operator switch cannot be built", "channel", id)
			failed, direct := false, true
			writeJSON(w, log, advancePayload{
				Status:       "success",
				Success:      &failed,
				DirectUpdate: &direct,
				Message:      "Stream switch failed",
			})
			return
		}
		source, err := build.source(candidate)
		if err != nil {
			// An unbuildable profile -- a null argv, Amendment A4.3 -- is
			// terminal for this switch and never a retry, because no retry
			// against the same profile can change what Django could not
			// split. Reported as a failed switch, which change_stream turns
			// into its 502.
			log.Error("the advance named a profile this relay cannot spawn", "channel", id, "error", redact.Error(err))
			failed, direct := false, true
			writeJSON(w, log, advancePayload{
				Status:       "success",
				Success:      &failed,
				DirectUpdate: &direct,
				Message:      "Stream switch failed",
			})
			return
		}

		applied := ch.Advance(channel.Resolved{Source: source, Info: infoFrom(candidate)}, req.ResetTried)
		// change_stream_url reports SUCCESS for an unchanged URL even though
		// update_url returned False: ":487-490 -- update_url() returns False
		// for same URL; still success so metadata refreshes". The relay has
		// no metadata to refresh, and the answer is the one that matters.
		success := true
		direct, updated := true, true
		if !applied {
			log.Info("the operator switch changed nothing", "channel", id)
		}
		writeJSON(w, log, advancePayload{
			Status:          "success",
			Success:         &success,
			DirectUpdate:    &direct,
			MetadataUpdated: &updated,
		})
	}
}

// advanceSource rebuilds the control.Source shape the tune path already knows
// how to turn into a running source, out of the advance body's own fields.
//
// One shape, not two: sourceBuilder.source and infoFrom are the same two
// functions the tune and the failover use, so an operator's switch cannot
// diverge from an automatic one in what it spawns.
func advanceSource(req *advanceRequest) *control.Source {
	source := &control.Source{
		URL:            req.URL,
		UserAgent:      req.UserAgent,
		Transcode:      req.Transcode,
		StreamProfile:  *req.StreamProfile,
		ChannelName:    req.ChannelName,
		StreamName:     req.StreamName,
		M3UProfileName: req.M3UProfileName,
		// SlotReserved is FALSE and that is deliberate: Django moved the
		// provider slot when it resolved this candidate (Phase 1 PR 6), and
		// the relay releases only what it reserved. Marking it reserved here
		// would make the channel's own release double-release.
		FFmpegStreamProfile: req.FFmpegProfile,
	}
	if req.StreamID != nil {
		source.StreamID = *req.StreamID
	}
	if req.M3UProfileID != nil {
		source.M3UProfileID = *req.M3UProfileID
	}
	return source
}

// builderFor is the source builder the channel's own tune created, reached
// through its resolver.
//
// The tune's builder rather than one assembled from the advance body,
// because it holds three tune-time facts an advance does not carry: which of
// the three Stream Profile architectures this channel plays (the answer's
// stream_profile is the CHANNEL's, apps/proxy/next_source.py:609-622), the
// defaulted user agent (input/manager.py:73), and the upstream read size
// (CHUNK_SIZE). Python keeps all three on the StreamManager across a switch
// for the same reason.
func builderFor(ch *channel.Channel) (sourceBuilder, bool) {
	r, ok := ch.Resolver().(*resolver)
	if !ok {
		return sourceBuilder{}, false
	}
	return r.build, true
}
