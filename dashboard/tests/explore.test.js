import { beforeEach, describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
import { milestoneMarks, seriesFor } from '../lib/chart.js';
import { render } from '../pages/explore.js';

describe('chart helpers', () => {
  it('builds a daily series with gaps and a commit series', () => {
    const m = site.groups.safety_net[0];
    const daily = seriesFor(m, 'daily');
    expect(daily.xs.length).toBe(18);
    expect(daily.ys.slice(0, 6)).toEqual([null, null, null, null, null, null]);
    expect(daily.ys.slice(-3)).toEqual([200, 249, 249]);
    const commits = seriesFor(m, 'commits');
    expect(commits.ys).toEqual([0, 249]);
    expect(commits.labels).toEqual(['fd413f0c', '75a68555']);
    expect(seriesFor(site.groups.security[0], 'commits').xs).toEqual([]);
    expect(seriesFor(site.groups.safety_net[1], 'daily').ys).toEqual([null, null, null]);
  });
  it('places milestone marks inside the x-range only', () => {
    const m = site.groups.safety_net[0];
    expect(milestoneMarks(site, seriesFor(m, 'commits').xs).map((x) => x.label)).toEqual(['v0.29.0 baseline', 'Phase 0 done']);
    // e2e's padded daily now spans the whole date range, so it would show
    // both milestones and not discriminate the "inside range only" filter;
    // codeql's short 3-day daily window (starting on the Phase 0 date) does.
    expect(milestoneMarks(site, seriesFor(site.groups.security[0], 'daily').xs).map((x) => x.label)).toEqual(['Phase 0 done']);
  });
});

describe('explore page', () => {
  let root;
  beforeEach(() => { document.body.innerHTML = '<main id="root"></main>'; root = document.getElementById('root'); });
  it('renders every catalogued metric grouped, with note and mode toggle', () => {
    render(site, root, new URLSearchParams(''));
    expect(root.querySelectorAll('.chart-block').length).toBe(5);
    expect([...root.querySelectorAll('.grp')].map((g) => g.textContent)).toEqual(['Safety net', 'Security', 'Extraction readiness', 'Delivery']);
    expect(root.querySelector('[data-id="e2e_scenarios"] .note').textContent).toBe('Playwright test() call sites.');
    // e2e_scenarios has commits, so the default (per-commit) mode draws its 2 commit points.
    expect(root.querySelector('[data-id="e2e_scenarios"] .plot').dataset.points).toBe('2');
    // codeql_open_critical_high is derived (commits: null), so it always draws daily (3 points).
    expect(root.querySelector('[data-id="codeql_open_critical_high"] .plot').dataset.points).toBe('3');
    expect(root.querySelector('a.active').textContent).toBe('per commit');
  });
  it('honours ?mode=daily', () => {
    render(site, root, new URLSearchParams('mode=daily'));
    expect(root.querySelector('[data-id="e2e_scenarios"] .plot').dataset.points).toBe('18');
    expect(root.querySelector('a.active').textContent).toBe('daily');
  });
});
