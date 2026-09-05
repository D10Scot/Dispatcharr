import { block } from '../lib/chart.js';
import { GROUP_ORDER } from '../lib/compare.js';
import { h } from '../lib/dom.js';
import { footer, GROUP_LABELS } from '../lib/status.js';

export function render(site, root, params = new URLSearchParams('')) {
  const mode = params.get('mode') === 'daily' ? 'daily' : 'commits';
  root.replaceChildren();
  root.append(h('div', { class: 'toolbar' },
    h('span', { text: 'Resolution:' }),
    h('a', { href: '?mode=commits', text: 'per commit', class: mode === 'commits' ? 'active' : '' }),
    h('a', { href: '?mode=daily', text: 'daily', class: mode === 'daily' ? 'active' : '' }),
    h('span', { text: '· dashed lines are milestones' })));
  for (const g of GROUP_ORDER) {
    const metrics = site.groups[g] || [];
    if (metrics.length === 0) continue;
    root.append(h('div', { class: 'grp', text: GROUP_LABELS[g] }));
    // Derived series have no per-commit points; show them daily whatever the toggle says.
    root.append(h('div', { class: 'chart-grid' }, metrics.map((m) => block(m, m.commits ? mode : 'daily', site))));
  }
  root.append(footer(site));
}
