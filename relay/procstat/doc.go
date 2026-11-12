// Package procstat reads the CPU time and resident memory of the process
// groups the relay spawns (observability spec M8 and M9).
//
// It is stdlib only. It does not know about OpenTelemetry: relay/telemetry
// observes a Registry from its instrument callbacks. On Linux the source is
// /proc; elsewhere the source reports nothing, so the two instruments have no
// points on a developer's macOS build.
//
// M8 is a cumulative counter. A sum over the processes alive at collection
// time would fall whenever one child of a tracked group exits while its
// siblings run on, and a backend would read that fall as a counter reset. The
// Registry therefore keeps one accumulator per label set and adds, for each
// process identity (pid, starttime), the CPU it used since the previous
// collection. A process that exits keeps what was already added; what is lost
// is the CPU it used after its last observation, so M8 is a lower bound.
package procstat
