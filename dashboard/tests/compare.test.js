import { describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
import { GROUP_ORDER, deltaIsGood, rowsFor } from '../lib/compare.js';

const A = 'fd413f0cc4ab3131789a68fb31f1ae622ae7371a';
const B = '75a68555b931e7d088bfbbd859b35e6e27064312';

describe('compare', () => {
  it('uses the precomputed pair when present', () => {
    const rows = rowsFor(site, A, B);
    expect(rows.find((r) => r.id === 'e2e_scenarios').good).toBe(true);
  });
  it('exports the fixed group display order (not the alphabetical key order site.groups uses)', () => {
    expect(GROUP_ORDER).toEqual(['safety_net', 'security', 'extraction', 'delivery', 'agents']);
  });
  it('computes from commit series or forward-filled daily for an arbitrary pair', () => {
    const rows = rowsFor(site, B, A);
    const e2e = rows.find((r) => r.id === 'e2e_scenarios');
    expect(e2e.delta).toBe(-249);
    expect(e2e.good).toBe(false);
    // Derived metrics (commits === null) now appear too, valued from the
    // forward-filled daily series at each milestone's date rather than
    // dropped for lack of a per-commit row.
    const codeql = rows.find((r) => r.id === 'codeql_open_critical_high');
    expect(codeql.from).toBe(75); // daily value at B's date, 2026-09-03
    expect(codeql.to).toBeNull(); // A's date, 2026-08-19, predates codeql's daily series
    expect(codeql.delta).toBeNull();
  });
  it('orders fallback rows by GROUP_ORDER, then each group array\'s own order', () => {
    const rows = rowsFor(site, B, A);
    expect(rows.map((r) => r.id)).toEqual([
      'e2e_scenarios',
      'backend_coverage',
      'codeql_open_critical_high',
      'reverse_imports_into_proxy',
      'median_review_hours',
    ]);
  });
  // A coverage-shaped metric: per-commit rows exist, but at the once-daily
  // job's own SHAs, neither of which is a milestone. Reading it by sha finds
  // nothing at either end; reading it by date finds both. `compare_by` is
  // the only thing that tells the two apart — its `commits` list looks
  // exactly like a snapshot metric's.
  const coverageShaped = (extra) => ({
    id: 'backend_coverage', label: 'Backend line coverage', unit: 'pct', direction: 'up', group: 'safety_net',
    daily: [['2026-08-19', 35], ['2026-08-25', 38], ['2026-09-03', 40], ['2026-09-05', 40]],
    commits: [['e'.repeat(40), '2026-08-20T06:15:00+00:00', 35], ['f'.repeat(40), '2026-09-02T06:15:00+00:00', 40]],
    ...extra,
  });
  // Only `compare` is emptied: rowsFor short-circuits to a precomputed pair
  // when one exists, and the fixture has one for A..B.
  const siteWith = (metric) => ({ ...site, compare: {}, groups: { ...site.groups, safety_net: [metric] } });

  it('reads a metric marked compare_by "date" from the daily series, not its per-sha rows', () => {
    const cov = rowsFor(siteWith(coverageShaped({ compare_by: 'date' })), A, B).find((r) => r.id === 'backend_coverage');
    expect(cov.from).toBe(35); // A's date, 2026-08-19
    expect(cov.to).toBe(40); // B's date, 2026-09-03
    expect(cov.delta).toBe(5);
    expect(cov.good).toBe(true);
  });
  it('falls back to the old commits-shaped rule for an entry with no compare_by (older site.json)', () => {
    const cov = rowsFor(siteWith(coverageShaped({})), A, B).find((r) => r.id === 'backend_coverage');
    // Same metric, field absent: the per-sha branch runs, and neither
    // milestone sha has a row of its own, so both ends are null — the
    // behaviour compare_by corrects, kept for a site.json built before it.
    expect(cov.from).toBeNull();
    expect(cov.to).toBeNull();
    expect(cov.delta).toBeNull();
  });
  it('mirrors the python rule (same six cases as test_calendar.py::test_delta_is_good)', () => {
    expect(deltaIsGood('down', -2)).toBe(true);
    expect(deltaIsGood('down', 2)).toBe(false);
    expect(deltaIsGood('up', 2)).toBe(true);
    expect(deltaIsGood('zero', -1)).toBe(true);
    expect(deltaIsGood('info', 2)).toBeNull();
    expect(deltaIsGood('up', 0)).toBeNull();
  });
  it('is null-safe (JS-only guard, not mirrored from Python)', () => {
    // The contract says `good` is null whenever `delta` is null (either sha
    // missing a row), which delta < 0 / delta > 0 alone would get wrong
    // (null < 0 is false, not null) — guard before the direction switch.
    expect(deltaIsGood('up', null)).toBeNull();
  });
});
