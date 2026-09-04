import { h } from '../lib/dom.js';
import { footer, GROUP_LABELS, phaseStrip, tile } from '../lib/status.js';
import { GROUP_ORDER } from '../lib/compare.js';

export function render(site, root) {
  root.replaceChildren();
  root.append(phaseStrip(site));
  const baselineDate = site.meta.baseline.date;
  const byGroup = {};
  for (const m of site.headline) (byGroup[m.group] ||= []).push(m);
  for (const g of GROUP_ORDER) {
    if (!byGroup[g]) continue;
    root.append(h('div', { class: 'grp', text: GROUP_LABELS[g] }));
    root.append(h('div', { class: 'tiles' }, byGroup[g].map((m) => tile(withSince(m, baselineDate)))));
  }
  root.append(footer(site));
}

// See lib/status.js's contextLine() doc comment: site.json metrics carry
// `daily` (whose first point is `since`) but not `since` itself, so the page
// decorates each metric before handing it to tile().
function withSince(m, baselineDate) {
  const since = m.daily && m.daily.length ? m.daily[0][0] : null;
  return { ...m, since, baseline_date: baselineDate };
}
