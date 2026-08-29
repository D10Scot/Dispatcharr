// Trends view: time-series per family, one chart per numeric metric, with
// vertical milestone annotations read from milestones.json.

(async function () {
  const { loadAllFamilies, loadMilestones, flattenMetrics, shortSha } = window.MetricsData;
  const container = document.getElementById("families");

  const [families, milestones] = await Promise.all([loadAllFamilies(), loadMilestones()]);
  const familyNames = Object.keys(families);

  if (familyNames.length === 0) {
    container.innerHTML = '<p class="empty">No metric data found yet.</p>';
    return;
  }

  container.innerHTML = "";

  const milestoneByFullSha = new Map((milestones || []).map((m) => [m.commit_sha, m]));

  for (const family of familyNames) {
    const rows = families[family];
    const section = document.createElement("section");
    section.className = "family";

    const heading = document.createElement("h2");
    heading.textContent = family;
    section.appendChild(heading);

    if (rows.length === 0) {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = "No rows for this family yet.";
      section.appendChild(p);
      container.appendChild(section);
      continue;
    }

    const timestamps = rows.map((r) => Math.floor(new Date(r.timestamp).getTime() / 1000));

    // Union of numeric keys across all rows (a metric may appear only in
    // later rows, e.g. a collector that added a field).
    const keys = new Set();
    const flatRows = rows.map((r) => flattenMetrics(r.metrics));
    flatRows.forEach((flat) => Object.keys(flat).forEach((k) => keys.add(k)));

    const grid = document.createElement("div");
    grid.className = "chart-grid";
    section.appendChild(grid);

    // Milestone x-positions (unix seconds) that fall within this family's
    // commit history, matched by commit_sha (rows may carry short or full
    // SHAs from different collectors).
    const milestoneMarks = [];
    rows.forEach((row, i) => {
      const m = [...milestoneByFullSha.values()].find(
        (cand) =>
          row.commit_sha &&
          (row.commit_sha === cand.commit_sha || cand.commit_sha.startsWith(row.commit_sha) || row.commit_sha.startsWith(cand.commit_sha))
      );
      if (m) milestoneMarks.push({ x: timestamps[i], label: m.label });
    });

    if (milestoneMarks.length > 0) {
      const note = document.createElement("p");
      note.className = "milestone-note";
      note.textContent = "Milestones: " + milestoneMarks.map((m) => m.label).join(" · ");
      section.appendChild(note);
    }

    for (const key of keys) {
      const values = flatRows.map((flat) => (typeof flat[key] === "number" ? flat[key] : null));
      if (values.every((v) => v === null)) continue;

      const block = document.createElement("div");
      block.className = "chart-block";
      const h3 = document.createElement("h3");
      h3.textContent = key;
      block.appendChild(h3);
      const chartDiv = document.createElement("div");
      block.appendChild(chartDiv);
      grid.appendChild(block);

      if (!window.uPlot) continue;

      const plugins = [];
      if (milestoneMarks.length > 0) {
        plugins.push({
          hooks: {
            draw: [
              (u) => {
                const ctx = u.ctx;
                ctx.save();
                ctx.strokeStyle = "#9aa3b2";
                ctx.setLineDash([4, 3]);
                ctx.lineWidth = 1;
                for (const mark of milestoneMarks) {
                  const xPos = u.valToPos(mark.x, "x", true);
                  if (xPos < u.bbox.left || xPos > u.bbox.left + u.bbox.width) continue;
                  ctx.beginPath();
                  ctx.moveTo(xPos, u.bbox.top);
                  ctx.lineTo(xPos, u.bbox.top + u.bbox.height);
                  ctx.stroke();
                }
                ctx.restore();
              },
            ],
          },
        });
      }

      try {
        new uPlot(
          {
            width: 400,
            height: 220,
            cursor: { sync: { key: "trends" } },
            scales: { x: { time: true } },
            series: [
              {
                label: "time",
                value: (u, ts) => new Date(ts * 1000).toISOString().slice(0, 10),
              },
              { label: key, stroke: "#4da3ff", width: 2 },
            ],
            plugins,
          },
          [timestamps, values],
          chartDiv
        );
      } catch (err) {
        console.warn("chart render failed", family, key, err);
      }
    }

    if (grid.children.length === 0) {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = "No numeric metrics found in this family.";
      section.appendChild(p);
    }

    container.appendChild(section);
  }
})();
