import { beforeEach, describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
import { unix } from '../lib/chart.js';
import { render } from '../pages/story.js';

describe('story page', () => {
  let root;
  beforeEach(() => { document.body.innerHTML = '<main id="root"></main>'; root = document.getElementById('root'); });
  it('renders one section per phase with dates, summary, milestones and headline charts', () => {
    render(site, root);
    const phases = root.querySelectorAll('.story-phase');
    expect(phases.length).toBe(3);

    expect(phases[0].querySelector('h2').textContent).toBe('Investigate');
    expect(phases[0].querySelector('.when').textContent).toBe('from 19 Aug');
    expect(phases[0].querySelectorAll('.chart-block').length).toBe(1);
    // Investigate's start (2026-08-19) has no end, so shade.to resolves to
    // the headline metric's own last x (e2e_scenarios' daily series runs
    // through 2026-09-05, the fixture's "today") rather than staying null.
    expect(phases[0].querySelector('.chart-block .plot').dataset.shade).toBe(`${unix('2026-08-19')}..${unix('2026-09-05')}`);
    // Only investigate's own milestone ('v0.29.0 baseline') marks its
    // chart — 'Phase 0 done' belongs to phase0 and must not appear here,
    // or the shade would be buried under every other phase's milestones too.
    expect(phases[0].querySelector('.chart-block .plot').dataset.marks).toBe('1');

    expect(phases[1].querySelector('.when').textContent).toBe('3 Sep – 3 Sep');
    expect(phases[1].querySelector('li').textContent).toContain('Phase 0 done');
    expect(phases[1].querySelector('li a').getAttribute('href')).toBe('https://github.com/D10Scot/Dispatcharr/pull/155');
    expect(phases[1].querySelector('.chart-block h3').textContent).toBe('Open CodeQL critical + high');
    // phase0's window is a single day (start === end): shade runs from that
    // day's start through the end of that same day.
    expect(phases[1].querySelector('.chart-block .plot').dataset.shade).toBe(`${unix('2026-09-03')}..${unix('2026-09-03') + 86399}`);
    // Only phase0's own milestone ('Phase 0 done') marks its chart.
    expect(phases[1].querySelector('.chart-block .plot').dataset.marks).toBe('1');

    expect(phases[2].querySelector('.when').textContent).toBe('not started');
    expect(phases[2].querySelectorAll('li').length).toBe(0);
    expect(phases[2].querySelectorAll('.chart-block').length).toBe(0);
  });
});
