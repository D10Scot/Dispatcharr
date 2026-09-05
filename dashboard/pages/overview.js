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
// `daily` but not `since` itself, so the page decorates each metric before
// handing it to tile(). `daily` is padded with nulls back to the baseline
// date (so every series lines up on the same x-axis) — `daily[0][0]` is
// therefore always the baseline date, never the metric's real `since`.
// `since` is the date of the first NON-NULL point (null when the series has
// no real data at all).
function withSince(m, baselineDate) {
  const real = (m.daily || []).find(([, v]) => v !== null && v !== undefined);
  return { ...m, since: real ? real[0] : null, baseline_date: baselineDate };
}
