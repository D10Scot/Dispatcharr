package httpapi

import (
	"context"
	"errors"
	"log/slog"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
)

// resolver is channel.Resolver over the control client: the control-plane
// half of _try_next_stream (input/manager.py:2076-2131) and the whole of its
// degraded fallback, which is why it is one per channel -- it holds the
// candidate list the initial answer carried, the in-memory form of
// live:channel:{id}:source_cache (spec § Stage 2c's key-family table,
// "Degraded-fallback cache: an in-memory field on the channel struct").
//
// THE DISPOSITION IS THE SPEC'S ERROR TABLE, and the distinction it turns on
// is the one apps/proxy/control_plane.py:118-136 draws: only an Unavailable
// -- a transport failure or a 5xx, both already retried once by the client
// -- falls back to the cache, "stale, unenforced, and no slot moves"
// (input/manager.py:2107-2112). A Refused (a 404 for a deleted channel, a
// 403 from a SECRET_KEY mismatch between roles) fails the switch loudly,
// because "the cached list would keep a deleted channel streaming, and a
// token fault would make every failover on the deployment degrade forever
// instead of failing once" (:2084-2098). A null source is ErrNoAlternate.
//
// THE TIMING SHAPE IS THE CLIENT'S: a failover against an unreachable
// control plane costs two attempts of (ConnectTimeout, ReadTimeout) plus the
// retry delay -- up to ~14 s of dead air on a hang, CLAUDE.md § Operationally
// -- before the cache is consulted, exactly as the Python relay spends
// control_plane.py's budget first. The context is bounded by tuneBudget for
// the same reason startTune's is.
type resolver struct {
	control    *control.Client
	id         string
	build      sourceBuilder
	alternates []control.Source
	log        *slog.Logger
}

func (r *resolver) Next(parent context.Context, req channel.NextRequest) (channel.Resolved, error) {
	ctx, cancel := context.WithTimeout(parent, tuneBudget)
	defer cancel()

	current := req.CurrentStreamID
	request := control.NextSourceRequest{
		ExcludeStreamIDs: req.Exclude,
		Reason:           "failover",
		CurrentURL:       req.CurrentURL,
	}
	if current != 0 {
		request.CurrentStreamID = &current
	}

	answer, err := r.control.NextSource(ctx, r.id, request)
	switch {
	case err == nil:
		if answer.Source == nil {
			return channel.Resolved{}, channel.ErrNoAlternate
		}
		return r.resolved(answer.Source, false, outputProfilesFrom(answer))
	case isUnavailable(err):
		r.log.Warn("control plane unreachable during failover; using the cached candidate list unenforced", "channel", r.id)
		candidate := r.pickCached(req)
		if candidate == nil {
			return channel.Resolved{}, channel.ErrNoAlternate
		}
		// The cached list carries no answer of its own, so the channel keeps
		// the Output Profile set it already had (2c-7's Ruling R5).
		return r.resolved(candidate, true, channel.OutputProfiles{})
	default:
		// A Refused, or a misconfigured address: never degrade.
		return channel.Resolved{}, err
	}
}

func isUnavailable(err error) bool {
	var unavailable *control.Unavailable
	return errors.As(err, &unavailable)
}

// pickCached is _pick_cached_alternate (input/manager.py:2020-2039): the
// first cached candidate not already tried and not the URL playing. The
// shape checks there guard a cache written by an older Django; here the
// candidates were decoded by control.Source and a candidate with no stream
// id or URL is skipped for the same reason.
func (r *resolver) pickCached(req channel.NextRequest) *control.Source {
	excluded := map[int]bool{}
	for _, id := range req.Exclude {
		excluded[id] = true
	}
	for i := range r.alternates {
		candidate := &r.alternates[i]
		if candidate.StreamID == 0 || candidate.URL == "" {
			continue
		}
		if excluded[candidate.StreamID] || candidate.URL == req.CurrentURL {
			continue
		}
		return candidate
	}
	return nil
}

// resolved builds the Source for a candidate. A candidate whose profile
// cannot be built -- a null argv, Amendment A4.3 -- is TERMINAL for that
// candidate: reported as the switch's failure, never retried as a
// connection failure, because no retry against the same profile can change
// what Django could not split.
func (r *resolver) resolved(candidate *control.Source, degraded bool, profiles channel.OutputProfiles) (channel.Resolved, error) {
	source, err := r.build.source(candidate)
	if err != nil {
		return channel.Resolved{}, err
	}
	return channel.Resolved{
		Source:         source,
		Info:           infoFrom(candidate),
		Degraded:       degraded,
		OutputProfiles: profiles,
	}, nil
}
