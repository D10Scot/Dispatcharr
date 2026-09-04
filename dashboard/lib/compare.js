// Milestone-to-milestone deltas. Uses the build step's precomputed pair when
// it exists, otherwise derives the same rows from per-commit series so any
// two milestones can be compared.

export function deltaIsGood(direction, delta) {
  // `null < 0` / `null > 0` are both false, not null, so a missing delta
  // (either milestone sha has no row for this metric) must be guarded
  // before the direction switch, not left to fall through it.
  if (delta === null || delta === undefined || !Number.isFinite(delta)) return null;
  if (direction === 'info' || delta === 0) return null;
  return direction === 'down' || direction === 'zero' ? delta < 0 : delta > 0;
}

export function rowsFor(site, fromSha, toSha) {
  const pre = site.compare && site.compare[`${fromSha}..${toSha}`];
  if (pre) return pre;
  const rows = [];
  for (const [group, metrics] of Object.entries(site.groups || {})) {
    for (const m of metrics) {
      if (!m.commits) continue;
      const bySha = Object.fromEntries(m.commits.map(([sha, , v]) => [sha, v]));
      if (!(fromSha in bySha) || !(toSha in bySha)) continue;
      const delta = bySha[toSha] - bySha[fromSha];
      rows.push({ id: m.id, group, label: m.label, unit: m.unit, direction: m.direction,
                  from: bySha[fromSha], to: bySha[toSha], delta, good: deltaIsGood(m.direction, delta) });
    }
  }
  return rows;
}
