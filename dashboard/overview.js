// Overview view: "now vs baseline" big-number cards with sparklines, one
// per numeric metric across every discovered family.

(async function () {
  const { loadAllFamilies, flattenMetrics, shortSha, formatNumber } = window.MetricsData;
  const container = document.getElementById("cards");

  const families = await loadAllFamilies();
  const familyNames = Object.keys(families);

  if (familyNames.length === 0) {
    container.innerHTML = '<p class="empty">No metric data found yet.</p>';
    return;
  }

  container.innerHTML = "";

  for (const family of familyNames) {
    const rows = families[family];
    if (rows.length === 0) continue;

    const baseline = rows[0];
    const latest = rows[rows.length - 1];
    const baselineFlat = flattenMetrics(baseline.metrics);
    const latestFlat = flattenMetrics(latest.metrics);

    // Sparkline series per metric key across the full history.
    const seriesByKey = {};
    for (const row of rows) {
      const flat = flattenMetrics(row.metrics);
      for (const [key, value] of Object.entries(flat)) {
        (seriesByKey[key] = seriesByKey[key] || []).push(value);
      }
    }

    for (const key of Object.keys(latestFlat)) {
      const card = document.createElement("div");
      card.className = "card";

      const nowVal = latestFlat[key];
      const baseVal = baselineFlat[key];
      let deltaHtml = "";
      if (typeof baseVal === "number" && typeof nowVal === "number") {
        const diff = nowVal - baseVal;
        const cls = diff === 0 ? "" : diff > 0 ? "up" : "down";
        const sign = diff > 0 ? "+" : "";
        deltaHtml = `<div class="delta ${cls}">${sign}${formatNumber(diff)} vs baseline (${shortSha(baseline.commit_sha)})</div>`;
      }

      card.innerHTML = `
        <div class="label">${family} · ${key}</div>
        <div class="value">${formatNumber(nowVal)}</div>
        ${deltaHtml}
        <div class="spark" id="spark-${family}-${key}"></div>
      `;
      container.appendChild(card);

      const sparkData = seriesByKey[key];
      const sparkEl = card.querySelector(".spark");
      if (window.uPlot && sparkData && sparkData.length > 1) {
        const xs = sparkData.map((_, i) => i);
        try {
          new uPlot(
            {
              width: sparkEl.clientWidth || 200,
              height: 40,
              cursor: { show: false },
              legend: { show: false },
              axes: [{ show: false }, { show: false }],
              scales: { x: { time: false } },
              series: [{}, { stroke: "#4da3ff", width: 1.5 }],
            },
            [xs, sparkData],
            sparkEl
          );
        } catch (err) {
          console.warn("sparkline render failed", key, err);
        }
      }
    }
  }

  if (container.children.length === 0) {
    container.innerHTML = '<p class="empty">No numeric metrics found across families.</p>';
  }
})();
