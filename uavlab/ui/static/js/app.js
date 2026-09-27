// Application shell: navigation, routing, toolbar, status bar, job polling.
import { h, clear, fill, api, state, toast, modal, icon, clone, modifiedCount } from "./core.js";

const PAGES = [
  { sect: "Set up" },
  { id: "overview", label: "Overview", icon: "overview" },
  { id: "scenario", label: "Scenario", icon: "scenario" },
  { sect: "Run & analyse" },
  { id: "live", label: "Live run", icon: "live" },
  { id: "results", label: "Results", icon: "results" },
  { id: "compare", label: "Compare runs", icon: "compare" },
  { sect: "Studies" },
  { id: "doe", label: "Parameter study", icon: "doe" },
  { id: "optimise", label: "Optimisation", icon: "opt" },
  { id: "performance", label: "Performance map", icon: "perf" },
  { sect: "Assurance" },
  { id: "validation", label: "Verification & validation", icon: "vv" },
  { id: "jobs", label: "Jobs", icon: "jobs" },
  { id: "handbook", label: "Handbook", icon: "book" },
];

const loaders = {
  overview: () => import("./pages/overview.js"), scenario: () => import("./pages/scenario.js"),
  live: () => import("./pages/live.js"), results: () => import("./pages/results.js"),
  compare: () => import("./pages/compare.js"), doe: () => import("./pages/doe.js"),
  optimise: () => import("./pages/optimise.js"), performance: () => import("./pages/performance.js"),
  validation: () => import("./pages/validation.js"), jobs: () => import("./pages/jobs.js"),
  handbook: () => import("./pages/handbook.js"),
};

let cleanup = null;

function renderNav(active) {
  const nav = clear(document.getElementById("sidenav"));
  const running = state.jobs.filter((j) => j.state === "running" || j.state === "queued").length;
  for (const p of PAGES) {
    if (p.sect) { nav.append(h("div", { class: "sect" }, p.sect)); continue; }
    const a = h("a", { href: `#/${p.id}`, class: p.id === active ? "active" : "" }, icon(p.icon), p.label);
    if (p.id === "jobs" && running) a.append(h("span", { class: "badge", title: "Running jobs" }, running));
    if (p.id === "compare" && state.compare.length) a.append(h("span", { class: "badge" }, state.compare.length));
    nav.append(a);
  }
}

function renderScenarioId() {
  const el = document.getElementById("scenario-id");
  const n = modifiedCount();
  fill(el, "Scenario ", h("b", {}, state.name),
    state.dirty ? h("span", { class: "mod", title: "Edited since it was loaded or saved" }, "● edited") : null,
    h("span", { class: "hint" }, ` · ${n} parameter${n === 1 ? " differs" : "s differ"} from defaults`));
}

function renderStatus(ok = true) {
  const sb = clear(document.getElementById("statusbar"));
  const m = state.meta || {};
  const running = state.jobs.filter((j) => j.state === "running");
  sb.append(
    h("span", {}, h("i", { class: `dot ${ok ? "ok" : "alarm"}` }), ok ? "Server connected" : "Server not reachable"),
    h("span", {}, `uavlab ${m.version || ""}`), h("span", {}, `JSBSim ${m.jsbsim || ""}`),
    h("span", {}, `${m.cpus || "?"} CPU cores`),
    h("button", { onclick: () => (location.hash = "#/jobs"), title: "Open the job list" },
      h("i", { class: `dot ${running.length ? "run" : ""}` }),
      running.length ? `${running.length} job${running.length > 1 ? "s" : ""} running: ${running[0].title} ${Math.round(100 * running[0].progress)} %` : "No job running"),
    h("span", { class: "sp", title: m.workspace }, `Workspace ${m.workspace || ""}`));
}

async function route() {
  const parts = (location.hash || "#/overview").slice(2).split("/");
  const page = loaders[parts[0]] ? parts[0] : "overview";
  renderNav(page);
  if (cleanup) { try { cleanup(); } catch (e) { console.error(e); } cleanup = null; }
  const main = clear(document.getElementById("main"));
  try {
    const mod = await loaders[page]();
    cleanup = (await mod.render(main, parts.slice(1).map(decodeURIComponent))) || null;
  } catch (e) {
    console.error(e);
    main.append(h("div", { class: "alertbox" }, `This page failed to load: ${e.message}`));
  }
  main.focus({ preventScroll: true });
}

// ------------------------------------------------------------------ toolbar
export async function applyPreset(kind, name) {
  const cfg = await api("/api/config/apply", { kind, name, config: state.config });
  const label = kind === "scenarios" ? name : (state.name === "untitled" || state.name === "defaults" ? name : `${state.name} + ${name}`);
  state.setConfig(cfg, label, kind !== "scenarios");
  toast(`Loaded ${kind === "missions" ? "mission" : kind === "wind" ? "wind" : "scenario"} preset “${name}”.`, "ok");
}

async function openPresets() {
  const p = await api("/api/presets");
  const sect = (title, kind, list, note) => h("div", { style: { marginBottom: "14px" } },
    h("h3", { style: { margin: "0 0 4px", fontSize: "13px" } }, title), note ? h("div", { class: "hint", style: { marginBottom: "6px" } }, note) : null,
    list.length ? h("div", { class: "preset-list" }, list.map((x) => h("button", { class: "preset",
      onclick: async () => { m.close(); try { await applyPreset(kind, x.name); } catch (e) { toast(e.message, "alarm"); } } },
      h("b", {}, x.name), h("span", {}, x.description || "")))) : h("div", { class: "hint" }, "None saved yet."));
  const m = modal("Open preset", h("div", {},
    sect("Missions", "missions", p.missions, "Replaces the mission section (waypoints, cruise, repeat)."),
    sect("Wind conditions", "wind", p.wind, "Replaces the wind section; everything else is kept."),
    sect("Saved scenarios", "scenarios", p.scenarios, "Complete scenarios saved in this workspace."),
    h("button", { class: "btn", onclick: async () => { m.close(); state.setConfig(clone(state.defaults), "defaults", false); toast("Reset to the default configuration.", "ok"); } },
      "Reset everything to defaults")));
}

async function saveScenario() {
  const name = h("input", { type: "text", id: "save-name", value: state.name.replace(/[^\w-]+/g, "_") });
  const desc = h("input", { type: "text", id: "save-desc", placeholder: "One line shown in the preset list" });
  modal("Save scenario", h("div", { class: "grid" },
    h("label", { class: "field" }, h("span", {}, "Name (letters, digits, - and _)"), name),
    h("label", { class: "field" }, h("span", {}, "Description"), desc),
    h("div", { class: "hint" }, "Only the values that differ from the defaults are written, as a YAML file in the workspace ",
      h("span", { class: "mono" }, "scenarios/"), ". The same file runs from the command line: ",
      h("span", { class: "mono" }, "python -m uavlab run scenarios/<name>.yaml"))), [
    { label: "Cancel" },
    { label: "Save", primary: true, onclick: async () => {
      try {
        const r = await api("/api/scenarios/save", { name: name.value, description: desc.value, config: state.config });
        state.name = r.name; state.dirty = false; state.persist(); state.emit("config");
        toast(`Saved ${r.saved} (${r.changed_keys} values differ from defaults).`, "ok");
      } catch (e) { toast(e.message, "alarm"); return true; }
    } }]);
}

export async function validateScenario(quiet = false) {
  const r = await api("/api/config/validate", state.config);
  if (r.ok) { if (!quiet) toast("All parameters are within their limits.", "ok"); return true; }
  modal("The scenario has invalid values", h("div", { class: "alertbox" }, "Fix these before running:",
    h("ul", {}, r.errors.map((e) => h("li", {}, e)))));
  return false;
}

export async function runScenario() {
  if (!(await validateScenario(true))) return;
  try {
    const j = await api("/api/run", { config: state.config, label: state.name });
    state.activeJobId = j.id;
    toast("Simulation started.", "ok");
    location.hash = "#/live";
    pollJobs();
  } catch (e) { toast(e.message, "alarm"); }
}

let navSig = "";
async function pollJobs() {
  try {
    state.jobs = await api("/api/jobs");
    renderStatus(true);
    const active = (location.hash || "").slice(2).split("/")[0];
    const sig = `${active}|${state.jobs.filter((j) => j.state === "running" || j.state === "queued").length}|${state.compare.length}`;
    if (sig !== navSig) { navSig = sig; renderNav(loaders[active] ? active : "overview"); }
    state.emit("jobs");
  } catch (e) { renderStatus(false); }
}

function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("uavlab.theme", t); } catch (_) {}
  state.emit("theme");
}

async function boot() {
  let theme = null;
  try { theme = localStorage.getItem("uavlab.theme"); } catch (_) {}
  applyTheme(theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  document.getElementById("tb-theme").onclick = () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    route();
  };
  const [meta, schema, defaults] = await Promise.all([api("/api/meta"), api("/api/schema"), api("/api/config/defaults")]);
  state.meta = meta; state.schema = schema; state.defaults = defaults;
  const saved = state.restore();
  if (saved) { state.config = saved.config; state.name = saved.name; state.dirty = saved.dirty; }
  else { state.config = clone(defaults); state.name = "defaults"; }
  state.on((what) => { if (what === "config" || what === "dirty") renderScenarioId(); });
  renderScenarioId();
  document.getElementById("tb-open").onclick = openPresets;
  document.getElementById("tb-save").onclick = saveScenario;
  document.getElementById("tb-validate").onclick = () => validateScenario(false);
  document.getElementById("tb-run").onclick = runScenario;
  document.addEventListener("keydown", (e) => { if (e.ctrlKey && e.key === "Enter") runScenario(); });
  window.addEventListener("hashchange", route);
  await pollJobs();
  setInterval(pollJobs, 1500);
  route();
}

boot().catch((e) => {
  document.getElementById("main").append(h("div", { class: "alertbox" }, `The UI could not start: ${e.message}`));
});
