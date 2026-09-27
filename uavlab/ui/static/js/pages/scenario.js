// Scenario editor: every configuration parameter, grouped by layer, with previews.
import { h, clear, api, state, get, set, toast, debounce, fmt, modifiedCount, clone, fill } from "../core.js";
import { propertyGrid, editTable } from "../widgets.js";
import { missionMap } from "../map.js";
import { xyPlot, timeChart } from "../charts.js";

const TABS = [
  { id: "mission", label: "Mission", groups: ["mission"] },
  { id: "wind", label: "Wind", groups: ["wind"] },
  { id: "atmosphere", label: "Atmosphere", groups: ["atmosphere"] },
  { id: "aircraft", label: "Aircraft", groups: ["aircraft"] },
  { id: "powertrain", label: "Powertrain", groups: ["powertrain"] },
  { id: "autonomy", label: "Autonomy & policy", groups: ["autonomy"] },
  { id: "controller", label: "Controller", groups: ["controller"] },
  { id: "hw", label: "Actuators & sensors", groups: ["actuators", "sensors"] },
  { id: "sim", label: "Simulation & logging", groups: ["sim", "logging"] },
];

const fieldsOf = (groups) => state.schema.fields.filter((f) => groups.includes(f.group));

export async function render(main, params) {
  let tab = params[0] && TABS.find((t) => t.id === params[0]) ? params[0] : "mission";
  let search = "";
  const disposers = [];
  const head = h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, "Scenario"),
      h("div", { class: "sub" }, "Every parameter the simulation uses, with its unit and meaning. Changed values are marked in the margin; ",
        h("span", { class: "tag REP" }, "REP"), " values are representative and should be replaced with your hardware's data.")),
    h("div", { class: "actions" },
      h("input", { type: "text", id: "param-search", placeholder: "Search all parameters…", style: { width: "240px" },
        oninput: debounce((e) => { search = e.target.value; draw(); }, 250) }),
      h("button", { class: "btn", onclick: exportYaml, title: "Download the scenario as YAML (only values that differ from defaults)" }, "Export YAML")));
  const tabsEl = h("div", { class: "tabs", role: "tablist" });
  const body = h("div", {});
  main.append(head, tabsEl, body);

  function drawTabs() {
    clear(tabsEl);
    for (const t of TABS) {
      const n = t.groups.reduce((a, g) => a + modifiedCount(g + "."), 0);
      tabsEl.append(h("button", { class: t.id === tab && !search ? "on" : "", role: "tab",
        onclick: () => { tab = t.id; search = ""; document.getElementById("param-search").value = ""; history.replaceState(null, "", `#/scenario/${t.id}`); draw(); } },
        t.label, n ? h("span", { class: "cnt", title: `${n} changed from default` }, n) : null));
    }
  }
  const onChange = () => { state.touch(); drawTabs(); };

  function draw() {
    disposers.splice(0).forEach((d) => d());
    clear(body); drawTabs();
    if (search) {
      const p = h("div", { class: "panel" }, h("div", { class: "ph" }, `Search results for “${search}”`), h("div", { class: "pb" }));
      body.append(p); propertyGrid(p.lastChild, state.schema.fields, { filter: search, onChange }); return;
    }
    ({ mission: drawMission, wind: drawWind, powertrain: drawPowertrain, autonomy: drawAutonomy }[tab] || drawPlain)();
  }

  function panel(title, tools) {
    const pb = h("div", { class: "pb" });
    const p = h("div", { class: "panel" }, h("div", { class: "ph" }, title, tools ? h("div", { class: "tools" }, tools) : null), pb);
    return [p, pb];
  }

  function drawPlain() {
    const t = TABS.find((x) => x.id === tab);
    const [p, pb] = panel(t.label);
    body.append(p);
    propertyGrid(pb, fieldsOf(t.groups), { onChange });
  }

  // ---------------------------------------------------------------- mission
  function drawMission() {
    const g = h("div", { class: "grid g-side-r" });
    const [mapP, mapB] = panel("Route (local north / east from home)");
    const [parP, parB] = panel("Mission parameters");
    g.append(h("div", { class: "grid" }, mapP), parP);
    body.append(g);
    const stats = h("div", { class: "row small muted", style: { marginBottom: "6px" } });
    mapB.append(stats);
    const map = missionMap(mapB, { height: 430, editable: true,
      onChange: (w) => { writeWps(w); wpTable.render(); refresh(); }, onSelect: () => {} });
    disposers.push(() => map.destroy());
    const tblBox = h("div", { style: { marginTop: "10px" } }, h("div", { class: "chart-title" }, "Waypoints"));
    mapB.append(tblBox);
    const wps = state.config.mission.waypoints;
    const wpTable = editTable(tblBox, {
      columns: [{ key: "name", label: "Name", type: "text", width: "90px" }, { key: "n_m", label: "North", unit: "m", type: "num" },
        { key: "e_m", label: "East", unit: "m", type: "num" }, { key: "alt_agl_m", label: "Altitude AGL", unit: "m", type: "num" },
        { key: "airspeed_mps", label: "Airspeed", unit: "m/s", type: "num", optional: true },
        { key: "acceptance_radius_m", label: "Radius", unit: "m", type: "num", optional: true }],
      rows: wps, minRows: 1,
      newRow: (rows) => { const l = rows[rows.length - 1] || { n_m: 0, e_m: 0, alt_agl_m: 100 };
        return { name: `WP${rows.length + 1}`, n_m: (l.n_m || 0) + 200, e_m: l.e_m || 0, alt_agl_m: l.alt_agl_m || 100 }; },
      onChange: () => { state.touch(); refresh(); },
    });
    function writeWps(list) {
      const cur = state.config.mission.waypoints;
      list.forEach((p, i) => {
        if (!cur[i]) cur[i] = { name: p.name, alt_agl_m: p.alt };
        cur[i].n_m = p.n; cur[i].e_m = p.e; delete cur[i].lat_deg; delete cur[i].lon_deg;
      });
      cur.length = list.length; state.touch();
    }
    propertyGrid(parB, fieldsOf(["mission"]), { onChange: () => { onChange(); refresh(); } });
    const refresh = debounce(async () => {
      try {
        const g = await api("/api/preview/mission", state.config);
        // waypoints given as lat/lon in a file are converted to local N/E once, for editing
        state.config.mission.waypoints.forEach((w, i) => {
          if (w.n_m === undefined && g.waypoints[i]) { w.n_m = Math.round(g.waypoints[i].n); w.e_m = Math.round(g.waypoints[i].e); delete w.lat_deg; delete w.lon_deg; }
        });
        map.setGeometry(g);
        map.setFence(state.config.mission.geofence.radius_m);
        map.setWaypoints(g.waypoints.map((w) => ({ name: w.name, n: w.n, e: w.e, alt: w.alt })));
        const v = state.config.mission.cruise.airspeed_mps;
        fill(stats, 
          h("span", {}, `Runway ${fmt.n(g.runway.heading_deg, 0)}° (${g.runway.selection.replace("_", " ")})`),
          h("span", {}, `· route ${fmt.n(g.route_length_m / 1000, 2)} km per lap × ${g.repeat}`),
          h("span", {}, `· about ${fmt.dur(g.route_length_m * g.repeat / v)} at ${v} m/s in still air`));
      } catch (e) { fill(stats, h("span", { style: { color: "var(--alarm)" } }, e.message)); }
    }, 300);
    refresh();
  }

  // ------------------------------------------------------------------ wind
  function drawWind() {
    const g = h("div", { class: "grid g2" });
    const [parP, parB] = panel("Wind model");
    const [prevP, prevB] = panel("Preview", h("button", { class: "btn btn-sm", onclick: () => refresh() }, "Refresh"));
    g.append(parP, prevP); body.append(g);
    propertyGrid(parB, fieldsOf(["wind"]), { onChange: () => { onChange(); refresh(); } });
    parB.append(h("div", { class: "chart-title" }, "Time schedule of the mean wind (optional)"),
      h("div", { class: "hint" }, "Linear interpolation between rows; the reference-height wind above is used when empty."));
    editTable(parB, { columns: [{ key: "t_s", label: "Time", unit: "s", type: "num" }, { key: "speed_mps", label: "Speed", unit: "m/s", type: "num" },
      { key: "from_deg", label: "From", unit: "deg", type: "num" }],
      rows: state.config.wind.mean.schedule, reorder: false, emptyText: "No schedule: the wind is constant in time.",
      newRow: (r) => ({ t_s: r.length ? r[r.length - 1].t_s + 300 : 0, speed_mps: state.config.wind.mean.speed_mps, from_deg: state.config.wind.mean.from_deg }),
      onChange: () => { state.touch(); refresh(); } });
    parB.append(h("div", { class: "chart-title" }, "Discrete gusts"),
      h("div", { class: "hint" }, "one_minus_cos: rises and falls over the duration. ramp_hold: rises over the duration and holds for hold_s."));
    editTable(parB, { columns: [{ key: "t_s", label: "Start", unit: "s", type: "num" }, { key: "duration_s", label: "Duration", unit: "s", type: "num" },
      { key: "amplitude_mps", label: "Horizontal", unit: "m/s", type: "num" }, { key: "from_deg", label: "From", unit: "deg", type: "num" },
      { key: "vertical_mps", label: "Vertical (up +)", unit: "m/s", type: "num", optional: true },
      { key: "shape", label: "Shape", type: "select", options: ["one_minus_cos", "ramp_hold"] },
      { key: "hold_s", label: "Hold", unit: "s", type: "num", optional: true }],
      rows: state.config.wind.gusts, reorder: false, emptyText: "No discrete gusts.",
      newRow: () => ({ t_s: 120, duration_s: 4, amplitude_mps: 4, from_deg: 270, vertical_mps: 0, shape: "one_minus_cos" }),
      onChange: () => { state.touch(); refresh(); } });

    const prof = h("div"), series = h("div"), facts = h("dl", { class: "kv", style: { marginTop: "8px" } });
    prevB.append(h("div", { class: "chart-title" }, "Mean wind profile at t = 0"), prof,
      h("div", { class: "chart-title" }, `Wind at cruise altitude, first 300 s (seeded; what the aircraft would meet at cruise speed)`), series, facts);
    const pp = xyPlot(prof, { height: 220, xLabel: "wind speed (m/s)", yLabel: "height AGL (m)", series: [] });
    const ts = timeChart(series, { series: [{ label: "north" }, { label: "east" }, { label: "down" }, { label: "mean speed", dash: [5, 3] }],
      yLabel: "m/s", height: 190, modes: false, sync: "windprev" });
    disposers.push(() => pp.destroy(), () => ts.destroy());
    const refresh = debounce(async () => {
      try {
        const r = await api("/api/preview/wind", { config: state.config, duration_s: 300 });
        pp.update([{ label: "speed", points: r.profile.h.map((hh, i) => [r.profile.speed[i], hh]) }]);
        ts.setData(r.series.t, [r.series.n, r.series.e, r.series.d, r.series.mean_speed]);
        const d = r.dryden;
        fill(facts, 
          h("dt", {}, "Turbulence model"), h("dd", {}, r.turbulence_model),
          h("dt", {}, "W20 (wind at 20 ft)"), h("dd", {}, `${fmt.n(d.w20_mps)} m/s`),
          h("dt", {}, `σ u / v / w at ${fmt.n(d.height_m, 0)} m`), h("dd", {}, d.sigma_uvw_mps.map((x) => fmt.n(x)).join(" / ") + " m/s"),
          h("dt", {}, "Scale lengths L u / v / w"), h("dd", {}, d.L_uvw_m.map((x) => fmt.n(x, 0)).join(" / ") + " m"),
          r.turbulence_model === "jsbsim_milspec" ? h("dt", {}, "Note") : null,
          r.turbulence_model === "jsbsim_milspec" ? h("dd", { style: { fontFamily: "var(--sans)" } }, "Preview uses the lab's Dryden generator; JSBSim generates its own realisation in flight.") : null);
      } catch (e) { toast(e.message, "alarm"); }
    }, 350);
    refresh();
  }

  // ------------------------------------------------------------- powertrain
  function drawPowertrain() {
    const g = h("div", { class: "grid g2" });
    const [parP, parB] = panel("Powertrain parameters");
    const [batP, batB] = panel("Battery and mass summary");
    g.append(parP, batP); body.append(g);
    propertyGrid(parB, fieldsOf(["powertrain"]), { onChange: () => { onChange(); refresh(); } });
    const facts = h("dl", { class: "kv", style: { marginBottom: "10px" } });
    const chart = h("div");
    batB.append(facts, h("div", { class: "chart-title" }, "Pack open-circuit voltage vs state of charge"), chart,
      h("div", { class: "chart-title" }, "OCV table (per cell)"), h("div", { class: "hint" }, "Replace with a pulse-test curve of your cells for absolute SOC accuracy."));
    const ocv = state.config.powertrain.battery.ocv_table;
    const rows = ocv.soc.map((s, i) => ({ soc: s, v: ocv.v[i] }));
    editTable(batB, { columns: [{ key: "soc", label: "SOC", unit: "0-1", type: "num" }, { key: "v", label: "Cell OCV", unit: "V", type: "num" }],
      rows, reorder: false, minRows: 2, newRow: () => ({ soc: 1, v: 4.2 }),
      onChange: (r) => { const s = [...r].sort((a, b) => a.soc - b.soc); ocv.soc = s.map((x) => x.soc); ocv.v = s.map((x) => x.v); state.touch(); refresh(); } });
    const pl = xyPlot(chart, { height: 200, xLabel: "state of charge (–)", yLabel: "pack OCV (V)", series: [] });
    disposers.push(() => pl.destroy());
    const refresh = debounce(async () => {
      try {
        const r = await api("/api/preview/battery", state.config);
        pl.update([{ label: "OCV", points: r.soc.map((s, i) => [s, r.ocv[i]]) }]);
        const m = state.config.powertrain.motor;
        fill(facts, 
          h("dt", {}, "Pack energy (SOC 0-1)"), h("dd", {}, `${fmt.n(r.energy_Wh, 1)} Wh`),
          h("dt", {}, "Usable down to RTL reserve"), h("dd", {}, `${fmt.n(r.usable_to_rtl_Wh, 1)} Wh`),
          h("dt", {}, "Voltage full / mid"), h("dd", {}, `${fmt.n(r.full_V, 1)} / ${fmt.n(r.nominal_V, 1)} V`),
          h("dt", {}, "Pack R0 / R1 / τ"), h("dd", {}, `${fmt.n(r.R0_mohm, 1)} / ${fmt.n(r.R1_mohm, 1)} mΩ / ${fmt.n(r.tau_s, 0)} s`),
          h("dt", {}, "Specific energy"), h("dd", {}, `${fmt.n(r.specific_Wh_per_kg, 0)} Wh/kg`),
          h("dt", {}, "All-up mass"), h("dd", {}, `${fmt.n(r.all_up_mass_kg, 2)} kg`),
          h("dt", {}, "Motor no-load speed at full pack"), h("dd", {}, `${fmt.int(m.kv_rpm_per_v * r.full_V)} rpm`),
          h("dt", {}, "Motor torque constant Kt"), h("dd", {}, `${fmt.n(60 / (2 * Math.PI * m.kv_rpm_per_v), 4)} N·m/A`));
      } catch (e) { toast(e.message, "alarm"); }
    }, 300);
    refresh();
  }

  // --------------------------------------------------------------- autonomy
  function drawAutonomy() {
    const g = h("div", { class: "grid g2" });
    const [polP, polB] = panel("Adaptive policy (online optimiser slot)");
    const [parP, parB] = panel("Autonomy parameters");
    g.append(polP, parP); body.append(g);
    const pol = state.config.autonomy.policy;
    const pols = state.schema.policies;
    const sel = h("select", { id: "policy-name" }, Object.keys(pols).filter((n) => n !== "external").map((n) => h("option", { value: n, selected: n === pol.name }, n)));
    const doc = h("pre", { class: "log", style: { maxHeight: "200px", fontFamily: "var(--sans)", whiteSpace: "pre-wrap" } });
    const pbox = h("div");
    polB.append(h("div", { class: "row" }, h("label", { class: "field", style: { flex: 1 } }, h("span", {}, "Policy"), sel)),
      h("div", { class: "chart-title" }, "What it does"), doc, h("div", { class: "chart-title" }, "Parameters"), pbox);
    function drawParams() {
      const defs = pols[pol.name]?.params || {};
      doc.textContent = pols[pol.name]?.doc || "";
      pol.params = Object.fromEntries(Object.entries({ ...defs, ...(pol.params || {}) }).filter(([k]) => k in defs));
      clear(pbox);
      if (!Object.keys(defs).length) { pbox.append(h("div", { class: "hint" }, "This policy has no parameters.")); return; }
      const t = h("table", { class: "pgrid" });
      for (const [k, dv] of Object.entries(defs)) {
        const isBool = typeof dv === "boolean";
        const inp = isBool ? h("input", { type: "checkbox", id: `pp_${k}` }) : h("input", { type: "number", step: "any", id: `pp_${k}`, value: pol.params[k] });
        if (isBool) inp.checked = !!pol.params[k];
        inp.addEventListener("change", () => {
          const v = isBool ? inp.checked : Number(inp.value);
          if (!isBool && !Number.isFinite(v)) { inp.classList.add("invalid"); return; }
          inp.classList.remove("invalid"); pol.params[k] = v; state.touch();
        });
        t.append(h("tr", {}, h("td", { class: "lab" }, h("label", { for: `pp_${k}` }, k)), h("td", { class: "val" }, inp),
          h("td", { class: "unit" }, `default ${fmt.auto(dv)}`)));
      }
      pbox.append(t);
    }
    sel.addEventListener("change", () => { pol.name = sel.value; pol.params = {}; state.touch(); drawParams(); drawTabs(); });
    drawParams();
    propertyGrid(parB, fieldsOf(["autonomy"]), { onChange });
  }

  async function exportYaml() {
    try {
      const r = await fetch("/api/config/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ config: state.config }) });
      const blob = new Blob([await r.text()], { type: "text/yaml" });
      const a = h("a", { href: URL.createObjectURL(blob), download: `${state.name || "scenario"}.yaml` });
      document.body.append(a); a.click(); a.remove();
    } catch (e) { toast(e.message, "alarm"); }
  }

  const off = state.on((w) => { if (w === "config") draw(); });
  draw();
  return () => { off(); disposers.splice(0).forEach((d) => d()); };
}
