// Presentation view: ?from=<sha>&to=<sha> renders a before/after delta
// table per family, for walking through the migration story in a talk.

(async function () {
  const { loadAllFamilies, flattenMetrics, shortSha, formatNumber } = window.MetricsData;
  const container = document.getElementById("story");

  const params = new URLSearchParams(window.location.search);
  const fromParam = params.get("from");
  const toParam = params.get("to");

  const families = await loadAllFamilies();
  const familyNames = Object.keys(families);

  if (familyNames.length === 0) {
    container.innerHTML = '<p class="empty">No metric data found yet.</p>';
    return;
  }

  container.innerHTML = "";

  function findRow(rows, shaParam, fallback) {
    if (!shaParam) return fallback;
    return (
      rows.find(
        (r) => r.commit_sha === shaParam || r.commit_sha.startsWith(shaParam) || shaParam.startsWith(r.commit_sha)
      ) || fallback
    );
  }

  let anyRendered = false;

  for (const family of familyNames) {
    const rows = families[family];
    if (rows.length === 0) continue;

    const fromRow = findRow(rows, fromParam, rows[0]);
    const toRow = findRow(rows, toParam, rows[rows.length - 1]);
    if (!fromRow || !toRow) continue;

    const fromFlat = flattenMetrics(fromRow.metrics);
    const toFlat = flattenMetrics(toRow.metrics);
    const keys = new Set([...Object.keys(fromFlat), ...Object.keys(toFlat)]);
    if (keys.size === 0) continue;

    anyRendered = true;

    const section = document.createElement("section");
    section.className = "family";
    const heading = document.createElement("h2");
    heading.textContent = `${family}: ${shortSha(fromRow.commit_sha)} → ${shortSha(toRow.commit_sha)}`;
    section.appendChild(heading);

    const table = document.createElement("table");
    table.className = "delta-table";
    table.innerHTML = `
      <thead>
        <tr><th>Metric</th><th>Before</th><th>After</th><th>Delta</th></tr>
      </thead>
      <tbody></tbody>
    `;
    const tbody = table.querySelector("tbody");

    for (const key of [...keys].sort()) {
      const before = fromFlat[key];
      const after = toFlat[key];
      let deltaText = "—";
      if (typeof before === "number" && typeof after === "number") {
        const diff = after - before;
        const sign = diff > 0 ? "+" : "";
        deltaText = `${sign}${formatNumber(diff)}`;
      }
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${key}</td>
        <td>${before === undefined ? "—" : formatNumber(before)}</td>
        <td>${after === undefined ? "—" : formatNumber(after)}</td>
        <td>${deltaText}</td>
      `;
      tbody.appendChild(tr);
    }

    section.appendChild(table);
    container.appendChild(section);
  }

  if (!anyRendered) {
    container.innerHTML = '<p class="empty">No matching commits found for the given from/to parameters.</p>';
  }
})();
