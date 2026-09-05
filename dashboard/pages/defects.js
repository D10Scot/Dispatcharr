// The defect ledger: entries grouped by status, with a status-mix bar sized
// from the latest by_status_daily point.
import { h } from '../lib/dom.js';
import { fmtDate } from '../lib/format.js';
import { footer } from '../lib/status.js';

const REPO = 'https://github.com/D10Scot/Dispatcharr';
const ORDER = [['open', 'Open'], ['pinned', 'Pinned by a test'], ['carried', 'Carried as a constraint'], ['fixed', 'Fixed']];

export function render(site, root) {
  root.replaceChildren();
  const daily = site.defects.by_status_daily;
  const latest = daily.length ? daily[daily.length - 1][1] : { open: 0, pinned: 0, carried: 0, fixed: 0 };
  const total = Object.values(latest).reduce((a, b) => a + b, 0) || 1;
  root.append(h('div', { class: 'status-bar', title: ORDER.map(([k, l]) => `${l}: ${latest[k]}`).join(' · ') },
    ORDER.map(([k]) => h('span', { class: k, style: `width:${Math.round((100 * latest[k]) / total)}%` }))));

  for (const [status, label] of ORDER) {
    const entries = site.defects.entries.filter((d) => d.status === status);
    if (entries.length === 0) continue;
    root.append(h('h2', { text: `${label} (${entries.length})` }));
    root.append(h('table', { id: `status-${status}` },
      h('thead', {}, h('tr', {},
        h('th', { text: 'Defect' }), h('th', { text: 'Area' }), h('th', { text: 'Severity' }),
        h('th', { text: 'Evidence' }), h('th', { text: 'Since' }))),
      h('tbody', {}, entries.map((d) => h('tr', {},
        h('td', { text: d.title }), h('td', { text: d.area }), h('td', { text: d.severity }),
        h('td', {}, evidence(d)), h('td', { text: fmtDate(d.status_changed) }))))));
  }
  root.append(footer(site));
}

function evidence(d) {
  const links = [];
  if (d.issue) links.push(h('a', { href: `${REPO}/issues/${d.issue}`, text: `#${d.issue}` }));
  if (d.test) links.push(h('a', { href: `${REPO}/blob/main/${d.test}`, text: d.test.split('/').pop() }));
  if (d.fixed_in) links.push(h('a', { href: `${REPO}/pull/${d.fixed_in}`, text: `PR #${d.fixed_in}` }));
  if (d.carried_as) links.push(h('a', { href: `${REPO}/blob/main/${d.carried_as}`, text: 'spec' }));
  if (!links.length && d.source) links.push(h('a', { href: `${REPO}/blob/main/${d.source}`, text: d.source.split('#')[0].split('/').pop() }));
  return links.flatMap((l, i) => (i ? [' · ', l] : [l]));
}
