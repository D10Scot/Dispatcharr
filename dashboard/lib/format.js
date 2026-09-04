// Number, date and status formatting. Pure; no DOM.

const STATUSES = new Set(['good', 'bad', 'neutral', 'stale']);

export function fmt(value, unit) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  switch (unit) {
    case 'pct': return `${round(value, 1)}%`;
    case 'ratio': return `${Math.round(value * 100)}%`;
    case 'seconds': return fmtSeconds(value);
    case 'days': return `${Math.round(value)} d`;
    case 'score': return String(round(value, 1));
    default: return Number.isInteger(value) ? value.toLocaleString('en-GB') : String(round(value, 2));
  }
}

function fmtSeconds(s) {
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${round(s / 3600, 1)}h`;
  return `${round(s / 86400, 1)}d`;
}

export function fmtDelta(delta, unit) {
  if (delta === null || delta === undefined) return '—';
  if (delta === 0) return '±0';
  const sign = delta > 0 ? '+' : '−';
  const abs = Math.abs(delta);
  if (unit === 'pct') return `${sign}${round(abs, 1)} pt`;
  if (unit === 'ratio') return `${sign}${Math.round(abs * 100)} pt`;
  return `${sign}${fmt(abs, unit)}`;
}

export function shortSha(sha) {
  return typeof sha === 'string' ? sha.slice(0, 8) : '';
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function fmtDate(iso) {
  // Fixed abbreviations: ICU's en-GB short month is "Sept", which drifts by Node version.
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

export function statusClass(status) {
  return STATUSES.has(status) ? status : 'neutral';
}

function round(n, places) {
  const f = 10 ** places;
  return Math.round(n * f) / f;
}
