// Parameter study (design of experiments): full-factorial grids, Latin-hypercube sampling,
// replicates; live progress; dataset explorer with response plots.
import { h, clear, api, state, fmt, statusChip, toast, get, fill } from "../core.js";
import { dataTable } from "../widgets.js";
import { xyPlot } from "../charts.js";
import { applyPreset } from "../app.js";

export function paramOptions(filterFn = () => true) {
  const groups = {};
  for (const f of state.schema.fields) {
    if (!["float", "int", "enum", "bool", "null"].includes(f.type) || !filterFn(f)) continue;
    (groups[f.group] ||= []).push(f);
  }
  const pol = state.config.autonomy.policy;
  const pp = Object.keys(state.schema.policies[pol.name]?.params || {}).map((k) => ({ path: `autonomy.policy.params.${k}`, label: `${pol.name}: ${k}`, unit: "" }));
  return [...Object.entries(groups).map(([g, fs]) => h("optgroup", { label: g }, fs.map((f) => h("option", { value: f.path }, `${f.path}${f.unit ? " (" + f.unit + ")" : ""}`)))),
    pp.length ? h("optgroup", { label: "policy parameters" }, pp.map((p) => h("option", { value: p.path }, p.path))) : null];
}

function parseList(s) {
  return s.split(",").map((x) => x.trim()).filter(Boolean).map((x) => (x === "true" ? true : x === "false" ? false : Number.isFinite(Number(x)) ? Number(x) : x));
}

export async function render(main, params) {
  const factors = [
    { path: "wind.mean.speed_mps", kind: "values", values: "0, 4, 8", lo: 0, hi: 10, n: 3 },
    { path: "mission.cruise.airspeed_mps", kind: "values", values: "14, 17, 20", lo: 13, hi: 22, n: 3 },
  ];
  let nRandom = 10, reps = 1, workers = state.meta.cpus || 2, logRate = 5;
  let name = `study_${new Date().toISOString().slice(5, 16).replace(/[-:T]/g, "")}`;
  let jobId = null, timer = null;
  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Parameter study"),
    h("div", { class: "sub" }, "Vary any parameter of the current scenario on a grid or by Latin-hypercube sampling, run every case as a full flight, and explore the dataset. Each run keeps its full logs."))));
  const g = h("div", { class: "grid g-side" });
  const defP = h("div", { class: "panel" }, h("div", { class: "ph" }, "Study definition"), h("div", { class: "pb" }));
  const presetRow = h("div", { class: "row", style: { marginBottom: "8px" } }, h("select", { id: "doe-preset", style: { width: "100%" }, onchange: (e) => loadPreset(e.target.value) },
    h("option", { value: "" }, "Load an experiment preset…")));
  const resP = h("div", { class: "panel" }, h("div", { class: "ph" }, "Studies in this workspace"), h("div", { class: "pb" }));
  g.append(defP, resP); main.append(g);
  const presetSel = presetRow.querySelector("#doe-preset");
  api("/api/presets").then((p) => p.experiments.forEach((x) => presetSel.append(h("option", { value: x.name }, `${x.name}: ${x.description}`))));

  const defB = defP.lastChild;
  function drawDef() {
    clear(defB);
    defB.append(presetRow);
    defB.append(h("div", { class: "grid", style: { gridTemplateColumns: "1fr 1fr", gap: "8px" } },
      h("label", { class: "field" }, h("span", {}, "Study name"), h("input", { type: "text", id: "doe-name", value: name, onchange: (e) => (name = e.target.value) })),
      h("div", { class: "field" }, h("span", {}, "Base scenario"), h("div", { class: "mono small", style: { paddingTop: "4px" } }, `${state.name}${state.dirty ? " (edited)" : ""}`))));
    defB.append(h("div", { class: "chart-title" }, "Factors"),
      h("div", { class: "hint" }, "List/range factors form a full-factorial grid. Random factors are sampled by Latin hypercube; every grid point is combined with every random sample."));
    const t = h("table", { class: "tbl edit" });
    t.append(h("thead", {}, h("tr", {}, h("th", {}, "Parameter"), h("th", {}, "Kind"), h("th", {}, "Values / range"), h("th", {}, ""))));
    const tb = h("tbody");
    factors.forEach((f, i) => {
      const sel = h("select", { "aria-label": "Parameter" }, paramOptions()); sel.value = f.path;
      sel.onchange = () => { f.path = sel.value; drawEst(); };
      const kind = h("select", { "aria-label": "Kind" }, [["values", "list of values"], ["range", "linear range"], ["uniform", "random uniform"], ["choice", "random choice"]]
        .map(([v, l]) => h("option", { value: v, selected: f.kind === v }, l)));
      kind.onchange = () => { f.kind = kind.value; drawDef(); };
      let vals;
      if (f.kind === "values" || f.kind === "choice") vals = h("input", { type: "text", value: f.values, placeholder: "e.g. 0, 4, 8", onchange: (e) => { f.values = e.target.value; drawEst(); } });
      else vals = h("div", { class: "row", style: { flexWrap: "nowrap" } },
        h("input", { type: "number", step: "any", value: f.lo, title: "from", style: { width: "70px" }, onchange: (e) => { f.lo = +e.target.value; drawEst(); } }),
        h("input", { type: "number", step: "any", value: f.hi, title: "to", style: { width: "70px" }, onchange: (e) => { f.hi = +e.target.value; drawEst(); } }),
        f.kind === "range" ? h("input", { type: "number", step: "1", min: 2, value: f.n, title: "points", style: { width: "56px" }, onchange: (e) => { f.n = +e.target.value; drawEst(); } }) : null);
      tb.append(h("tr", {}, h("td", {}, sel), h("td", {}, kind), h("td", {}, vals),
        h("td", {}, h("button", { class: "btn btn-sm btn-icon btn-danger", title: "Remove factor", onclick: () => { factors.splice(i, 1); drawDef(); } }, "×"))));
    });
    t.append(tb);
    defB.append(h("div", { class: "tbl-wrap" }, t), h("button", { class: "btn btn-sm", style: { marginTop: "6px" },
      onclick: () => { factors.push({ path: "wind.mean.from_deg", kind: "values", values: "0, 90, 180, 270", lo: 0, hi: 360, n: 4 }); drawDef(); } }, "Add factor"));
    const num = (lab, v, set, attrs = {}) => h("label", { class: "field" }, h("span", {}, lab), h("input", { type: "number", value: v, ...attrs, onchange: (e) => { set(+e.target.value); drawEst(); } }));
    defB.append(h("div", { class: "grid", style: { gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "8px", marginTop: "10px" } },
      num("Random samples", nRandom, (v) => (nRandom = v), { min: 1 }), num("Replicates (seeds)", reps, (v) => (reps = v), { min: 1 }),
      num("Parallel workers", workers, (v) => (workers = v), { min: 1 }), num("Log rate (Hz)", logRate, (v) => (logRate = v), { min: 1 })));
    defB.append(h("div", { id: "doe-est", class: "hint", style: { margin: "8px 0" } }),
      h("div", { class: "row" }, h("button", { class: "btn btn-primary", onclick: start }, "Start study")),
      h("div", { id: "doe-progress", style: { marginTop: "10px" } }));
    drawEst();
  }
  function spec() {
    const grid = {}, random = {};
    for (const f of factors) {
      if (f.kind === "values") grid[f.path] = parseList(f.values);
      else if (f.kind === "range") grid[f.path] = Array.from({ length: Math.max(2, f.n) }, (_, i) => +(f.lo + (i * (f.hi - f.lo)) / (Math.max(2, f.n) - 1)).toPrecision(8));
      else if (f.kind === "uniform") random[f.path] = { uniform: [f.lo, f.hi] };
      else random[f.path] = { choice: parseList(f.values) };
    }
    const s = { name, base_config: state.config, fixed: { "sim.log_rate_hz": logRate }, grid, replicates: reps, workers };
    if (Object.keys(random).length) s.random = { n: nRandom, params: random };
    return s;
  }
  function count() {
    const s = spec(); let n = 1;
    for (const v of Object.values(s.grid)) n *= v.length;
    if (s.random) n *= s.random.n;
    return n * reps;
  }
  function drawEst() {
    const el = defB.querySelector("#doe-est"); if (!el) return;
    const n = count();
    const perRun = 25;   // typical wall seconds per full mission at ~20x real time
    el.textContent = `${n} runs. Rough duration: ${fmt.dur((n * perRun) / Math.max(workers, 1))} with ${workers} workers (longer for windy or long missions).`;
  }
  async function loadPreset(nameP) {
    if (!nameP) return;
    const r = await api(`/api/preset/raw?kind=experiments&name=${encodeURIComponent(nameP)}`);
    const sp = r.data;
    for (const f of sp.scenario || []) { const m = f.match(/missions\/(\w+)\.yaml/); if (m) await applyPreset("missions", m[1]); }
    factors.length = 0;
    for (const [k, v] of Object.entries(sp.grid || {})) factors.push({ path: k, kind: "values", values: v.join(", "), lo: 0, hi: 1, n: 3 });
    for (const [k, v] of Object.entries(sp.random?.params || {})) {
      if (v.uniform) factors.push({ path: k, kind: "uniform", lo: v.uniform[0], hi: v.uniform[1], n: 3, values: "" });
      else factors.push({ path: k, kind: "choice", values: v.choice.join(", "), lo: 0, hi: 1, n: 3 });
    }
    for (const [k, v] of Object.entries(sp.fixed || {})) { if (k === "sim.log_rate_hz") logRate = v; else factors.push({ path: k, kind: "values", values: String(v), lo: 0, hi: 1, n: 1 }); }
    nRandom = sp.random?.n || nRandom; reps = sp.replicates || 1; name = sp.name || name;
    drawDef(); toast(`Loaded experiment “${nameP}”.`, "ok");
  }
  async function start() {
    try {
      const j = await api("/api/sweep", spec());
      jobId = j.id; toast(`Study started: ${count()} runs.`, "ok"); poll();
    } catch (e) { toast(e.message, "alarm"); }
  }
  async function poll() {
    if (!jobId) return;
    const el = defB.querySelector("#doe-progress");
    try {
      const d = await api(`/api/jobs/${jobId}`);
      fill(el, h("div", { class: "row" }, statusChip(d.state), h("div", { class: "progress", style: { width: "220px" } }, h("i", { style: { width: `${Math.round(100 * d.progress)}%` } })),
        h("span", { class: "muted" }, `${d.counts.results} / ${d.params.n_runs} runs`),
        d.state === "running" ? h("button", { class: "btn btn-sm btn-danger", onclick: () => api(`/api/jobs/${jobId}/cancel`, {}) }, "Stop") : null),
        h("div", { class: "log", style: { maxHeight: "120px", marginTop: "6px" } }, d.log.slice(-12).join("\n")));
      if (["running", "queued"].includes(d.state)) { timer = setTimeout(poll, 1500); if (d.counts.results) loadStudies(name, true); }
      else { loadStudies(name); }
    } catch (e) { el.textContent = e.message; }
  }

  // --------------------------------------------------------------- explorer
  const resB = resP.lastChild;
  let curStudy = params[0] || null, disp = [];
  async function loadStudies(select, quiet = false) {
    const list = await api("/api/sweeps");
    if (select) curStudy = select;
    if (!curStudy && list.length) curStudy = list[0].name;
    if (quiet && resB.dataset.study === curStudy) { refreshData(); return; }
    clear(resB); disp.forEach((f) => f()); disp = [];
    resB.dataset.study = curStudy || "";
    if (!list.length) { resB.append(h("div", { class: "empty" }, "No studies yet. Define one on the left and press Start.")); return; }
    const sel = h("select", { id: "doe-study", onchange: (e) => { curStudy = e.target.value; loadStudies(); } },
      list.map((s) => h("option", { value: s.name, selected: s.name === curStudy }, `${s.name} · ${s.state || "?"}${s.runs != null ? " · " + s.runs + " runs" : ""}`)));
    resB.append(h("div", { class: "row" }, sel,
      h("a", { class: "btn btn-sm", href: `/api/file?ref=sweeps/${curStudy}&name=dataset_runs.csv` }, "dataset_runs.csv"),
      h("a", { class: "btn btn-sm", href: `/api/file?ref=sweeps/${curStudy}&name=dataset_legs.csv` }, "dataset_legs.csv")));
    resB.append(h("div", { id: "doe-data" }));
    refreshData();
  }
  async function refreshData() {
    const box = resB.querySelector("#doe-data"); if (!box || !curStudy) return;
    let d; try { d = await api(`/api/sweep?name=${encodeURIComponent(curStudy)}`); } catch (e) { fill(box, h("div", { class: "hint" }, "Dataset not written yet.")); return; }
    const rows = d.runs;
    clear(box); disp.forEach((f) => f()); disp = [];
    if (!rows.length) { box.append(h("div", { class: "hint", style: { marginTop: "8px" } }, "Runs in progress; the dataset appears when the study ends.")); return; }
    const pcols = Object.keys(rows[0]).filter((k) => k.startsWith("param."));
    const kcols = Object.keys(rows[0]).filter((k) => k.startsWith("kpi.") && typeof rows.find((r) => r[k] != null)?.[k] === "number");
    const xs = h("select", { id: "doe-x" }, [...pcols, ...kcols].map((c) => h("option", { value: c }, c)));
    const ys = h("select", { id: "doe-y" }, kcols.map((c) => h("option", { value: c, selected: c === "kpi.mission_Wh_per_km" }, c)));
    const gs = h("select", { id: "doe-g" }, h("option", { value: "" }, "(none)"), pcols.map((c) => h("option", { value: c }, c)));
    if (pcols[1]) gs.value = pcols[1];
    const chart = h("div");
    box.append(h("div", { class: "row", style: { margin: "10px 0 4px" } }, h("label", { class: "inline" }, "X", xs), h("label", { class: "inline" }, "Y", ys), h("label", { class: "inline" }, "Group by", gs)), chart);
    const plot = xyPlot(chart, { height: 280, series: [] }); disp.push(() => plot.destroy());
    const best = h("div", { class: "okbox", style: { margin: "8px 0" } });
    box.append(best);
    const tbox = h("div"); box.append(tbox);
    function redraw() {
      const X = xs.value, Y = ys.value, G = gs.value;
      const ok = rows.filter((r) => r[X] != null && r[Y] != null);
      const groups = {};
      for (const r of ok) (groups[G ? r[G] : "all"] ||= []).push(r);
      const series = Object.entries(groups).sort((a, b) => (+a[0] || 0) - (+b[0] || 0)).map(([k, rs]) => ({
        label: G ? `${G.replace("param.", "")} = ${k}` : "runs", mode: "both", size: 4,
        points: rs.sort((a, b) => a[X] - b[X]).map((r) => [r[X], r[Y], 0, r.run_id + (r["kpi.status"] !== "LANDED" ? " " + r["kpi.status"] : "")]) }));
      plot.update(series);
      const landed = rows.filter((r) => r["kpi.status"] === "LANDED" && r[Y] != null);
      const b = landed.sort((a, c) => a[Y] - c[Y])[0];
      fill(best, b ? `Lowest ${Y} among landed runs: ${fmt.auto(+b[Y].toPrecision(5))} in ${b.run_id} with ` +
        pcols.map((p) => `${p.replace("param.", "")} = ${fmt.auto(b[p])}`).join(", ") : "No landed run has this KPI.");
      clear(tbox);
      dataTable(tbox, { rows, maxHeight: 360, sortKey: Y, sortDir: 1,
        onRow: (r) => (location.hash = `#/results/${encodeURIComponent(`sweeps/${curStudy}/runs/${r.run_id}`)}`),
        cols: [{ key: "run_id", label: "Run" }, ...pcols.map((p) => ({ key: p, label: p.replace("param.", ""), num: true, fmt: (v) => fmt.auto(v) })),
          { key: "kpi.status", label: "Status", fmt: (v) => statusChip(v) },
          ...["kpi.E_batt_Wh", "kpi.Wh_per_km", "kpi.mission_Wh_per_km", "kpi.flight_time_s", "kpi.soc_end"].map((k) => ({ key: k, label: k.replace("kpi.", ""), num: true, fmt: (v) => fmt.n(v, 2) }))] });
    }
    [xs, ys, gs].forEach((s) => s.addEventListener("change", redraw));
    redraw();
  }
  drawDef();
  loadStudies(params[0]);
  return () => { clearTimeout(timer); disp.forEach((f) => f()); };
}
