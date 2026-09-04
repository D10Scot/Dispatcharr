import { describe, expect, it } from 'vitest';
import { fmt, fmtDate, fmtDelta, shortSha, statusClass } from '../lib/format.js';

describe('fmt', () => {
  it('formats by unit', () => {
    expect(fmt(null, 'count')).toBe('—');
    expect(fmt(1860, 'count')).toBe('1,860');
    expect(fmt(45.678, 'pct')).toBe('45.7%');
    expect(fmt(0.9535, 'ratio')).toBe('95%');
    expect(fmt(778, 'seconds')).toBe('13m');
    expect(fmt(8640, 'seconds')).toBe('2.4h');
    expect(fmt(270000, 'seconds')).toBe('3.1d');
    expect(fmt(12, 'days')).toBe('12 d');
    expect(fmt(6.9, 'score')).toBe('6.9');
  });
  it('shows one decimal for a ratio under 10%, not a rounded whole percent', () => {
    expect(fmt(0.0064, 'ratio')).toBe('0.6%');
    expect(fmt(0.9535, 'ratio')).toBe('95%');
  });
  it('formats deltas with a sign', () => {
    expect(fmtDelta(249, 'count')).toBe('+249');
    expect(fmtDelta(-3, 'count')).toBe('−3');
    expect(fmtDelta(0.4, 'pct')).toBe('+0.4 pt');
    expect(fmtDelta(0, 'count')).toBe('±0');
  });
  it('helpers', () => {
    expect(shortSha('fd413f0cc4ab3131789a68fb31f1ae622ae7371a')).toBe('fd413f0c');
    expect(fmtDate('2026-09-03')).toBe('3 Sep');
    expect(statusClass('good')).toBe('good');
    expect(statusClass('weird')).toBe('neutral');
  });
  it('fmtDate is null-safe', () => {
    // phases[].start/end and a stale series' last_real can all be null in the
    // real site.json (one phase has start: null; three have end: null).
    expect(fmtDate(null)).toBe('—');
    expect(fmtDate(undefined)).toBe('—');
  });
});
