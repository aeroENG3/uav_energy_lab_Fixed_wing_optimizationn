// Overview: start points, recent results, assurance status and running work.
import { h, clear, api, state, fmt, statusChip, toast, clone } from "../core.js";
import { applyPreset, runScenario } from "../app.js";

const TEMPLATES = [
  { title: "Survey in calm air", text: "5-waypoint box, 17 m/s at 100 m. The energy reference case.", mission: "survey_box", wind: "calm" },
  { title: "Survey in gusty wind", text: "5 m/s westerly with Dryden turbulence and three discrete gusts.", mission: "survey_box", wind: "gusty" },
  { title: "Head-wind / tail-wind legs", text: "2.5 km out-and-back legs in a 6 m/s sheared westerly: the wind-energy case.", mission: "out_and_back", wind: "steady_headwind_6" },
  { title: "Wind that strengthens", text: "Wind grows from 3 to 9 m/s and veers during the flight, with slow random variation.", mission: "survey_box", wind: "time_varying" },
  { title: "Endurance to reserve", text: "Repeats the survey until the energy logic brings the aircraft home.", mission: "endurance_loiter", wind: "calm" },
  { title: "Strong-wind stress case", text: "11 m/s wind near the cruise speed: tests the energy-feasibility decisions.", mission: "survey_box", wind: "strong_wind" },
];

export async function render(main) {
  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Overview"),
    h("div", { class: "sub" }, "JSBSim Rascal 110 electric with atmosphere, mission, autonomy, control and powertrain layers. Pick a starting point, adjust it on the Scenario page, then run it."))));
  const tp = h("div", { class: "panel" }, h("div", { class: "ph" }, "Start from a template"), h("div", { class: "pb" }));
  const cards = h("div", { class: "card-list" });
  for (const t of TEMPLATES) {
    cards.append(h("div", { class: "preset", style: { cursor: "default" } },
      h("b", { style: { fontFamily: "var(--sans)", fontSize: "13px" } }, t.title), h("span", {}, t.text),
      h("div", { class: "row", style: { marginTop: "8px" } },
        h("button", { class: "btn btn-sm", onclick: () => load(t, false) }, "Load"),
        h("button", { class: "btn btn-sm btn-primary", onclick: () => load(t, true) }, "Load and run"))));
  }
  tp.lastChild.append(cards);
  main.append(tp);
  async function load(t, run) {
    try {
      state.setConfig(clone(state.defaults), t.title.toLowerCase().replace(/[^\w]+/g, "_"), false);
      await applyPreset("missions", t.mission); await applyPreset("wind", t.wind);
      state.name = t.title.toLowerCase().replace(/[^\w]+/g, "_"); state.persist(); state.emit("config");
      if (run) await runScenario(); else location.hash = "#/scenario/mission";
    } catch (e) { toast(e.message, "alarm"); }
  }
  const g = h("div", { class: "grid g3", style: { marginTop: "12px" } });
  const rp = h("div", { class: "panel" }, h("div", { class: "ph" }, "Recent results", h("div", { class: "tools" }, h("a", { href: "#/results" }, "All results"))), h("div", { class: "pb flush" }));
  const vp = h("div", { class: "panel" }, h("div", { class: "ph" }, "Verification & validation", h("div", { class: "tools" }, h("a", { href: "#/validation" }, "Details"))), h("div", { class: "pb" }));
  const jp = h("div", { class: "panel" }, h("div", { class: "ph" }, "Workflow"), h("div", { class: "pb" }));
  g.append(rp, vp, jp); main.append(g);
  try {
    const runs = (await api("/api/runs")).slice(0, 8);
    if (!runs.length) rp.lastChild.append(h("div", { class: "empty", style: { margin: "10px" } }, "No runs yet."));
    else rp.lastChild.append(h("table", { class: "tbl" }, h("tbody", {}, runs.map((r) => h("tr", { class: "clickable", onclick: () => (location.hash = `#/results/${encodeURIComponent(r.ref)}`) },
      h("td", {}, r.label || r.run_id), h("td", {}, statusChip(r.status)), h("td", { class: "n" }, `${fmt.n(r.E_batt_Wh, 1)} Wh`), h("td", { class: "n" }, `${fmt.n(r.Wh_per_km, 2)} Wh/km`))))));
  } catch (e) { rp.lastChild.append(h("div", { class: "alertbox" }, e.message)); }
  try {
    const v = await api("/api/validation");
    if (v.checks?.length) {
      vp.lastChild.append(h("div", { class: "row" }, h("span", { class: "num", style: { fontSize: "22px", fontWeight: 600 } }, `${v.passed}/${v.total}`), h("span", { class: "muted" }, "checks passed"),
        statusChip(v.passed === v.total ? "PASS" : "FAIL")),
        h("div", { class: "hint", style: { margin: "6px 0" } }, `Generated ${v.meta.date} with JSBSim ${v.meta.jsbsim}.`),
        h("div", { class: "small" }, v.checks.slice(0, 9).map((c) => h("div", { class: "row", style: { justifyContent: "space-between", borderBottom: "1px solid var(--border-soft)", padding: "2px 0" } },
          h("span", {}, `${c.id} ${c.title}`), statusChip(c.passed ? "PASS" : "FAIL")))));
    } else vp.lastChild.append(h("div", { class: "hint" }, "No report yet."));
  } catch (_) {}
  jp.lastChild.append(h("ol", { style: { margin: 0, paddingLeft: "18px", lineHeight: "1.9" } },
    h("li", {}, h("a", { href: "#/scenario/mission" }, "Scenario"), ": route, wind, aircraft, powertrain, policy."),
    h("li", {}, h("b", {}, "Run simulation"), " (toolbar or Ctrl+Enter), then watch it on ", h("a", { href: "#/live" }, "Live run"), "."),
    h("li", {}, h("a", { href: "#/results" }, "Results"), ": KPIs, energy breakdown, signals, legs, events; ", h("a", { href: "#/compare" }, "compare"), " runs."),
    h("li", {}, h("a", { href: "#/doe" }, "Parameter study"), " or ", h("a", { href: "#/optimise" }, "Optimisation"), " for datasets and best designs."),
    h("li", {}, "Check assumptions in the ", h("a", { href: "#/handbook" }, "Handbook"), " and the ", h("a", { href: "#/validation" }, "V&V report"), ".")));
}
