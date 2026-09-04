// Shared visual pieces: the headline tile, the phase strip, the footer.
import { h, svg } from './dom.js';
import { fmt, fmtDate, fmtDelta, shortSha, statusClass } from './format.js';
import { paths } from './spark.js';

export const GROUP_LABELS = {
  safety_net: 'Safety net', security: 'Security', extraction: 'Extraction readiness',
  delivery: 'Delivery', agents: 'Agent pipeline',
};

const SPARK_W = 200;
const SPARK_H = 60;

// `m.since`/`m.baseline_date` are optional decorations a page adds before
// calling tile()/contextLine() (see pages/overview.js's withSince()) — real
// site.json metric objects don't carry a `since` field, only `daily`, which
// is padded with nulls back to the baseline date, so `since` (the first
// non-null point) can differ from meta.baseline.date. When it does, "since
// baseline" is misleading (at_baseline is the value at since, not at the
// baseline date — see site-contract.md), so the line names the date instead.
// Absent those fields, this falls back to "since baseline" unchanged.
export function contextLine(m) {
  if (m.now === null || m.now === undefined) {
    return m.stale && m.last_real ? `stale since ${fmtDate(m.last_real)}` : 'no data yet';
  }
  const parts = [];
  const target = m.direction === 'zero' ? 0 : m.target;
  if (target !== null && target !== undefined && m.direction !== 'info') parts.push(`target ${fmt(target, m.unit)}`);
  if (m.at_baseline !== null && m.at_baseline !== undefined) {
    const sinceDiffersFromBaseline = m.since && m.baseline_date && m.since !== m.baseline_date;
    const label = sinceDiffersFromBaseline ? `since ${fmtDate(m.since)}` : 'since baseline';
    parts.push(`${fmtDelta(m.now - m.at_baseline, m.unit)} ${label}`);
  }
  if (m.stale && m.last_real) parts.push(`stale since ${fmtDate(m.last_real)}`);
  return parts.join(' · ');
}

export function tile(m) {
  const cls = statusClass(m.status);
  const { line, area } = paths(m.spark || [], SPARK_W, SPARK_H);
  const bg = svg('svg', { viewBox: `0 0 ${SPARK_W} ${SPARK_H}`, preserveAspectRatio: 'none', 'aria-hidden': 'true' },
    area && svg('path', { class: 'area', d: area }),
    line && svg('path', { class: 'line', d: line }));
  return h('div', { class: `tile ${cls}`, 'data-id': m.id, title: m.note || '' },
    bg,
    h('div', { class: 'l', text: m.label }),
    h('div', { class: 'v', text: fmt(m.now, m.unit) }),
    h('div', { class: 'd', text: contextLine(m) }));
}

// Percent position of a milestone within its phase's date window (start to
// end, or to today for the still-open current phase). Positioning dots this
// way — rather than by CSS `:nth-of-type(n)` — matters because nth-of-type
// also counts the .name/.muted spans in the same phase element, which shifts
// every dot's offset by two slots.
function milestonePercent(phase, ms, today) {
  if (!phase.start) return 0;
  const start = Date.parse(phase.start);
  const end = Date.parse(phase.end || today);
  const span = end - start;
  if (!span) return 0;
  const at = Date.parse(ms.date);
  return Math.min(100, Math.max(0, ((at - start) / span) * 100));
}

export function phaseStrip(site) {
  const today = site.meta.today;
  return h('div', { class: 'phases' }, site.phases.map((p) => {
    const done = p.end !== null && p.end !== undefined;
    const cur = !done && p.start && p.start <= today;
    const cls = `phase${done ? ' done' : ''}${cur ? ' cur' : ''}`;
    return h('div', { class: cls, title: p.summary },
      p.milestones.map((ms) => h('span', {
        class: `m ${ms.kind}`,
        style: `left: ${milestonePercent(p, ms, today)}%`,
        title: `${ms.label}${ms.pr ? ` (#${ms.pr})` : ''}: ${ms.summary}`,
      })),
      h('span', { class: 'name', text: p.label }),
      h('span', { class: 'muted', text: done ? `${fmtDate(p.start)} – ${fmtDate(p.end)}` : cur ? 'now' : '' }));
  }));
}

export function footer(site) {
  const fresh = Object.entries(site.meta.freshness || {}).map(([k, v]) => `${k} ${v.slice(0, 16).replace('T', ' ')}`).join(' · ');
  const notes = (site.meta.source_notes || []).join(' · ');
  return h('div', { class: 'foot' },
    h('span', { text: `Data as of: ${fresh || 'none'}${notes ? ` · ⚠ ${notes}` : ''}` }),
    h('span', { text: `baseline ${shortSha(site.meta.baseline.sha)} · ${site.meta.commit_count} commits · built ${site.meta.built_at.slice(0, 16).replace('T', ' ')} UTC` }));
}
