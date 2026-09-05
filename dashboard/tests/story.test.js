import { beforeEach, describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
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
    // the headline metric's own last x rather than staying null.
    const shade = phases[0].querySelector('.chart-block .plot').dataset.shade;
    expect(shade.startsWith(`${Math.floor(Date.parse('2026-08-19T00:00:00Z') / 1000)}..`)).toBe(true);

    expect(phases[1].querySelector('.when').textContent).toBe('3 Sep – 3 Sep');
    expect(phases[1].querySelector('li').textContent).toContain('Phase 0 done');
    expect(phases[1].querySelector('li a').getAttribute('href')).toBe('https://github.com/D10Scot/Dispatcharr/pull/155');
    expect(phases[1].querySelector('.chart-block h3').textContent).toBe('Open CodeQL critical + high');

    expect(phases[2].querySelector('.when').textContent).toBe('not started');
    expect(phases[2].querySelectorAll('li').length).toBe(0);
    expect(phases[2].querySelectorAll('.chart-block').length).toBe(0);
  });
});
