// Optimisation: cross-entropy method over any numeric parameters, any KPI objective,
// constraints, several evaluation conditions (robust design), live convergence.
import { h, clear, api, state, fmt, statusChip, toast, set, clone, fill } from "../core.js";
import { paramOptions } from "./doe.js";
import { xyPlot } from "../charts.js";
import { dataTable } from "../widgets.js";

const OBJECTIVES = [["mission_E_Wh", "Mission-leg battery energy (Wh)"], ["mission_Wh_per_km", "Mission-leg energy per km (Wh/km)"],
  ["E_batt_Wh", "Total battery energy (Wh)"], ["Wh_per_km", "Total energy per km (Wh/km)"], ["flight_time_s", "Flight time (s)"],
  ["soc_end", "SOC at end (–)"], ["tracking.xtrack_rms_steady_m", "Cross-track RMS (m)"], ["touchdown.sink_mps", "Touchdown sink rate (m/s)"]];

export async function render(main, params) {
  const pol = state.config.autonomy.policy;
  const vars = pol.name === "linear_wind"
    ? [{ path: "autonomy.policy.params.v0", lo: 12, hi: 20 }, { path: "autonomy.policy.params.k_head", lo: 0, hi: 1.2 }]
    : [{ path: "mission.cruise.airspeed_mps", lo: 12, hi: 22 }];
  // an energy objective also needs a complete mission: an early return (D4/D5) would otherwise "save" energy
  const cons = [{ kpi: "status", op: "==", value: "LANDED" }, { kpi: "rtl_reason", op: "==", value: "mission_complete" }];
  let conds = [{ label: "base", preset: "", overrides: "" }];
  let objective = "mission_E_Wh", sense = "min", pop = 8, iters = 5, seeds = "1", workers = state.meta.cpus || 2;
  let name = `opt_${new Date().toISOString().slice(5, 16).replace(/[-:T]/g, "")}`;
  let jobId = null, timer = null, disp = [];
  const windPresets = (await api("/api/presets")).wind;

  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Optimisation"),
    h("div", { class: "sub" }, "Find the parameter values that minimise (or maximise) a KPI over one or more flight conditions, subject to constraints. ",
      "Derivative-free cross-entropy method: robust to turbulence noise, runs a whole population in parallel. Every candidate flies the same seeds (common random numbers)."))));
  const g = h("div", { class: "grid g-side" });
  const defP = h("div", { class: "panel" }, h("div", { class: "ph" }, "Problem definition"), h("div", { class: "pb" }));
  const resP = h("div", { class: "panel" }, h("div", { class: "ph" }, "Convergence and results"), h("div", { class: "pb" }));
  g.append(defP, resP); main.append(g);
  const B = defP.lastChild;

  function drawDef() {
    clear(B);
    B.append(h("div", { class: "grid", style: { gridTemplateColumns: "1fr 1fr", gap: "8px" } },
      h("label", { class: "field" }, h("span", {}, "Name"), h("input", { type: "text", id: "opt-name", value: name, onchange: (e) => (name = e.target.value) })),
      h("div", { class: "field" }, h("span", {}, "Base scenario"), h("div", { class: "mono small", style: { paddingTop: "4px" } }, `${state.name} · policy ${state.config.autonomy.policy.name}`))));
    if (pol.name !== "linear_wind") B.append(h("div", { class: "hint", style: { marginTop: "6px" } },
      "Tip: to optimise a wind-adaptive speed law, choose the ", h("b", {}, "linear_wind"), " policy on the Scenario › Autonomy tab, then add its parameters (v0, k_head, …) here."));
    // variables
    B.append(h("div", { class: "chart-title" }, "Decision variables (bounds)"));
    const vt = h("table", { class: "tbl edit" }, h("thead", {}, h("tr", {}, h("th", {}, "Parameter"), h("th", {}, "Lower"), h("th", {}, "Upper"), h("th", {}, "Integer"), h("th", {}, ""))));
    const vb = h("tbody");
    vars.forEach((v, i) => {
      const s = h("select", {}, paramOptions((f) => ["float", "int"].includes(f.type))); s.value = v.path; s.onchange = () => (v.path = s.value);
      vb.append(h("tr", {}, h("td", {}, s),
        h("td", {}, h("input", { type: "number", step: "any", value: v.lo, onchange: (e) => (v.lo = +e.target.value) })),
        h("td", {}, h("input", { type: "number", step: "any", value: v.hi, onchange: (e) => (v.hi = +e.target.value) })),
        h("td", {}, (() => { const c = h("input", { type: "checkbox", onchange: (e) => (v.integer = e.target.checked) }); c.checked = !!v.integer; return c; })()),
        h("td", {}, h("button", { class: "btn btn-sm btn-icon btn-danger", onclick: () => { vars.splice(i, 1); drawDef(); } }, "×"))));
    });
    vt.append(vb);
    B.append(h("div", { class: "tbl-wrap" }, vt), h("button", { class: "btn btn-sm", style: { marginTop: "6px" }, onclick: () => { vars.push({ path: "mission.cruise.alt_agl_m", lo: 60, hi: 140 }); drawDef(); } }, "Add variable"));
    // objective
    B.append(h("div", { class: "chart-title" }, "Objective"), h("div", { class: "row" },
      h("select", { id: "opt-obj", onchange: (e) => (objective = e.target.value) }, OBJECTIVES.map(([k, l]) => h("option", { value: k, selected: k === objective }, l))),
      h("div", { class: "seg" }, ["min", "max"].map((s) => h("button", { class: s === sense ? "on" : "", onclick: () => { sense = s; drawDef(); } }, s === "min" ? "Minimise" : "Maximise")))));
    // constraints
    B.append(h("div", { class: "chart-title" }, "Constraints (every run must satisfy them)"));
    const ct = h("table", { class: "tbl edit" }, h("tbody", {}, cons.map((c, i) => h("tr", {},
      h("td", {}, h("input", { type: "text", value: c.kpi, onchange: (e) => (c.kpi = e.target.value), "aria-label": "KPI" })),
      h("td", { style: { width: "70px" } }, h("select", { onchange: (e) => (c.op = e.target.value) }, ["==", "!=", "<", "<=", ">", ">="].map((o) => h("option", { selected: o === c.op }, o)))),
      h("td", {}, h("input", { type: "text", value: c.value, onchange: (e) => { const v = e.target.value; c.value = Number.isFinite(Number(v)) && v !== "" ? Number(v) : v; }, "aria-label": "Value" })),
      h("td", { style: { width: "36px" } }, h("button", { class: "btn btn-sm btn-icon btn-danger", onclick: () => { cons.splice(i, 1); drawDef(); } }, "×"))))));
    B.append(ct, h("div", { class: "row", style: { marginTop: "6px" } },
      h("button", { class: "btn btn-sm", onclick: () => { cons.push({ kpi: "soc_end", op: ">=", value: 0.3 }); drawDef(); } }, "Add constraint"),
      h("span", { class: "hint" }, "KPI names as in summary.json, e.g. status, soc_end, touchdown.sink_mps, tracking.xtrack_rms_steady_m")));
    // conditions
    B.append(h("div", { class: "chart-title" }, "Evaluation conditions (objective = mean over conditions × seeds)"));
    const cdt = h("table", { class: "tbl edit" }, h("thead", {}, h("tr", {}, h("th", {}, "Label"), h("th", {}, "Wind preset"), h("th", {}, "Extra overrides (key=value; …)"), h("th", {}, ""))),
      h("tbody", {}, conds.map((c, i) => h("tr", {},
        h("td", { style: { width: "90px" } }, h("input", { type: "text", value: c.label, onchange: (e) => (c.label = e.target.value) })),
        h("td", {}, h("select", { onchange: (e) => (c.preset = e.target.value) }, h("option", { value: "" }, "scenario wind"), windPresets.map((w) => h("option", { value: w.name, selected: w.name === c.preset }, w.name)))),
        h("td", {}, h("input", { type: "text", value: c.overrides, placeholder: "wind.mean.speed_mps=6; wind.mean.from_deg=90", onchange: (e) => (c.overrides = e.target.value) })),
        h("td", { style: { width: "36px" } }, h("button", { class: "btn btn-sm btn-icon btn-danger", disabled: conds.length < 2, onclick: () => { conds.splice(i, 1); drawDef(); } }, "×"))))));
    B.append(h("div", { class: "tbl-wrap" }, cdt), h("button", { class: "btn btn-sm", style: { marginTop: "6px" }, onclick: () => { conds.push({ label: `c${conds.length + 1}`, preset: "steady_headwind_6", overrides: "" }); drawDef(); } }, "Add condition"));
    const num = (lab, v, fn, attrs = {}) => h("label", { class: "field" }, h("span", {}, lab), h("input", { type: attrs.text ? "text" : "number", value: v, onchange: (e) => { fn(attrs.text ? e.target.value : +e.target.value); est(); } }));
    B.append(h("div", { class: "grid", style: { gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "8px", marginTop: "10px" } },
      num("Population", pop, (v) => (pop = v)), num("Generations", iters, (v) => (iters = v)), num("Seeds", seeds, (v) => (seeds = v), { text: true }), num("Workers", workers, (v) => (workers = v))),
      h("div", { id: "opt-est", class: "hint", style: { margin: "8px 0" } }), h("button", { class: "btn btn-primary", onclick: start }, "Start optimisation"), h("div", { id: "opt-prog", style: { marginTop: "10px" } }));
    est();
  }
  function est() {
    const el = B.querySelector("#opt-est"); if (!el) return;
    const n = pop * iters * conds.length * seeds.split(",").filter(Boolean).length;
    el.textContent = `${n} flights in total. Rough duration: ${fmt.dur(n * 25 / Math.max(workers, 1))} (longer for long or windy missions).`;
  }
  async function buildSpec() {
    const conditions = [];
    for (const c of conds) {
      const ov = {};
      if (c.preset) {   // a wind preset defines the whole wind section: start from the default wind
        flatten(state.defaults.wind, "wind", ov);
        const r = await api(`/api/preset/raw?kind=wind&name=${encodeURIComponent(c.preset)}`); flatten(r.data, "", ov);
      }
      for (const part of (c.overrides || "").split(";")) { const [k, v] = part.split("=").map((x) => x && x.trim()); if (k && v !== undefined) ov[k] = Number.isFinite(Number(v)) ? Number(v) : v; }
      conditions.push({ label: c.label, overrides: ov });
    }
    return { name, base_config: state.config, variables: vars.map((v) => ({ ...v })), objective: { kpi: objective, sense }, constraints: cons,
      conditions, seeds: seeds.split(",").map((s) => parseInt(s)).filter((s) => Number.isFinite(s)),
      algorithm: { population: pop, iterations: iters, elite_frac: 0.25, init_sigma_frac: 0.3, smoothing: 0.7 }, workers, fixed: { "sim.log_rate_hz": 2 } };
  }
  function flatten(o, p, out) {
    for (const [k, v] of Object.entries(o)) { const q = p ? `${p}.${k}` : k;
      if (v && typeof v === "object" && !Array.isArray(v)) flatten(v, q, out); else out[q] = v; }
  }
  async function start() {
    try { const j = await api("/api/optimise", await buildSpec()); jobId = j.id; toast("Optimisation started.", "ok"); poll(); }
    catch (e) { toast(e.message, "alarm"); }
  }
  async function poll() {
    const el = B.querySelector("#opt-prog");
    try {
      const d = await api(`/api/jobs/${jobId}`);
      fill(el, h("div", { class: "row" }, statusChip(d.state), h("div", { class: "progress", style: { width: "200px" } }, h("i", { style: { width: `${Math.round(100 * d.progress)}%` } })),
        h("span", { class: "muted" }, `generation ${d.counts.results} / ${d.params.iterations}`),
        d.state === "running" ? h("button", { class: "btn btn-sm btn-danger", onclick: () => api(`/api/jobs/${jobId}/cancel`, {}) }, "Stop after this generation") : null),
        h("div", { class: "log", style: { maxHeight: "110px", marginTop: "6px" } }, d.log.slice(-8).join("\n")));
      if (["running", "queued"].includes(d.state)) timer = setTimeout(poll, 2000);
      showResult(name);
    } catch (e) { el.textContent = e.message; }
  }

  // --------------------------------------------------------------- results
  const R = resP.lastChild;
  let cur = params[0] || null;
  async function showResult(select) {
    const list = await api("/api/optimisations");
    if (select) cur = select;
    if (!cur && list.length) cur = list[0].name;
    disp.forEach((f) => f()); disp = []; clear(R);
    if (!list.length) { R.append(h("div", { class: "empty" }, "No optimisation yet.")); return; }
    R.append(h("div", { class: "row" }, h("select", { onchange: (e) => showResult(e.target.value) }, list.map((o) => h("option", { value: o.name, selected: o.name === cur }, `${o.name} · ${o.state || "?"}`)))));
    let d; try { d = await api(`/api/optimisation?name=${encodeURIComponent(cur)}`); } catch (e) { return; }
    const G = d.generations || [];
    const sp = d.spec || {};
    const ch = h("div"); R.append(h("div", { class: "chart-title" }, `Objective per generation (${sp.objective?.kpi || ""}, ${sp.objective?.sense || ""})`), ch);
    const p = xyPlot(ch, { height: 220, xLabel: "generation", yLabel: sp.objective?.kpi || "",
      series: [{ label: "best candidate", mode: "both", points: G.map((g) => [g.generation + 1, g.best_objective]) },
        { label: "mean of feasible candidates", mode: "both", dash: [5, 3], points: G.map((g) => [g.generation + 1, g.mean_feasible_objective]) }] });
    disp.push(() => p.destroy());
    const vkeys = (sp.variables || []).map((v) => v.path);
    if (G.length) {
      const last = G[G.length - 1];
      R.append(h("div", { class: "chart-title" }, "Search distribution (mean ± σ) after the last generation"),
        h("dl", { class: "kv" }, vkeys.flatMap((k) => [h("dt", {}, k), h("dd", {}, `${fmt.n(last["mu." + k], 3)} ± ${fmt.n(last["sigma." + k], 3)}`)])));
    }
    if (d.result?.best_variables) {
      const bv = d.result.best_variables;
      R.append(h("div", { class: "okbox", style: { marginTop: "10px" } }, `Best feasible design: ${sp.objective?.kpi} = ${fmt.auto(+(+d.result.best_objective).toPrecision(5))} with `,
        Object.entries(bv).map(([k, v]) => `${k} = ${fmt.auto(+(+v).toPrecision(5))}`).join(", "), "."),
        h("div", { class: "row", style: { marginTop: "6px" } },
          h("button", { class: "btn btn-primary", onclick: () => { const c = clone(state.config); for (const [k, v] of Object.entries(bv)) set(c, k, v);
            state.setConfig(c, `${state.name}+${cur}`, true); toast("Best design applied to the scenario.", "ok"); } }, "Apply best design to scenario"),
          d.best_run_ref ? h("a", { class: "btn", href: `#/results/${encodeURIComponent(d.best_run_ref)}` }, "Open verification run") : null));
    }
    if ((d.evaluations || []).length) {
      R.append(h("div", { class: "chart-title", style: { marginTop: "10px" } }, `All evaluations (${d.evaluations.length})`));
      dataTable(R, { rows: d.evaluations, maxHeight: 300, sortKey: "objective_kpi", sortDir: sp.objective?.sense === "max" ? -1 : 1,
        cols: [{ key: "generation", label: "Gen", num: true }, { key: "candidate", label: "Cand", num: true }, { key: "condition", label: "Condition" },
          ...vkeys.map((k) => ({ key: k, label: k.split(".").pop(), num: true, fmt: (v) => fmt.n(v, 3) })),
          { key: "objective_kpi", label: sp.objective?.kpi || "objective", num: true, fmt: (v) => fmt.n(v, 3) },
          { key: "status", label: "Status", fmt: (v) => statusChip(v) }, { key: "violations", label: "Violations", num: true }] });
    }
  }
  drawDef();
  showResult(params[0]);
  return () => { clearTimeout(timer); disp.forEach((f) => f()); };
}
