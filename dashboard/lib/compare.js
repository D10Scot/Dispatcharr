// Milestone-to-milestone deltas. Uses the build step's precomputed pair when
// it exists, otherwise derives the same rows from per-commit series (or, for
// derived/coverage metrics, forward-filled daily values) so any two
// milestones can be compared.

// Fixed display order for the fallback path. site.groups' own keys are
// alphabetical (the build step json.dumps'es with sort_keys=True) — this is
// the order pages actually render groups in, and it must match a
// precomputed site.compare[...] pair's row order for the two paths to be
// interchangeable. Exported so pages reuse the same order rather than
// re-deriving (or accidentally diverging from) it.
export const GROUP_ORDER = ['safety_net', 'security', 'extraction', 'delivery', 'agents'];

export function deltaIsGood(direction, delta) {
  // `null < 0` / `null > 0` are both false, not null, so a missing delta
  // (either milestone sha has no row for this metric) must be guarded
  // before the direction switch, not left to fall through it.
  if (delta === null || delta === undefined || !Number.isFinite(delta)) return null;
  if (direction === 'info' || delta === 0) return null;
  return direction === 'down' || direction === 'zero' ? delta < 0 : delta > 0;
}

// The last non-null daily value on or before `date` (an iso YYYY-MM-DD
// string) — mirrors metrics/build/calendar_.py's forward_fill (points need
// not be pre-sorted; null before the first point).
function valueOnDate(daily, date) {
  if (!date) return null;
  const sorted = [...(daily || [])].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  let result = null;
  for (const [d, v] of sorted) {
    if (d > date) break;
    if (v !== null && v !== undefined) result = v;
  }
  return result;
}

export function rowsFor(site, fromSha, toSha) {
  const pre = site.compare && site.compare[`${fromSha}..${toSha}`];
  if (pre) return pre;

  const dateBySha = Object.fromEntries((site.milestones || []).map((m) => [m.sha, m.date]));
  const fromDate = dateBySha[fromSha] ?? null;
  const toDate = dateBySha[toSha] ?? null;

  const rows = [];
  for (const group of GROUP_ORDER) {
    for (const m of (site.groups || {})[group] || []) {
      let from = null;
      let to = null;
      // R45: `compare_by` is the build step's own branch, published on every
      // metric entry — reading it is what keeps this fallback and
      // assemble.py's `compare()` from drifting. `commits !== null` is NOT a
      // substitute: a coverage metric has per-commit rows just like a
      // snapshot metric, but they sit at whatever sha the once-daily job
      // happened to see, so a per-sha lookup misses at both ends and the
      // whole row reads as "no data". The field is absent in a site.json
      // built before it existed; the old rule is the right guess there,
      // since it is wrong only for the daily families.
      //
      // Either way a per-sha read needs a commit list to read from; without
      // one there is nothing to look up, so it falls through to the date rule.
      const hasCommits = m.commits !== null && m.commits !== undefined;
      const readBySha = hasCommits && m.compare_by !== 'date';
      if (readBySha) {
        // Per-sha row value, null when a sha has no row of its own.
        const bySha = Object.fromEntries(m.commits.map(([sha, , v]) => [sha, v]));
        from = fromSha in bySha ? bySha[fromSha] : null;
        to = toSha in bySha ? bySha[toSha] : null;
      } else {
        // Forward-filled daily value on each milestone's own date; null when
        // the milestone predates the series.
        from = valueOnDate(m.daily, fromDate);
        to = valueOnDate(m.daily, toDate);
      }
      const delta = from !== null && from !== undefined && to !== null && to !== undefined ? to - from : null;
      rows.push({ id: m.id, group, label: m.label, unit: m.unit, direction: m.direction,
                  from, to, delta, good: deltaIsGood(m.direction, delta) });
    }
  }
  return rows;
}
