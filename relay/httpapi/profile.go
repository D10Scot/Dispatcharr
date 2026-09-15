package httpapi

import (
	"log/slog"
	"net/http"
	"strconv"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/output"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// The Output Profile half of the stream handler: resolve the profile the
// authorize hop named against the set next-source sent, start (or join) its
// transcode, and hand back the ring the client's own output is built from.
//
// views.py:765-776, in order and for the same reasons:
//
//	if resolved_output_profile:
//	    cmd = resolved_output_profile.build_command()
//	    if not proxy_server.ensure_output_profile(channel_id, id, cmd):
//	        ... return JsonResponse({...}, status=500)
//	source_buffer = proxy_server.get_buffer(channel_id, profile=id or None)
//
// The one thing that is not in that order is WHERE the profile row comes
// from: Python re-reads it from the database per client (views.py:150-155),
// and this relay reads it off the channel's cached copy of the next-source
// answer, which is what closes that ORM read (2b-2's Ruling R3).

// profileNotStartedBody is views.py:771's JsonResponse body, character for
// character. One of the few error bodies views.py spells out in full, so a
// client that reads it cannot tell the two implementations apart.
const profileNotStartedBody = `{"error": "Failed to start output profile transcode"}`

// attachOutputProfile resolves this client's Output Profile and starts or
// joins its transcode.
//
// It returns the ring whatever serves this client should read: the profile's
// output ring when a transcode is running, and the channel's own ring when no
// profile was asked for -- or when the one asked for is no longer in the
// active set, which is Python's own answer and not a fallback invented here.
//
// THE ABSENT PROFILE IS NOT AN ERROR, and that is the single least obvious
// behaviour in this file. The authorize hop resolved the id with
// is_active=True and put it in X-Relay-Output; views.py:150-155 then re-reads
// the row with is_active=True and gets None if it was deactivated in between,
// and :725-751 registers the client with that None and serves it plain TS.
// Reproduced: the client streams, and its registry row says null.
//
// `ok` false means the response has already been written and the caller must
// return.
func attachOutputProfile(
	w http.ResponseWriter,
	ch *channel.Channel,
	client *channel.Client,
	log *slog.Logger,
) (source *buffer.Ring, release func(), ok bool) {
	noop := func() {}
	if client.OutputProfileID == nil {
		return ch.Ring(), noop, true
	}
	id := strconv.Itoa(*client.OutputProfileID)

	profiles := ch.OutputProfiles()
	if !profiles.Known {
		// A contract mismatch: 502, as an absent proxy_settings key is. Not
		// a 500, which is what a profile that exists but cannot be started
		// gets, and not a silent fall-through to plain TS, which would serve
		// a client the wrong audio codec because the relay is newer than
		// Django.
		log.Error("the control plane sent no output_profiles", "channel", ch.ID(), "client", client.ID, "output_profile", id)
		http.Error(w, "control plane contract mismatch", http.StatusBadGateway)
		return nil, nil, false
	}

	profile, found := profiles.Lookup(id)
	if !found {
		// Deactivated between the authorize hop and the tune. Python serves
		// the client with no profile at all and records null; so does this.
		log.Info("the Output Profile this tune named is no longer active, serving without one",
			"channel", ch.ID(), "client", client.ID, "output_profile", id)
		// SetClientOutputProfile IS THE WRITE, and there is deliberately no
		// second one here. An earlier draft also assigned
		// `client.OutputProfileID = nil` directly, which reads as harmless --
		// same value, same field, the struct the caller already holds -- and is
		// a DATA RACE: Attach registered this pointer in the channel's own
		// registry, so the list endpoint reads the field under RLock
		// (channel/channel.go's ClientSnapshot) while this goroutine writes it
		// under no lock at all. Caught by the review, reproduced with `-race`,
		// and pinned by TestTheDeactivatedProfileCorrectionDoesNotRaceTheListEndpoint.
		ch.SetClientOutputProfile(client.ID, nil)
		return ch.Ring(), noop, true
	}
	// ONE FAILURE BRANCH FOR TWO FAULTS, deliberately (Global Constraint 18).
	// An argv Django could not build (`argv: null`, shlex refused the
	// profile's parameters) reaches StartProfile as an empty command and comes
	// back as ErrProfileCommandAbsent; a command that is not on disk comes
	// back as a spawn error. Python answers 500 to both -- build_command()
	// raises inside stream_ts's try (:823-827) for the first, and
	// ensure_output_profile returns False (:767-772) for the second -- so the
	// STATUS is parity either way, and only the LOG needs to tell them apart.
	//
	// The BODY is views.py:771's for both, and for the unbuildable case that
	// is a stated divergence: Python's carries shlex's own message, which
	// never crosses this wire and cannot be reproduced from anything the relay
	// holds.
	pipeline, releaseOutput, err := ch.AttachOutput(output.ProfileKey(profile.ID), channel.OutputSpec{Profile: &profile})
	if err != nil {
		log.Error("the Output Profile transcode could not be started",
			"channel", ch.ID(), "client", client.ID, "output_profile", id,
			"error", redact.Error(err))
		writeProfileFailure(w)
		return nil, nil, false
	}
	return pipeline.Ring(), releaseOutput, true
}

// writeProfileFailure writes views.py:770-772's 500.
func writeProfileFailure(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusInternalServerError)
	_, _ = w.Write([]byte(profileNotStartedBody))
}

// outputProfilesFrom converts a next-source answer's map into the wire-free
// form the channel package holds. One conversion per answer, at the one place
// the wire is read.
func outputProfilesFrom(answer *control.NextSourceAnswer) channel.OutputProfiles {
	if !answer.OutputProfilesPresent {
		return channel.OutputProfiles{}
	}
	byID := make(map[string]channel.OutputProfile, len(answer.OutputProfiles))
	for id, ref := range answer.OutputProfiles {
		byID[id] = channel.OutputProfile{ID: ref.ID, Argv: ref.Argv}
	}
	return channel.OutputProfiles{Known: true, ByID: byID}
}
