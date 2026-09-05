// uPlot wrappers plus the pure series builders the tests exercise.
import { h } from './dom.js';
import { fmt, shortSha } from './format.js';

const DAY = 86400;

export function unix(iso) {
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
  const last = Math.max(...xs);
  const lo = first - (first % DAY); // milestones carry a date, not a time: compare from the day's start
  const hi = last - (last % DAY) + DAY - 1; // ...through the end of the last x's calendar day
  return (site.milestones || [])
    .map((m) => ({ x: unix(m.date), label: m.label }))
    .filter((m) => m.x >= lo && m.x <= hi);
}

// Elements built by block() below whose uPlot instantiation is still
// pending — block() writes the .plot div and its data attributes
// synchronously (so jsdom tests see them immediately) but must not read
// clientWidth or construct uPlot until the element is actually attached to
// the document, which only happens once the caller (a page's render())
// appends it. Call mountAll() once, after the page has finished appending
// everything to root, to draw every chart at its real width.
const pending = new WeakMap();

// `block(metric, mode, site, opts)` builds the `.chart-block` (h3, note,
// `.plot` with `data-points`/`data-shade`) without touching layout; the
// actual uPlot draw is deferred to mountAll().
export function block(metric, mode, site, opts = {}) {
  const { xs, ys, labels } = seriesFor(metric, mode);
  const attrs = { class: 'plot', 'data-points': String(xs.length) };
  let shade = null;
  if (opts.shade) {
    const to = opts.shade.to !== null && opts.shade.to !== undefined
      ? opts.shade.to
      : (xs.length ? xs[xs.length - 1] : opts.shade.from);
    shade = { from: opts.shade.from, to };
    attrs['data-shade'] = `${shade.from}..${shade.to}`;
  }
  const plot = h('div', attrs);
  const el = h('div', { class: 'chart-block', 'data-id': metric.id },
    h('h3', { text: metric.label }),
    h('p', { class: 'note', text: metric.note || '' }),
    plot);
  pending.set(plot, () => draw(plot, metric, mode, site, xs, ys, labels, shade));
  return el;
}

// Call once per page render, after every block() has been appended
// somewhere under `root` and `root` itself is attached to the document —
// draws (or, in a non-browser test environment, no-ops) every chart at its
// real, laid-out width.
export function mountAll(root) {
  for (const plot of root.querySelectorAll('.plot')) {
    const fn = pending.get(plot);
    if (fn) { fn(); pending.delete(plot); }
  }
}

function draw(plot, metric, mode, site, xs, ys, labels, shade) {
  if (typeof window === 'undefined' || !window.uPlot || xs.length === 0) return null;
  const marks = milestoneMarks(site, xs);
  const uplotOpts = {
    width: Math.max(plot.clientWidth, 320),
    height: 160,
    tzDate: (ts) => window.uPlot.tzDate(new Date(ts * 1e3), 'Etc/UTC'),
    scales: { x: { time: true } },
    axes: [{ grid: { show: false } }, { size: 56 }],
    series: [
      {
        label: mode === 'commits' ? 'commit' : 'day',
        value: (u, v, sidx, idx) => {
          const date = new Date(v * 1000).toISOString().slice(0, 10);
          return mode === 'commits' ? `${labels[idx]} · ${date}` : date;
        },
      },
      {
        label: metric.label,
        stroke: cssVar('--accent'),
        width: 1.5,
        spanGaps: false,
        points: { show: mode === 'commits' },
        value: (u, v) => fmt(v, metric.unit),
      },
    ],
    hooks: {
      // Paint the phase-window shade first, under the series.
      drawClear: [(u) => {
        if (!shade) return;
        const ctx = u.ctx;
        const x0 = Math.max(u.valToPos(shade.from, 'x', true), u.bbox.left);
        const x1 = Math.min(u.valToPos(shade.to, 'x', true), u.bbox.left + u.bbox.width);
        if (x1 <= x0) return;
        ctx.save();
        ctx.fillStyle = cssVar('--accent');
        ctx.globalAlpha = 0.08;
        ctx.fillRect(x0, u.bbox.top, x1 - x0, u.bbox.height);
        ctx.restore();
      }],
      // Dashed milestone lines on top, after the series is drawn.
      draw: [(u) => {
        const ctx = u.ctx;
        ctx.save();
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
  const u = new window.uPlot(uplotOpts, [xs, ys], plot);
  observeResize(plot, u);
  return u;
}

function observeResize(plot, u) {
  const resize = () => {
    const width = plot.clientWidth;
    if (width > 0) u.setSize({ width, height: 160 });
  };
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(resize).observe(plot);
  } else {
    window.addEventListener('resize', resize);
  }
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#4da3ff';
}
