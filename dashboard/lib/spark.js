// SVG path data for the soft background trend on a tile. Pure; no DOM.
// A null breaks the line (a real gap), which is why the path can carry
// several M commands; the area follows the same segments.

export function paths(values, width, height) {
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
  if (pts.length === 0) return { line: '', area: '' };
  const n = Math.max(values.length - 1, 1);
  const vals = pts.map(([, v]) => v);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo || 1;
  const x = (i) => (values.length === 1 ? width : (i / n) * width);
  const y = (v) => (hi === lo ? height / 2 : height - ((v - lo) / span) * height);

  const segments = [];
  let current = [];
  values.forEach((v, i) => {
    if (v === null || v === undefined) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push([x(i), y(v)]);
    }
  });
  if (current.length) segments.push(current);

  const line = segments
    .map((seg) => seg.map(([px, py], j) => `${j === 0 ? 'M' : 'L'}${r(px)},${r(py)}`).join(' '))
    .join(' ');
  const area = segments
    .map((seg) => {
      const first = seg[0];
      const last = seg[seg.length - 1];
      const body = seg.map(([px, py], j) => `${j === 0 ? 'M' : 'L'}${r(px)},${r(py)}`).join(' ');
      return `${body} L${r(last[0])},${height} L${r(first[0])},${height} Z`;
    })
    .join(' ');
  return { line, area };
}

function r(n) {
  return Math.round(n * 100) / 100;
}
