import { beforeEach, describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
import { render } from '../pages/overview.js';
import { contextLine, tile } from '../lib/status.js';

// The fixture (committed by Task 16) really has 3 phases (investigate,
// phase0, phase1 — the last with start: null and no milestones) and 3
// headline metrics, so those counts are asserted against the real data
// rather than copied from the task brief's earlier draft numbers.
describe('overview', () => {
  let root;
  beforeEach(() => {
    document.body.innerHTML = '<main id="root"></main>';
    root = document.getElementById('root');
  });

  it('renders the phase strip, one tile per headline, grouped, and the footer', () => {
    render(site, root);
    expect(root.querySelectorAll('.phase').length).toBe(3);
    expect(root.querySelectorAll('.phase.cur').length).toBe(1);
    expect(root.querySelectorAll('.tile').length).toBe(3);
    const groups = [...root.querySelectorAll('.grp')].map((g) => g.textContent);
    expect(groups).toEqual(['Safety net', 'Security']);
    expect(root.querySelector('.foot').textContent).toContain('dependabot_alerts: not_permitted');
  });

  it('colours tiles by status and shows the value and context', () => {
    render(site, root);
    // e2e_scenarios: daily starts 2026-08-25, after meta.baseline.date
    // (2026-08-19) — so the label reads "since 25 Aug", not "since baseline".
    const e2e = root.querySelector('[data-id="e2e_scenarios"]');
    expect(e2e.classList.contains('good')).toBe(true);
    expect(e2e.querySelector('.v').textContent).toBe('249');
    expect(e2e.querySelector('.d').textContent).toBe('+249 since 25 Aug');
    expect(e2e.querySelector('svg path.line').getAttribute('d')).toMatch(/^M/);

    // codeql_open_critical_high: daily starts 2026-09-03, also after the
    // baseline date — "since 3 Sep".
    const cq = root.querySelector('[data-id="codeql_open_critical_high"]');
    expect(cq.classList.contains('bad')).toBe(true);
    expect(cq.querySelector('.d').textContent).toBe('target 0 · ±0 since 3 Sep');

    const cov = root.querySelector('[data-id="backend_coverage"]');
    expect(cov.classList.contains('stale')).toBe(true);
    expect(cov.querySelector('.v').textContent).toBe('—');
    expect(cov.querySelector('.d').textContent).toContain('no data yet');
  });

  it('derives "since" from the first non-null daily point, not the first (baseline-padded) point', () => {
    // The real build pads `daily` with nulls back to meta.baseline.date so
    // every series lines up on the same x-axis — daily[0][0] is therefore
    // always the baseline date, never the metric's actual since. A metric
    // whose real data starts well after the baseline (e.g. a catalogue
    // metric added later, like the real `scorecard` series starting 4 Sep
    // against an 19 Aug baseline) must still read "since <its own date>".
    const padded = {
      ...site,
      headline: [{
        ...site.headline[0], // reuse e2e_scenarios' shape (group safety_net, unit count, direction up)
        id: 'padded_metric',
        daily: [['2026-08-19', null], ['2026-08-20', null], ['2026-09-01', 10], ['2026-09-02', 12]],
        commits: null,
        now: 12,
        at_baseline: 10,
        spark: [null, null, 10, 12],
      }],
    };
    render(padded, root);
    const t = root.querySelector('[data-id="padded_metric"]');
    expect(t.querySelector('.d').textContent).toBe('+2 since 1 Sep');
  });

  it('positions phase milestones by inline left:N% rather than nth-of-type CSS', () => {
    render(site, root);
    const dots = root.querySelectorAll('.phase .m');
    expect(dots.length).toBe(2); // investigate has 1, phase0 has 1, phase1 has 0
    for (const dot of dots) {
      expect(dot.getAttribute('style')).toMatch(/left:\s*-?\d+(\.\d+)?%/);
    }
  });

  it('never injects markup from data', () => {
    const evil = { ...site.headline[0], label: '<img src=x onerror=alert(1)>' };
    const el = tile(evil);
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('.l').textContent).toContain('<img');
  });

  it('context line rules', () => {
    expect(contextLine({ unit: 'count', direction: 'up', target: null, now: 5, at_baseline: 2, stale: false, last_real: 'x' })).toBe('+3 since baseline');
    expect(contextLine({ unit: 'pct', direction: 'up', target: 60, now: 45.6, at_baseline: 45.6, stale: false, last_real: 'x' })).toBe('target 60% · ±0 since baseline');
    expect(contextLine({ unit: 'count', direction: 'up', target: null, now: null, at_baseline: null, stale: true, last_real: null })).toBe('no data yet');
    expect(contextLine({ unit: 'count', direction: 'up', target: null, now: 5, at_baseline: 2, stale: true, last_real: '2026-09-01T06:00:00+00:00' })).toBe('+3 since baseline · stale since 1 Sep');
    // "since <date>" wording when the metric's since (first daily point) is
    // after meta.baseline.date, via the optional since/baseline_date fields
    // a page decorates the metric with before calling tile()/contextLine().
    expect(contextLine({ unit: 'count', direction: 'up', target: null, now: 5, at_baseline: 2, stale: false, last_real: 'x', since: '2026-08-25', baseline_date: '2026-08-19' })).toBe('+3 since 25 Aug');
  });
});
