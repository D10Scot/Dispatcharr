// Package session is the relay's HLS session table (Phase 4 spec, § Presence
// and lifecycle; § The ADR 0006 amendment): the one place the relay INFERS a
// viewer's presence rather than observing it.
//
// A TS or fMP4 client is a goroutine, so its registry entry cannot outlive it.
// An HLS viewer is a sequence of short requests with no goroutine between
// them, so its entry is held by a session, and the session ends on one of five
// things: an explicit DELETE /hls/<token> (Table.Leave), an admin client stop
// or stream-limit termination (Table.EndClient), the stop of its channel or of
// its pipeline (Table.StopChannel, Table.StopPipeline), or the idle sweep
// (Table.Sweep: max(12 s, 6 x TARGETDURATION) with no request in flight). One
// process-wide sweeper ticks every second (Table.Run), and it is not tied to
// any channel or pipeline: a session outlives both, being resumable for
// ResumeWindow after an idle departure and answering one 410 after a stop.
//
// THE LOCK RULE. The table's mutex is the innermost in the process: the order
// is Manager.mu, then Channel.mu, then this one. Code holding it never takes
// c.mu, m.mu or a pipeline's outMu, never calls a release func, never emits an
// event and never writes a response. Every transition therefore TAKES what it
// must run (a Departure, a slice of channel.StoppedClient) under the lock and
// the caller runs it after unlocking.
//
// The package imports relay/channel (for *channel.Channel and *channel.Client)
// and relay/hls (for *hls.Pipeline); relay/channel never imports it, and
// reaches it only through channel.SessionEnder. The media-session token itself
// is relay/control's, and the HTTP handlers are relay/httpapi's.
package session
