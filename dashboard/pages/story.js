import { block } from '../lib/chart.js';
import { h } from '../lib/dom.js';
import { fmtDate } from '../lib/format.js';
import { footer } from '../lib/status.js';

const PR_URL = 'https://github.com/D10Scot/Dispatcharr/pull/';

function unix(iso) {
  return Math.floor(new Date(`${iso}T00:00:00Z`).getTime() / 1000);
}

export function render(site, root) {
  root.replaceChildren();
  const byId = Object.fromEntries(Object.values(site.groups).flat().map((m) => [m.id, m]));
  for (const p of site.phases) {
    const when = p.end ? `${fmtDate(p.start)} – ${fmtDate(p.end)}` : p.start ? `from ${fmtDate(p.start)}` : 'not started';
    const opts = p.start ? { shade: { from: unix(p.start), to: p.end ? unix(p.end) + 86399 : null } } : {};
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
}
