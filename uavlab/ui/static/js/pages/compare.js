// Compare runs: KPI table with differences to a baseline, overlaid signals, energy breakdown.
import { h, clear, api, state, fmt, statusChip, seriesColor } from "../core.js";
import { timeChart } from "../charts.js";

const KPIS = [
  ["status", "Status", null], ["E_batt_Wh", "Battery energy", "Wh"], ["Wh_per_km", "Energy per km", "Wh/km"],
  ["mission_E_Wh", "Mission-leg energy", "Wh"], ["mission_Wh_per_km", "Mission-leg energy per km", "Wh/km"],
  ["flight_time_s", "Flight time", "s"], ["dist_ground_km", "Ground distance", "km"], ["soc_end", "SOC at end", "–"],
  ["mean_P_batt_air_W", "Mean power in the air", "W"], ["max_i_batt_A", "Peak battery current", "A"],
  ["min_cell_v", "Minimum cell voltage", "V"], ["energy_breakdown_Wh.wind_work", "Wind work", "Wh"],
  ["eta.propeller", "Propeller efficiency", "–"], ["tracking.xtrack_rms_steady_m", "Cross-track RMS (steady)", "m"],
  ["touchdown.sink_mps", "Touchdown sink rate", "m/s"],
];
const get = (o, p) => p.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);

export async function render(main) {
  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Compare runs"),
    h("div", { class: "sub" }, "Side-by-side KPIs with differences to the first run (the baseline) and overlaid signals. Select runs on the Results page.")),
    h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => { state.compare.length = 0; state.emit("compare"); render(clear(main)); } }, "Clear selection"))));
  if (state.compare.length < 1) { main.append(h("div", { class: "empty" }, "No runs selected. Tick runs on the ", h("a", { href: "#/results" }, "Results"), " page.")); return; }
  const runs = [];
  for (const ref of state.compare) { try { runs.push(await api(`/api/run?ref=${encodeURIComponent(ref)}`)); } catch (_) {} }
  const disposers = [];
  // KPI table
  const t = h("table", { class: "tbl" });
  t.append(h("thead", {}, h("tr", {}, h("th", {}, "KPI"), h("th", {}, "Unit"),
    runs.map((r, i) => h("th", {}, h("span", { style: { color: seriesColor(i) } }, "■ "), r.brief?.label || r.summary.run_id,
      h("button", { class: "btn btn-sm btn-ghost", title: "Remove from comparison",
        onclick: () => { state.compare.splice(state.compare.indexOf(r.ref), 1); render(clear(main)); } }, "×"))))));
  const tb = h("tbody");
  for (const [k, lab, unit] of KPIS) {
    const tr = h("tr", {}, h("td", {}, lab), h("td", { class: "muted" }, unit || ""));
    const base = get(runs[0].summary, k);
    runs.forEach((r, i) => {
      const v = get(r.summary, k);
      if (k === "status") { tr.append(h("td", {}, statusChip(v))); return; }
      let delta = "";
      if (i > 0 && typeof v === "number" && typeof base === "number" && base !== 0) {
        const pct = 100 * (v / base - 1);
        delta = h("span", { class: "hint" }, ` (${pct >= 0 ? "+" : ""}${pct.toFixed(1)} %)`);
      }
      tr.append(h("td", { class: "n" }, typeof v === "number" ? fmt.auto(+v.toPrecision(5)) : (v ?? "–"), delta));
    });
    tb.append(tr);
  }
  t.append(tb);
  main.append(h("div", { class: "panel" }, h("div", { class: "ph" }, "Key performance indicators"), h("div", { class: "pb flush" }, h("div", { class: "tbl-wrap" }, t))));
  // config differences
  const cfgs = await Promise.all(runs.map((r) => api(`/api/run/config?ref=${encodeURIComponent(r.ref)}`).catch(() => ({}))));
  const flat = (o, p = "", out = {}) => { for (const [k, v] of Object.entries(o || {})) { const q = p ? `${p}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) flat(v, q, out); else out[q] = JSON.stringify(v); } return out; };
  const F = cfgs.map((c) => flat(c));
  const keys = [...new Set(F.flatMap((f) => Object.keys(f)))].filter((k) => !k.startsWith("logging.") && new Set(F.map((f) => f[k])).size > 1);
  const dt = h("table", { class: "tbl" }, h("thead", {}, h("tr", {}, h("th", {}, "Parameter"), runs.map((r, i) => h("th", {}, h("span", { style: { color: seriesColor(i) } }, "■ "), r.brief?.label || r.summary.run_id)))),
    h("tbody", {}, keys.map((k) => h("tr", {}, h("td", { class: "mono" }, k), F.map((f) => h("td", { class: "mono small" }, (f[k] ?? "–").slice(0, 80)))))));
  main.append(h("div", { class: "panel", style: { marginTop: "12px" } }, h("div", { class: "ph" }, `Configuration differences (${keys.length})`),
    h("div", { class: "pb flush" }, keys.length ? h("div", { class: "tbl-wrap", style: { maxHeight: "300px" } }, dt) : h("div", { class: "hint", style: { padding: "8px" } }, "Identical configurations."))));
  // overlay
  const sigSel = h("select", { id: "cmp-signal" }, ["P_batt_W", "soc", "E_batt_Wh", "tas_mps", "gs_mps", "alt_agl_m", "tailwind_mps", "P_wind_W", "rpm", "i_batt_A"].map((c) => h("option", { value: c }, c)));
  const box = h("div");
  main.append(h("div", { class: "panel", style: { marginTop: "12px" } }, h("div", { class: "ph" }, "Overlay", h("div", { class: "tools" }, sigSel)), h("div", { class: "pb" }, box)));
  async function overlay() {
    disposers.splice(0).forEach((f) => f()); clear(box);
    const col = sigSel.value;
    const data = await Promise.all(runs.map((r) => api(`/api/run/series?ref=${encodeURIComponent(r.ref)}&cols=${col}&max_points=3000`).catch(() => null)));
    // common time base: resample each run onto the union grid (linear interpolation)
    const tmax = Math.max(...data.filter(Boolean).map((d) => d.t_s[d.t_s.length - 1] || 0));
    const N = 1500, T = Array.from({ length: N }, (_, i) => (i * tmax) / (N - 1));
    const interp = (xs, ys, x) => { if (!xs.length || x > xs[xs.length - 1]) return null; let lo = 0, hi = xs.length - 1;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (xs[m] <= x) lo = m; else hi = m; }
      const f = (x - xs[lo]) / ((xs[hi] - xs[lo]) || 1); return ys[lo] == null || ys[hi] == null ? null : ys[lo] + f * (ys[hi] - ys[lo]); };
    const Y = data.map((d) => (d ? T.map((x) => interp(d.t_s, d[col] || [], x)) : T.map(() => null)));
    const c = timeChart(box, { series: runs.map((r) => ({ label: r.brief?.label || r.summary.run_id })), yLabel: col, height: 300, modes: false, sync: "cmp" });
    c.setData(T, Y); disposers.push(() => c.destroy());
  }
  sigSel.addEventListener("change", overlay);
  overlay();
  return () => disposers.splice(0).forEach((f) => f());
}
