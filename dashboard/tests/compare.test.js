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
