// uPlot wrappers plus the pure series builders the tests exercise.
import { h } from './dom.js';
import { fmt, fmtDate, shortSha } from './format.js';

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

// `milestones` defaults to every milestone on `site` (Explore's picture: the
// whole timeline); pass a narrower list — e.g. a single phase's own
// `milestones[]` — to restrict which ones can ever be marked (Story: only
// the current phase's milestones, not every phase's).
export function milestoneMarks(site, xs, milestones = site.milestones) {
  if (xs.length === 0) return [];
  const first = Math.min(...xs);
  const last = Math.max(...xs);
  const lo = first - (first % DAY); // milestones carry a date, not a time: compare from the day's start
  const hi = last - (last % DAY) + DAY - 1; // ...through the end of the last x's calendar day
  return (milestones || [])
    .map((m) => ({ x: unix(m.date), label: m.label }))
    .filter((m) => m.x >= lo && m.x <= hi);
}

// The x-series readout: `sha · date` in commit mode, just the date in daily
// mode. uPlot 1.6.32 calls this with v === null whenever the cursor sits
// off the plot (not just for a genuine data gap) — without the guard that
// rendered `new Date(null * 1000)`, the epoch, as the resting legend value.
export function xReadout(mode, labels, v, idx) {
  if (v === null || v === undefined) return '—';
  const date = new Date(v * 1000).toISOString().slice(0, 10);
  return mode === 'commits' ? `${labels[idx]} · ${date}` : date;
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
// `.plot` with `data-points`/`data-shade`/`data-marks`) without touching
// layout; the actual uPlot draw is deferred to mountAll(). `opts.milestones`
// restricts which milestones can be marked (see milestoneMarks' doc comment)
// — it defaults to every milestone on `site` when omitted.
export function block(metric, mode, site, opts = {}) {
  const { xs, ys, labels } = seriesFor(metric, mode);
  const marks = milestoneMarks(site, xs, opts.milestones);
  const attrs = { class: 'plot', 'data-points': String(xs.length), 'data-marks': String(marks.length) };
  let shade = null;
  if (opts.shade) {
    const to = opts.shade.to !== null && opts.shade.to !== undefined
      ? opts.shade.to
      : (xs.length ? xs[xs.length - 1] : opts.shade.from);
    shade = { from: opts.shade.from, to };
    attrs['data-shade'] = `${shade.from}..${shade.to}`;
  }
  const plot = h('div', attrs);
  // Nothing drawable — no x values at all, or an x for every day but a null
  // at each one (a catalogued metric whose collector has not reported yet).
  // uPlot renders that as an empty 160px box with no hint of why, so say so
  // in words and skip the draw entirely. `data-points` still reports the raw
  // series length: "0" when there are no x values, the day count when the
  // series is all gaps.
  const drawable = ys.some((v) => v !== null && v !== undefined && Number.isFinite(v));
  if (!drawable) plot.append(h('p', { class: 'empty', text: 'no data yet' }));
  const el = h('div', { class: 'chart-block', 'data-id': metric.id },
    h('h3', { text: metric.label }),
    h('p', { class: 'note', text: metric.note || '' }),
    plot);
  if (drawable) pending.set(plot, () => draw(plot, metric, mode, xs, ys, labels, shade, marks));
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

function draw(plot, metric, mode, xs, ys, labels, shade, marks) {
  if (typeof window === 'undefined' || !window.uPlot || xs.length === 0) return null;
  const uplotOpts = {
    width: Math.max(plot.clientWidth, 320),
    height: 160,
    tzDate: (ts) => window.uPlot.tzDate(new Date(ts * 1e3), 'Etc/UTC'),
    scales: { x: { time: true } },
    // uPlot's built-in axis colours are hard-coded near-black: legible on
    // the light theme, all but invisible against the dark theme's panel.
    // Drive stroke, ticks and grid from the same CSS variables the rest of
    // the dashboard uses so both themes get readable axes.
    axes: [
      {
        // uPlot's own tick formatter defaults to US "8/19"; match the rest of
        // the dashboard's date style instead. The year is deliberately left
        // off — the hover readout below already carries the full ISO date.
        stroke: cssVar('--muted'),
        ticks: { stroke: cssVar('--border') },
        grid: { show: false },
        values: (u, splits) => splits.map((ts) => fmtDate(new Date(ts * 1e3).toISOString())),
      },
      {
        size: 56,
        stroke: cssVar('--muted'),
        ticks: { stroke: cssVar('--border') },
        grid: { stroke: cssVar('--border') },
        // Same formatter as the hover legend below, so a y tick and the
        // readout beside it never disagree about units.
        values: (u, splits) => splits.map((v) => fmt(v, metric.unit)),
      },
    ],
    series: [
      { label: mode === 'commits' ? 'commit' : 'day', value: (u, v, sidx, idx) => xReadout(mode, labels, v, idx) },
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
