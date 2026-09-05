import { beforeEach, describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
import { render } from '../pages/defects.js';

describe('defects page', () => {
  let root;
  beforeEach(() => { document.body.innerHTML = '<main id="root"></main>'; root = document.getElementById('root'); });

  it('groups entries by status and links issue, test and PR', () => {
    render(site, root);
    expect([...root.querySelectorAll('h2')].map((x) => x.textContent)).toEqual(['Pinned by a test (1)', 'Fixed (1)']);

    const pinned = root.querySelector('#status-pinned tbody tr');
    expect(pinned.querySelector('a[href="https://github.com/D10Scot/Dispatcharr/issues/80"]')).not.toBeNull();
    expect(pinned.querySelector('a[href$="e2e/tests/seeded/output-m3u.spec.ts"]')).not.toBeNull();

    const fixed = root.querySelector('#status-fixed tbody tr');
    expect(fixed.querySelector('a[href="https://github.com/D10Scot/Dispatcharr/issues/89"]')).not.toBeNull();
    expect(fixed.querySelector('a[href="https://github.com/D10Scot/Dispatcharr/pull/154"]')).not.toBeNull();

    const bar = root.querySelector('.status-bar');
    expect(bar.querySelector('.pinned').style.width).toBe('50%');
    expect(bar.querySelector('.fixed').style.width).toBe('50%');
  });
});
