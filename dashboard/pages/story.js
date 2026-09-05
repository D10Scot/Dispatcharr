import { block, mountAll, unix } from '../lib/chart.js';
import { h } from '../lib/dom.js';
import { fmtDate } from '../lib/format.js';
import { footer } from '../lib/status.js';

const PR_URL = 'https://github.com/D10Scot/Dispatcharr/pull/';

export function render(site, root) {
  root.replaceChildren();
  const byId = Object.fromEntries(Object.values(site.groups).flat().map((m) => [m.id, m]));
  for (const p of site.phases) {
    const when = p.end ? `${fmtDate(p.start)} – ${fmtDate(p.end)}` : p.start ? `from ${fmtDate(p.start)}` : 'not started';
    // Restrict marks to this phase's own milestones — every other phase's
    // milestones would otherwise paper the chart and bury the shade.
    const opts = { milestones: p.milestones };
    if (p.start) opts.shade = { from: unix(p.start), to: p.end ? unix(p.end) + 86399 : null };
    const section = h('section', { class: 'story-phase', id: p.id },
      h('h2', { text: p.label }),
      h('div', { class: 'when', text: when }),
      h('p', { text: p.summary }),
      h('ul', {}, p.milestones.map((m) => h('li', {},
        `${fmtDate(m.date)} · ${m.label}`,
        m.pr ? [' (', h('a', { href: `${PR_URL}${m.pr}`, text: `#${m.pr}` }), ')'] : null,
        ` — ${m.summary}`))),
      h('div', { class: 'chart-grid' }, p.headline_ids.filter((id) => byId[id]).map((id) => block(byId[id], 'daily', site, opts))));
    root.append(section);
  }
  root.append(footer(site));
  // See explore.js's comment: charts must be drawn only after every .plot
  // is actually attached under root, or clientWidth reads as 0.
  mountAll(root);
}
