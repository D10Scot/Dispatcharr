// uPlot wrappers plus the pure series builders the tests exercise.
import { h } from './dom.js';
import { shortSha } from './format.js';

const DAY = 86400;

function unix(iso) {
  return Math.floor(new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso).getTime() / 1000);
}

export function seriesFor(metric, mode) {
  if (mode === 'commits') {
    const commits = metric.commits || [];
    return { xs: commits.map((c) => unix(c[1])), ys: commits.map((c) => c[2]), labels: commits.map((c) => shortSha(c[0])) };
  }
  const daily = metric.daily || [];
  return { xs: daily.map((d) => unix(d[0])), ys: daily.map((d) => d[1]), labels: daily.map(() => '') };
}

export function milestoneMarks(site, xs) {
  if (xs.length === 0) return [];
  const first = Math.min(...xs);
  const lo = first - (first % DAY); // milestones carry a date, not a time: compare from the day's start
  const hi = Math.max(...xs) + DAY - 1;
  return (site.milestones || [])
    .map((m) => ({ x: unix(m.date), label: m.label }))
    .filter((m) => m.x >= lo && m.x <= hi);
}

// opts.shade = { from, to } (unix seconds). `to` may be null, meaning "to
// the series' last x" — resolved here so the rendered .plot always carries
// a concrete data-shade range for tests and for the draw hook alike.
export function mount(el, metric, mode, site, { shade: shadeOpt } = {}) {
  const { xs, ys, labels } = seriesFor(metric, mode);
  const attrs = { class: 'plot', 'data-points': String(xs.length) };
  let shade = null;
  if (shadeOpt) {
    const to = shadeOpt.to !== null && shadeOpt.to !== undefined
      ? shadeOpt.to
      : (xs.length ? xs[xs.length - 1] : shadeOpt.from);
    shade = { from: shadeOpt.from, to };
    attrs['data-shade'] = `${shade.from}..${shade.to}`;
  }
  const plot = h('div', attrs);
  el.append(plot);
  if (typeof window === 'undefined' || !window.uPlot || xs.length === 0) return null;
  const marks = milestoneMarks(site, xs);
  const uplotOpts = {
    width: Math.max(el.clientWidth - 24, 320),
    height: 160,
    scales: { x: { time: true } },
    axes: [{ grid: { show: false } }, { size: 56 }],
    series: [
      { label: mode === 'commits' ? 'commit' : 'day', value: (u, v, sidx, idx) => labels[idx] || new Date(v * 1000).toISOString().slice(0, 10) },
      { label: metric.label, stroke: cssVar('--accent'), width: 1.5, spanGaps: false, points: { show: mode === 'commits' } },
    ],
    hooks: {
      draw: [(u) => {
        const ctx = u.ctx;
        ctx.save();
        if (shade) {
          const x0 = Math.max(u.valToPos(shade.from, 'x', true), u.bbox.left);
          const x1 = Math.min(u.valToPos(shade.to, 'x', true), u.bbox.left + u.bbox.width);
          if (x1 > x0) {
            ctx.fillStyle = cssVar('--accent');
            ctx.globalAlpha = 0.08;
            ctx.fillRect(x0, u.bbox.top, x1 - x0, u.bbox.height);
            ctx.globalAlpha = 1;
          }
        }
        ctx.strokeStyle = cssVar('--muted');
        ctx.setLineDash([4, 4]);
        for (const m of marks) {
          const x = u.valToPos(m.x, 'x', true);
          ctx.beginPath(); ctx.moveTo(x, u.bbox.top); ctx.lineTo(x, u.bbox.top + u.bbox.height); ctx.stroke();
        }
        ctx.restore();
      }],
    },
  };
  return new window.uPlot(uplotOpts, [xs, ys], plot);
}

export function block(metric, mode, site, opts = {}) {
  const el = h('div', { class: 'chart-block', 'data-id': metric.id },
    h('h3', { text: metric.label }),
    h('p', { class: 'note', text: metric.note || '' }));
  mount(el, metric, mode, site, opts);
  return el;
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#4da3ff';
}
