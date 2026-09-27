// Results: run browser and run detail (summary, plots, map, legs, events, config, files).
import { h, clear, api, state, fmt, statusChip, toast, clone } from "../core.js";
import { dataTable } from "../widgets.js";
import { timeChart, bars, xyPlot } from "../charts.js";
import { missionMap } from "../map.js";

const SOURCES = [["runs", "Single runs"], ["repo:poc_results", "Proof-of-concept runs (poc_results)"],
  ["repo:poc_results/robustness", "Proof of concept: robustness runs"], ["repo:validation_report/runs", "V&V runs (repository)"]];

export async function render(main, params) {
  if (params[0]) return renderDetail(main, params.join("/"));
  let source = "runs", filter = "";
  main.append(h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, "Results"), h("div", { class: "sub" }, "Every finished run in the workspace. Click a row to open it; tick rows to compare them.")),
    h("div", { class: "actions" },
      h("select", { id: "res-src", onchange: (e) => { source = e.target.value; load(); } }, SOURCES.map(([v, l]) => h("option", { value: v }, l))),
      h("input", { type: "text", id: "res-filter", placeholder: "Filter by label, status, policy…", oninput: (e) => { filter = e.target.value.toLowerCase(); draw(); } }),
      h("button", { class: "btn", onclick: () => (location.hash = "#/compare") }, "Compare selected"))));
  const box = h("div", { class: "panel" }, h("div", { class: "pb flush" }));
  main.append(box);
  let rows = [];
  async function load() {
    try { rows = await api(`/api/runs?source=${encodeURIComponent(source)}`); } catch (e) { rows = []; toast(e.message, "alarm"); }
    draw();
  }
  function draw() {
    const b = clear(box.lastChild);
    const shown = rows.filter((r) => !filter || JSON.stringify([r.label, r.status, r.policy, r.run_id, r.turbulence]).toLowerCase().includes(filter));
    dataTable(b, { rows: shown, maxHeight: 640, sortKey: "mtime", sortDir: -1,
      selected: (r) => state.compare.includes(r.ref),
      onRow: (r) => (location.hash = `#/results/${encodeURIComponent(r.ref)}`),
      cols: [
        { key: "sel", label: "Compare", fmt: (v, r) => { const c = h("input", { type: "checkbox", "aria-label": "Select for comparison",
          onclick: (e) => { e.stopPropagation(); const i = state.compare.indexOf(r.ref); if (i >= 0) state.compare.splice(i, 1); else state.compare.push(r.ref); state.emit("compare"); } });
          c.checked = state.compare.includes(r.ref); return c; } },
        { key: "mtime", label: "Finished", fmt: (v) => fmt.time(v) }, { key: "label", label: "Label", fmt: (v, r) => v || r.run_id },
        { key: "status", label: "Status", fmt: (v) => statusChip(v) },
        { key: "wind_mps", label: "Wind (m/s)", num: true, fmt: (v, r) => v == null ? "–" : `${fmt.n(v, 1)} from ${fmt.n(r.wind_from_deg, 0)}°` },
        { key: "turbulence", label: "Turbulence" }, { key: "policy", label: "Policy" },
        { key: "cruise_mps", label: "Cruise (m/s)", num: true, fmt: (v) => fmt.n(v, 1) },
        { key: "flight_time_s", label: "Flight time", num: true, fmt: (v) => fmt.dur(v) },
        { key: "E_batt_Wh", label: "Energy (Wh)", num: true, fmt: (v) => fmt.n(v, 2) },
        { key: "Wh_per_km", label: "Wh/km", num: true, fmt: (v) => fmt.n(v, 2) },
        { key: "soc_end", label: "SOC end", num: true, fmt: (v) => fmt.pct(v) }] });
  }
  load();
}

// ------------------------------------------------------------------- detail
const PLOT_PRESETS = {
  "Flight path": [["alt_agl_m", "h_cmd_m"], ["tas_mps", "gs_mps", "v_cmd_mps"], ["phi_deg", "phi_cmd_deg"], ["xtrack_m"]],
  "Energy": [["P_batt_W"], ["soc"], ["E_batt_Wh", "E_shaft_Wh", "E_thrust_Wh"], ["P_wind_W"]],
  "Powertrain": [["P_batt_W", "P_shaft_W", "P_thrust_W"], ["i_batt_A", "i_motor_A"], ["v_bus_V"], ["rpm"]],
  "Wind": [["wind_tot_n_mps", "wind_tot_e_mps", "wind_tot_d_mps"], ["tailwind_mps", "crosswind_mps"], ["wind_est_n_mps", "wind_est_e_mps"], ["P_wind_W"]],
  "Aerodynamics": [["alpha_deg", "beta_deg"], ["CL", "CD"], ["thrust_N", "drag_N"], ["nz_g"]],
};

async function renderDetail(main, ref) {
  let d;
  try { d = await api(`/api/run?ref=${encodeURIComponent(ref)}`); }
  catch (e) { main.append(h("div", { class: "alertbox" }, e.message)); return; }
  const s = d.summary || {}, b = d.brief || {};
  const disposers = [];
  const label = h("input", { type: "text", id: "run-label", value: b.label || "", placeholder: ref.startsWith("repo:") ? "Repository run (read-only)" : "Add a label", disabled: ref.startsWith("repo:"), style: { width: "260px" },
    onchange: async (e) => { await api("/api/run/label", { ref, label: e.target.value }); toast("Label saved.", "ok"); } });
  main.append(h("div", { class: "page-head" },
    h("div", {}, h("div", { class: "row" }, h("a", { href: "#/results" }, "Results"), h("span", { class: "muted" }, "/"), h("span", { class: "mono" }, s.run_id || ref)),
      h("div", { class: "row", style: { marginTop: "4px" } }, h("h1", {}, b.label || s.run_id || "Run"), statusChip(s.status),
        h("span", { class: "muted" }, s.termination || ""), h("span", { class: "hint mono", title: "Configuration hash" }, `config ${s.config_hash || ""}`))),
    h("div", { class: "actions" }, label,
      h("button", { class: "btn", title: "Load this run's exact configuration into the scenario editor", onclick: loadCfg }, "Load configuration"),
      h("button", { class: "btn", onclick: () => { if (!state.compare.includes(ref)) state.compare.push(ref); toast("Added to comparison.", "ok"); state.emit("compare"); } }, "Add to compare"))));
  const tabs = h("div", { class: "tabs" }), body = h("div");
  main.append(tabs, body);
  const TABS = ["Summary", "Plots", "Map", "Legs", "Events", "Files"];
  let tab = "Summary";
  function drawTabs() { clear(tabs); for (const t of TABS) tabs.append(h("button", { class: t === tab ? "on" : "", onclick: () => { tab = t; draw(); } }, t)); }
  function draw() {
    disposers.splice(0).forEach((f) => f()); clear(body); drawTabs();
    ({ Summary: summary, Plots: plots, Map: mapTab, Legs: legs, Events: events, Files: files })[tab]();
  }

  async function loadCfg() {
    try { const cfg = await api(`/api/run/config?ref=${encodeURIComponent(ref)}`); state.setConfig(cfg, b.label || s.run_id, true);
      toast("Configuration loaded into the scenario editor.", "ok"); } catch (e) { toast(e.message, "alarm"); }
  }

  function kpi(k, v, unit) { return h("div", { class: "kpi" }, h("div", { class: "k" }, k), h("div", { class: "v" }, v, unit ? h("small", {}, unit) : null)); }
  function summary() {
    const g = h("div", { class: "grid g2" });
    const k = h("div", { class: "kpis" });
    k.append(kpi("Battery energy", fmt.n(s.E_batt_Wh, 2), "Wh"), kpi("Energy per km", fmt.n(s.Wh_per_km, 2), "Wh/km"),
      kpi("Mission legs", fmt.n(s.mission_Wh_per_km, 2), "Wh/km"), kpi("Flight time", fmt.dur(s.flight_time_s)),
      kpi("Ground distance", fmt.n(s.dist_ground_km, 2), "km"), kpi("SOC start → end", `${fmt.pct(s.soc_start, 0)} → ${fmt.pct(s.soc_end, 0)}`),
      kpi("Min cell voltage", fmt.n(s.min_cell_v, 2), "V"), kpi("Peak battery current", fmt.n(s.max_i_batt_A, 1), "A"),
      kpi("Mean power in the air", fmt.n(s.mean_P_batt_air_W, 0), "W"), kpi("Wind work", fmt.n(s.energy_breakdown_Wh?.wind_work, 2), "Wh"),
      kpi("Energy balance residual", s.energy_closure ? s.energy_closure.relative.toExponential(1) : "–"),
      kpi("Real-time factor", fmt.n(s.realtime_factor, 1), "×"));
    const p1 = h("div", { class: "panel" }, h("div", { class: "ph" }, "Key figures"), h("div", { class: "pb" }, k));
    const eb = s.energy_breakdown_Wh || {};
    const p2 = h("div", { class: "panel" }, h("div", { class: "ph" }, "Where the battery energy went"), h("div", { class: "pb" }));
    bars(p2.lastChild, [["thrust_useful", "Thrust work (useful)", "--s1"], ["propeller_loss", "Propeller loss", "--s2"],
      ["motor_copper_loss", "Motor copper loss", "--s4"], ["motor_iron_friction_loss", "Motor iron / friction", "--s4"],
      ["esc_loss", "ESC loss", "--s5"], ["battery_internal_loss", "Battery internal loss", "--s8"], ["avionics_servos", "Avionics + servos", "--s7"]]
      .map(([key, lab, c]) => ({ label: lab, value: eb[key], color: `var(${c})` })), "Wh");
    const eta = s.eta || {};
    p2.lastChild.append(h("div", { class: "hint", style: { marginTop: "8px" } },
      `Average efficiency: propeller ${fmt.pct(eta.propeller, 1)}, motor ${fmt.pct(eta.motor, 1)}, ESC ${fmt.pct(eta.esc, 1)}. ` +
      `Drag work ${fmt.n(eb.drag_work, 2)} Wh; wind added ${fmt.n(eb.wind_work, 2)} Wh of mechanical energy.`));
    const tr = s.tracking || {}, td = s.touchdown || {};
    const p3 = h("div", { class: "panel" }, h("div", { class: "ph" }, "Tracking and landing"), h("div", { class: "pb" },
      h("dl", { class: "kv" },
        h("dt", {}, "Cross-track RMS (steady legs)"), h("dd", {}, `${fmt.n(tr.xtrack_rms_steady_m, 2)} m`),
        h("dt", {}, "Altitude error RMS (steady legs)"), h("dd", {}, `${fmt.n(tr.alt_err_rms_steady_m, 2)} m`),
        h("dt", {}, "Airspeed error RMS (steady legs)"), h("dd", {}, `${fmt.n(tr.tas_err_rms_steady_mps, 2)} m/s`),
        h("dt", {}, "Throttle activity"), h("dd", {}, `${fmt.n(tr.throttle_tv_per_s, 3)} /s`),
        h("dt", {}, "Touchdown sink rate"), h("dd", {}, `${fmt.n(td.sink_mps, 2)} m/s`),
        h("dt", {}, "Touchdown point"), h("dd", {}, `${fmt.n(td.along_runway_m, 1)} m along, ${fmt.n(td.xtrack_m, 2)} m off centre line`),
        h("dt", {}, "Go-arounds"), h("dd", {}, s.go_arounds ?? 0),
        h("dt", {}, "Reason for return"), h("dd", {}, s.rtl_reason || "–"))));
    const p4 = h("div", { class: "panel" }, h("div", { class: "ph" }, "Autonomy decisions"), h("div", { class: "pb" }));
    const dec = (d.events || []).filter((e) => e.kind === "decision");
    if (!dec.length) p4.lastChild.append(h("div", { class: "hint" }, "No decisions logged."));
    for (const e of dec) p4.lastChild.append(h("div", { class: "row small", style: { borderBottom: "1px solid var(--border-soft)", padding: "3px 0" } },
      h("span", { class: "mono", style: { width: "70px" } }, `${fmt.n(e.t_s, 1)} s`), h("b", {}, e.name), h("span", { class: "muted mono" }, e.data)));
    g.append(p1, p2, p3, p4); body.append(g);
    if (d.files.includes("dashboard.png")) body.append(h("div", { class: "panel", style: { marginTop: "12px" } }, h("div", { class: "ph" }, "Dashboard image"),
      h("div", { class: "pb" }, h("img", { src: `/api/file?ref=${encodeURIComponent(ref)}&name=dashboard.png`, alt: "Run dashboard", style: { maxWidth: "100%" } }))));
  }

  async function plots() {
    let cols;
    try { cols = await api(`/api/run/columns?ref=${encodeURIComponent(ref)}`); }
    catch (e) { body.append(h("div", { class: "alertbox" }, e.message)); return; }
    const presetSel = h("select", { id: "plot-preset" }, Object.keys(PLOT_PRESETS).map((k) => h("option", { value: k }, k)), h("option", { value: "custom" }, "Custom…"));
    const pick = h("select", { id: "plot-signal", multiple: true, size: 8, style: { height: "150px", width: "320px" } },
      cols.numeric.filter((c) => c !== "t_s").map((c) => h("option", { value: c }, c)));
    const box = h("div");
    body.append(h("div", { class: "panel" }, h("div", { class: "ph" }, "Signals",
      h("div", { class: "tools" }, h("span", { class: "hint" }, "Drag across a chart to zoom, double-click to reset. Shaded bands mark flight phases.")),
    ), h("div", { class: "pb" }, h("div", { class: "row", style: { alignItems: "flex-start" } },
      h("label", { class: "field" }, h("span", {}, "Preset"), presetSel),
      h("label", { class: "field" }, h("span", {}, "Custom signals (Ctrl/Shift-click, each gets its own chart)"), pick),
      h("button", { class: "btn", style: { marginTop: "18px" }, onclick: () => { presetSel.value = "custom"; show(); } }, "Plot selection")), box)));
    presetSel.addEventListener("change", show);
    async function show() {
      disposers.splice(0).forEach((f) => f()); clear(box);
      const groups = presetSel.value === "custom" ? [...pick.selectedOptions].map((o) => [o.value]) : PLOT_PRESETS[presetSel.value];
      const flat = [...new Set(groups.flat())].filter((c) => cols.all.includes(c));
      if (!flat.length) { box.append(h("div", { class: "hint" }, "Choose at least one signal.")); return; }
      const data = await api(`/api/run/series?ref=${encodeURIComponent(ref)}&cols=${flat.join(",")}`);
      for (const g of groups) {
        const gg = g.filter((c) => data[c]);
        if (!gg.length) continue;
        box.append(h("div", { class: "chart-title" }, gg.join(", ")));
        const c = timeChart(box, { series: gg.map((x) => ({ label: x })), height: 170, sync: "detail" });
        c.setData(data.t_s, gg.map((x) => data[x]), data.mode);
        disposers.push(() => c.destroy());
      }
    }
    show();
  }

  async function mapTab() {
    const p = h("div", { class: "panel" }, h("div", { class: "ph" }, "Flown track (colour = flight phase)"), h("div", { class: "pb" }));
    body.append(p);
    const m = missionMap(p.lastChild, { height: 600 });
    disposers.push(() => m.destroy());
    try {
      const cfg = await api(`/api/run/config?ref=${encodeURIComponent(ref)}`);
      const g = await api("/api/preview/mission", cfg);
      m.setGeometry(g); m.setWaypoints(g.waypoints.map((w) => ({ name: w.name, n: w.n, e: w.e, alt: w.alt })));
      const data = await api(`/api/run/series?ref=${encodeURIComponent(ref)}&cols=n_m,e_m&max_points=8000`);
      m.setTracks([{ n: data.n_m, e: data.e_m, mode: data.mode }], true);
    } catch (e) { p.lastChild.append(h("div", { class: "alertbox" }, e.message)); }
  }

  function legs() {
    const L = d.legs || [];
    const p = h("div", { class: "panel" }, h("div", { class: "ph" }, "Energy per mission leg"), h("div", { class: "pb" }));
    body.append(p);
    if (!L.length) { p.lastChild.append(h("div", { class: "hint" }, "No mission legs were flown.")); return; }
    const chart = h("div", { style: { maxWidth: "720px" } });
    p.lastChild.append(h("div", { class: "chart-title" }, "Energy per km vs mean tail-wind on the leg"), chart);
    const x = xyPlot(chart, { height: 230, xLabel: "mean tail-wind on leg (m/s, + = from behind)", yLabel: "Wh/km",
      series: [{ label: "leg", mode: "scatter", size: 5, points: L.map((l) => [l.tailwind_mean_mps, l.Wh_per_km, 0, l.leg_name]) }] });
    disposers.push(() => x.destroy());
    dataTable(p.lastChild, { rows: L, maxHeight: 400, cols: [
      { key: "leg_name", label: "Leg" }, { key: "duration_s", label: "Duration (s)", num: true, fmt: (v) => fmt.n(v, 0) },
      { key: "dist_ground_m", label: "Distance (m)", num: true, fmt: (v) => fmt.n(v, 0) },
      { key: "E_batt_Wh", label: "Energy (Wh)", num: true, fmt: (v) => fmt.n(v, 2) }, { key: "Wh_per_km", label: "Wh/km", num: true, fmt: (v) => fmt.n(v, 2) },
      { key: "tas_mean_mps", label: "TAS (m/s)", num: true, fmt: (v) => fmt.n(v, 1) }, { key: "gs_mean_mps", label: "GS (m/s)", num: true, fmt: (v) => fmt.n(v, 1) },
      { key: "tailwind_mean_mps", label: "Tail-wind (m/s)", num: true, fmt: (v) => fmt.n(v, 2) },
      { key: "crosswind_mean_mps", label: "Cross-wind (m/s)", num: true, fmt: (v) => fmt.n(v, 2) },
      { key: "turb_rms_mps", label: "Turb. RMS (m/s)", num: true, fmt: (v) => fmt.n(v, 2) },
      { key: "eta_prop", label: "η prop", num: true, fmt: (v) => fmt.pct(v) }, { key: "E_wind_Wh", label: "Wind work (Wh)", num: true, fmt: (v) => fmt.n(v, 3) }] });
    if ((d.phases || []).length) {
      p.lastChild.append(h("div", { class: "chart-title", style: { marginTop: "12px" } }, "Energy per flight phase"));
      dataTable(p.lastChild, { rows: d.phases, maxHeight: 300, cols: [{ key: "phase", label: "Phase" },
        { key: "duration_s", label: "Duration (s)", num: true, fmt: (v) => fmt.n(v, 0) }, { key: "E_batt_Wh", label: "Energy (Wh)", num: true, fmt: (v) => fmt.n(v, 2) },
        { key: "P_batt_mean_W", label: "Mean power (W)", num: true, fmt: (v) => fmt.n(v, 0) }, { key: "dist_ground_m", label: "Distance (m)", num: true, fmt: (v) => fmt.n(v, 0) }] });
    }
  }

  function events() {
    const p = h("div", { class: "panel" }, h("div", { class: "ph" }, "Event log"), h("div", { class: "pb flush" }));
    body.append(p);
    dataTable(p.lastChild, { rows: d.events || [], maxHeight: 640, sortKey: "t_s", sortDir: 1,
      cols: [{ key: "t_s", label: "t (s)", num: true, fmt: (v) => fmt.n(v, 2) }, { key: "kind", label: "Kind" }, { key: "name", label: "Event" },
        { key: "data", label: "Data", fmt: (v) => h("span", { class: "mono small" }, v) }] });
  }

  function files() {
    const p = h("div", { class: "panel" }, h("div", { class: "ph" }, "Files of this run"), h("div", { class: "pb" }));
    body.append(p);
    for (const f of d.files) p.lastChild.append(h("div", { class: "row" }, h("a", { href: `/api/file?ref=${encodeURIComponent(ref)}&name=${encodeURIComponent(f)}` }, f)));
    p.lastChild.append(h("hr", { class: "sep" }), h("div", { class: "hint" }, "Folder: ", h("span", { class: "mono" }, `${state.meta.workspace}/${ref}`),
      ". The JSBSim model files used are in the jsbsim/ sub-folder; metadata.json holds their SHA-256 hashes."));
    const m = d.metadata || {};
    p.lastChild.append(h("dl", { class: "kv", style: { marginTop: "8px" } },
      ...["uavlab_version", "jsbsim_version", "python", "config_hash", "seed", "created_utc", "wall_time_s", "sim_time_s"].flatMap((k) => [h("dt", {}, k), h("dd", {}, String(m[k] ?? "–"))])));
  }

  draw();
  return () => disposers.splice(0).forEach((f) => f());
}
