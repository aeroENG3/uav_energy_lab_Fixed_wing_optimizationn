// Performance map: steady level flight of the current scenario at several airspeeds,
// cross-checked against the independent trim model; best-range/endurance speeds.
import { h, clear, api, state, fmt, statusChip, toast, set, clone, fill } from "../core.js";
import { xyPlot } from "../charts.js";
import { dataTable } from "../widgets.js";

export async function render(main) {
  let jobId = null, timer = null, disp = [];
  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Performance map"),
    h("div", { class: "sub" }, "Straight-and-level flight of the current aircraft and powertrain at 8 airspeeds (3 in quick mode), flown by the full pipeline and ",
      "checked against an independent trim model. Gives the power curve, best-endurance and best-range speeds, and the P(V) fit used by the wind-aware policy.")),
    h("div", { class: "actions" },
      h("button", { class: "btn", onclick: () => start(true) }, "Quick map (3 speeds)"),
      h("button", { class: "btn btn-primary", onclick: () => start(false) }, "Full map (8 speeds)"))));
  const prog = h("div", { style: { marginBottom: "10px" } });
  const body = h("div");
  main.append(prog, body);

  async function start(quick) {
    try { const j = await api("/api/tools/performance", { config: state.config, quick }); jobId = j.id; toast("Performance map started.", "ok"); poll(); }
    catch (e) { toast(e.message, "alarm"); }
  }
  async function poll() {
    const d = await api(`/api/jobs/${jobId}`);
    fill(prog, h("div", { class: "row" }, statusChip(d.state), h("div", { class: "progress", style: { width: "220px" } }, h("i", { style: { width: `${Math.round(100 * d.progress)}%` } })),
      h("span", { class: "muted mono small" }, d.message)));
    if (["running", "queued"].includes(d.state)) timer = setTimeout(poll, 1500); else load();
  }
  async function load() {
    disp.forEach((f) => f()); disp = []; clear(body);
    const r = await api("/api/performance");
    if (!r.rows?.length) { body.append(h("div", { class: "empty" }, "No performance map yet. Run a quick or full map.")); return; }
    const f = r.fit;
    body.append(h("div", { class: "hint", style: { marginBottom: "8px" } }, r.is_workspace ? "Latest map computed in this workspace." : "Showing the map shipped with the V&V report (default configuration). Run a map to compute it for your scenario."));
    const k = h("div", { class: "kpis", style: { marginBottom: "12px" } },
      ...[["Best-range speed", fmt.n(f.v_best_range_mps, 1), "m/s"], ["Energy at best range", fmt.n(f.Wh_per_km_min, 2), "Wh/km"],
        ["Best-endurance speed", fmt.n(f.v_best_endurance_mps, 1), "m/s"], ["Min. battery power", fmt.n(f.p_min_W, 0), "W"],
        ["Air density", fmt.n(f.density_kgm3, 3), "kg/m³"], ["All-up mass", fmt.n(f.mass_kg, 2), "kg"]]
        .map(([a, b, c]) => h("div", { class: "kpi" }, h("div", { class: "k" }, a), h("div", { class: "v" }, b, h("small", {}, c)))));
    body.append(k);
    const g = h("div", { class: "grid g3" }); body.append(g);
    const c1 = h("div", { class: "panel" }, h("div", { class: "ph" }, "Battery power, level flight"), h("div", { class: "pb" }));
    const c2 = h("div", { class: "panel" }, h("div", { class: "ph" }, "Energy per km, still air"), h("div", { class: "pb" }));
    const c3 = h("div", { class: "panel" }, h("div", { class: "ph" }, "Component efficiency"), h("div", { class: "pb" }));
    g.append(c1, c2, c3);
    const V = r.rows.map((x) => x.sim_tas);
    const vv = Array.from({ length: 80 }, (_, i) => Math.min(...V) + (i * (Math.max(...V) - Math.min(...V))) / 79);
    const P = (v) => f.a * v ** 3 + f.b / v + f.c;
    disp.push(xyPlot(c1.lastChild, { height: 230, xLabel: "true airspeed (m/s)", yLabel: "W", series: [
      { label: "fit a·V³ + b/V + c", points: vv.map((v) => [v, P(v)]) },
      { label: "simulation", mode: "scatter", points: r.rows.map((x) => [x.sim_tas, x.sim_P_batt_W]) },
      { label: "independent model", mode: "scatter", size: 3, points: r.rows.map((x) => [x.sim_tas, x.model_P_batt_W]) }] }).destroy);
    disp.push(xyPlot(c2.lastChild, { height: 230, xLabel: "true airspeed (m/s)", yLabel: "Wh/km", vlines: [{ x: f.v_best_range_mps, label: `best range ${fmt.n(f.v_best_range_mps, 1)} m/s` }],
      series: [{ label: "fit", points: vv.map((v) => [v, P(v) / v / 3.6]) }, { label: "simulation", mode: "scatter", points: r.rows.map((x) => [x.sim_tas, x.Wh_per_km]) }] }).destroy);
    disp.push(xyPlot(c3.lastChild, { height: 230, xLabel: "true airspeed (m/s)", yLabel: "efficiency (–)", yDomain: [0.4, 1.0], series: [
      { label: "propeller", mode: "both", points: r.rows.map((x) => [x.sim_tas, x.eta_prop]) },
      { label: "motor", mode: "both", points: r.rows.map((x) => [x.sim_tas, x.eta_motor]) },
      { label: "ESC", mode: "both", points: r.rows.map((x) => [x.sim_tas, x.eta_esc]) }] }).destroy);
    const t = h("div", { class: "panel", style: { marginTop: "12px" } }, h("div", { class: "ph" }, "Operating points",
      h("div", { class: "tools" }, h("button", { class: "btn btn-sm", title: "Copy the fitted a, b, c into the wind_aware_best_range policy of the current scenario",
        onclick: () => { const c = clone(state.config); const prev = c.autonomy.policy;
          const keep = prev.name === "wind_aware_best_range" ? prev.params : {};
          set(c, "autonomy.policy.name", "wind_aware_best_range");
          set(c, "autonomy.policy.params", { ...keep, a: f.a, b: f.b, c: f.c });
          state.setConfig(c, state.name, true); toast("Fit copied into the wind-aware policy of the scenario.", "ok"); } }, "Use fit in wind-aware policy"))), h("div", { class: "pb flush" }));
    body.append(t);
    dataTable(t.lastChild, { rows: r.rows, maxHeight: 400, sortKey: "sim_tas", sortDir: 1, cols: [
      { key: "sim_tas", label: "TAS (m/s)", num: true, fmt: (v) => fmt.n(v, 1) }, { key: "sim_P_batt_W", label: "P batt (W)", num: true, fmt: (v) => fmt.n(v, 1) },
      { key: "model_P_batt_W", label: "Model (W)", num: true, fmt: (v) => fmt.n(v, 1) }, { key: "err_P_batt_pct", label: "Diff (%)", num: true, fmt: (v) => fmt.n(v, 2) },
      { key: "sim_rpm", label: "RPM", num: true, fmt: (v) => fmt.n(v, 0) }, { key: "sim_alpha_deg", label: "α (deg)", num: true, fmt: (v) => fmt.n(v, 2) },
      { key: "L_over_D", label: "L/D", num: true, fmt: (v) => fmt.n(v, 2) }, { key: "sim_duty", label: "Duty", num: true, fmt: (v) => fmt.n(v, 3) },
      { key: "sim_I_batt_A", label: "I batt (A)", num: true, fmt: (v) => fmt.n(v, 1) }, { key: "eta_prop", label: "η prop", num: true, fmt: (v) => fmt.n(v, 3) },
      { key: "endurance_min_usable", label: "Endurance (min)", num: true, fmt: (v) => fmt.n(v, 0) }, { key: "range_km_usable", label: "Range (km)", num: true, fmt: (v) => fmt.n(v, 1) }] });
    body.append(h("div", { class: "hint", style: { marginTop: "6px" } }, `Fit: P = ${f.a.toFixed(5)}·V³ + ${f.b.toFixed(1)}/V + ${f.c.toFixed(1)} W (RMS ${fmt.n(f.rms_residual_W, 2)} W). Endurance and range use the energy down to the RTL reserve.`));
  }
  load();
  return () => { clearTimeout(timer); disp.forEach((f) => f()); };
}
