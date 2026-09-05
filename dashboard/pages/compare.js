// Milestone-to-milestone comparison table: pick any two milestones, see every
// catalogued metric's value at each and the delta between them.
import { GROUP_ORDER, rowsFor } from '../lib/compare.js';
import { h } from '../lib/dom.js';
import { fmt, fmtDate, fmtDelta, shortSha } from '../lib/format.js';
import { footer, GROUP_LABELS } from '../lib/status.js';

export function render(site, root, params = new URLSearchParams('')) {
  const ms = site.milestones;
  const shas = new Set(ms.map((m) => m.sha));
  // A sha named in the query but not in site.milestones (stale link, typo)
  // falls back to the default rather than rendering a select with no
  // matching option and a table for a pair that doesn't exist.
  const fromParam = params.get('from');
  const toParam = params.get('to');
  const from = fromParam && shas.has(fromParam) ? fromParam : ms[0].sha;
  const to = toParam && shas.has(toParam) ? toParam : ms[ms.length - 1].sha;
  root.replaceChildren();

  const option = (m, value) => h('option', {
    value: m.sha, selected: m.sha === value ? 'selected' : null,
    text: `${fmtDate(m.date)} · ${m.label} (${shortSha(m.sha)})`,
  });
  const navigate = (e) => {
    const el = e.target.form;
    if (el.requestSubmit) el.requestSubmit(); else el.submit();
  };
  const select = (name, value) => h('select', { name, onchange: navigate }, ms.map((m) => option(m, value)));
  const form = h('form', { class: 'toolbar', method: 'get' },
    h('span', { text: 'From' }), select('from', from),
    h('span', { text: 'to' }), select('to', to),
    h('button', { type: 'submit', text: 'Compare' }),
    h('button', { type: 'button', text: 'Print', onclick: () => window.print() }));
  root.append(form);

  const rows = rowsFor(site, from, to);
  const table = h('table', {}, h('thead', {}, h('tr', {},
    h('th', { text: 'Metric' }),
    h('th', { text: `at ${shortSha(from)}` }),
    h('th', { text: `at ${shortSha(to)}` }),
    h('th', { text: 'Delta' }))));
  const body = h('tbody');
  for (const g of GROUP_ORDER) {
    const inGroup = rows.filter((r) => r.group === g);
    if (inGroup.length === 0) continue;
    body.append(h('tr', {}, h('th', { class: 'group', colspan: '4', text: GROUP_LABELS[g] })));
    for (const r of inGroup) {
      const cls = r.good === true ? 'good' : r.good === false ? 'bad' : '';
      body.append(h('tr', {},
        h('td', { text: r.label }),
        h('td', { class: 'n', text: fmt(r.from, r.unit) }),
        h('td', { class: 'n', text: fmt(r.to, r.unit) }),
        h('td', { class: `n delta ${cls}`.trim(), text: fmtDelta(r.delta, r.unit) })));
    }
  }
  if (rows.length === 0) body.append(h('tr', {}, h('td', { colspan: '4', class: 'empty', text: 'No metrics in the catalogue.' })));
  table.append(body);
  root.append(table, footer(site));
}
