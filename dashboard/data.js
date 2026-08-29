// Shared data-loading utilities for the metrics dashboard.
//
// Families are discovered dynamically from `data/manifest.json` (a plain
// JSON array of family names, generated at publish time from whatever
// `*.jsonl` files exist on the `metrics-data` branch) rather than
// hard-coded, so new families (e.g. added by a parallel M2 effort) show up
// without a dashboard code change.

const DATA_DIR = "data";

/**
 * Fetch the manifest listing available metric families. Falls back to an
 * empty list (rather than throwing) so the dashboard still renders -
 * gracefully empty - if the manifest is missing.
 */
async function loadManifest() {
  try {
    const res = await fetch(`${DATA_DIR}/manifest.json`, { cache: "no-store" });
    if (!res.ok) return [];
    const families = await res.json();
    return Array.isArray(families) ? families : [];
  } catch (err) {
    console.warn("could not load manifest.json", err);
    return [];
  }
}

/**
 * Fetch and parse one family's JSONL file into an array of rows, sorted by
 * timestamp ascending. Missing families (e.g. not yet produced by a
 * sibling collector effort) resolve to an empty array instead of throwing.
 */
async function loadFamily(family) {
  try {
    const res = await fetch(`${DATA_DIR}/${family}.jsonl`, { cache: "no-store" });
    if (!res.ok) return [];
    const text = await res.text();
    const rows = text
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      })
      .filter(Boolean);
    rows.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    return rows;
  } catch (err) {
    console.warn(`could not load family ${family}`, err);
    return [];
  }
}

/** Load every family discovered in the manifest. Returns {family: rows[]}. */
async function loadAllFamilies() {
  const families = await loadManifest();
  const entries = await Promise.all(
    families.map(async (family) => [family, await loadFamily(family)])
  );
  return Object.fromEntries(entries);
}

async function loadMilestones() {
  try {
    const res = await fetch("milestones.json", { cache: "no-store" });
    if (!res.ok) return [];
    return await res.json();
  } catch (err) {
    console.warn("could not load milestones.json", err);
    return [];
  }
}

/**
 * Flatten a metrics object into {key: number} pairs suitable for charting.
 * Nested plain objects (e.g. `loc_per_app`) are flattened with a
 * `parent.child` key so each leaf becomes its own series; arrays and
 * non-numeric leaves are skipped (they don't chart meaningfully as a
 * single scalar series).
 */
function flattenMetrics(metrics, prefix = "") {
  const out = {};
  for (const [key, value] of Object.entries(metrics || {})) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value === null || value === undefined) continue;
    if (typeof value === "number") {
      out[path] = value;
    } else if (
      typeof value === "object" &&
      !Array.isArray(value)
    ) {
      Object.assign(out, flattenMetrics(value, path));
    }
    // strings, booleans, arrays: skipped for charting purposes
  }
  return out;
}

function shortSha(sha) {
  return typeof sha === "string" ? sha.slice(0, 8) : sha;
}

function formatNumber(n) {
  if (typeof n !== "number" || !Number.isFinite(n)) return String(n);
  return Number.isInteger(n) ? n.toLocaleString() : n.toFixed(2);
}

window.MetricsData = {
  loadManifest,
  loadFamily,
  loadAllFamilies,
  loadMilestones,
  flattenMetrics,
  shortSha,
  formatNumber,
};
