import { beforeEach, describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
import { render } from '../pages/compare.js';

// Literal, not read from the fixture: pins the addendum's constants so a
// fixture edit that silently reordered milestones would fail this test
// rather than silently comparing the wrong pair.
const A = 'fd413f0cc4ab3131789a68fb31f1ae622ae7371a';
const B = '75a68555b931e7d088bfbbd859b35e6e27064312';

describe('compare page', () => {
  let root;
  beforeEach(() => { document.body.innerHTML = '<main id="root"></main>'; root = document.getElementById('root'); });

  it('defaults to baseline -> latest milestone and marks deltas', () => {
    render(site, root, new URLSearchParams(''));
    const form = root.querySelector('form');
    expect(form.getAttribute('method')).toBe('get');
    const selects = root.querySelectorAll('select');
    expect(selects[0].getAttribute('name')).toBe('from');
    expect(selects[1].getAttribute('name')).toBe('to');
    expect(selects[0].value).toBe(A);
    expect(selects[1].value).toBe(B);

    // Every catalogue metric appears in the precomputed pair (5 rows); group
    // header rows share the same tbody but carry no td.delta.
    const deltas = [...root.querySelectorAll('td.delta')];
    expect(deltas.length).toBe(5);

    const rows = [...root.querySelectorAll('tbody tr')];
    const e2e = rows.find((r) => r.textContent.includes('E2E scenarios'));
    expect(e2e.querySelector('td.delta').classList.contains('good')).toBe(true);
    expect(e2e.querySelector('td.delta').textContent).toBe('+249');

    const rev = rows.find((r) => r.textContent.includes('Reverse imports'));
    const revDelta = rev.querySelector('td.delta');
    expect(revDelta.textContent).toBe('±0');
    expect(revDelta.classList.contains('good')).toBe(false);
    expect(revDelta.classList.contains('bad')).toBe(false);

    // codeql_open_critical_high has no value at the baseline sha: both the
    // "from" cell and the delta must fall back to the null placeholder.
    const codeql = rows.find((r) => r.textContent.includes('Open CodeQL'));
    expect(codeql.querySelectorAll('td.n')[0].textContent).toBe('—');
    expect(codeql.querySelector('td.delta').textContent).toBe('—');

    expect([...root.querySelectorAll('th.group')].map((t) => t.textContent))
      .toEqual(['Safety net', 'Security', 'Extraction readiness', 'Delivery']);
  });

  it('accepts ?from=&to= and falls back to derived rows when reversed', () => {
    render(site, root, new URLSearchParams(`from=${B}&to=${A}`));
    const selects = root.querySelectorAll('select');
    expect(selects[0].value).toBe(B);
    expect(selects[1].value).toBe(A);

    const firstDelta = root.querySelector('td.delta');
    expect(firstDelta.textContent).toBe('−249');
    expect(firstDelta.classList.contains('bad')).toBe(true);

    expect([...root.querySelectorAll('th.group')].map((t) => t.textContent))
      .toEqual(['Safety net', 'Security', 'Extraction readiness', 'Delivery']);
  });

  it('falls back to the default pair when a query sha is not a known milestone', () => {
    render(site, root, new URLSearchParams('from=deadbeef'));
    const selects = root.querySelectorAll('select');
    expect(selects[0].value).toBe(A);
    expect(selects[1].value).toBe(B);
    expect(root.querySelectorAll('td.delta').length).toBe(5);
  });
});
