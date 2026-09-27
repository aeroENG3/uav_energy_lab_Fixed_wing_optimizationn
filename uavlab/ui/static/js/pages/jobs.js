// Job list: every experiment started in this session, with state, progress and log.
import { h, clear, api, state, fmt, statusChip, toast } from "../core.js";

export async function render(main) {
  let sel = null, timer = null;
  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Jobs"),
    h("div", { class: "sub" }, "Simulations, studies, optimisations and tool runs started from this interface since the server started. Results stay in the workspace after the server stops."))));
  const g = h("div", { class: "grid g2" });
  const list = h("div", { class: "panel" }, h("div", { class: "ph" }, "All jobs"), h("div", { class: "pb flush" }));
  const det = h("div", { class: "panel" }, h("div", { class: "ph" }, "Job log"), h("div", { class: "pb" }, h("div", { class: "hint" }, "Select a job.")));
  g.append(list, det); main.append(g);
  function drawList() {
    const b = clear(list.lastChild);
    if (!state.jobs.length) { b.append(h("div", { class: "empty" }, "No jobs yet.")); return; }
    const t = h("table", { class: "tbl" }, h("thead", {}, h("tr", {}, ["Started", "Job", "Kind", "State", "Progress", ""].map((x) => h("th", {}, x)))));
    const tb = h("tbody");
    for (const j of state.jobs) {
      tb.append(h("tr", { class: `clickable ${j.id === sel ? "sel" : ""}`, onclick: () => { sel = j.id; drawList(); drawDet(); } },
        h("td", {}, fmt.time(j.created)), h("td", {}, j.title), h("td", {}, j.kind), h("td", {}, statusChip(j.state)),
        h("td", {}, h("div", { class: "progress", style: { width: "100px" } }, h("i", { style: { width: `${Math.round(100 * j.progress)}%` } }))),
        h("td", {}, ["running", "queued"].includes(j.state) ? h("button", { class: "btn btn-sm btn-danger", onclick: async (e) => { e.stopPropagation(); await api(`/api/jobs/${j.id}/cancel`, {}); toast("Cancel requested.", "warn"); } }, "Cancel") : null)));
    }
    t.append(tb); b.append(h("div", { class: "tbl-wrap" }, t));
  }
  async function drawDet() {
    if (!sel) return;
    const d = await api(`/api/jobs/${sel}`);
    const b = clear(det.lastChild);
    b.append(h("div", { class: "row" }, h("b", {}, d.title), statusChip(d.state), h("span", { class: "muted" }, d.message)));
    if (d.kind === "run" && d.result?.ref) b.append(h("a", { class: "btn btn-sm", href: `#/results/${encodeURIComponent(d.result.ref)}` }, "Open results"));
    if (d.kind === "run" && ["running", "queued"].includes(d.state)) b.append(h("a", { class: "btn btn-sm", href: "#/live", onclick: () => (state.activeJobId = d.id) }, "Watch live"));
    if (d.kind === "sweep") b.append(h("a", { class: "btn btn-sm", href: `#/doe/${encodeURIComponent(d.params.name)}` }, "Open study"));
    if (d.kind === "optimise") b.append(h("a", { class: "btn btn-sm", href: `#/optimise/${encodeURIComponent(d.params.name)}` }, "Open optimisation"));
    b.append(h("div", { class: "log", style: { maxHeight: "480px", marginTop: "8px" } }, d.log.join("\n")));
    if (d.error) b.append(h("div", { class: "alertbox", style: { marginTop: "8px", whiteSpace: "pre-wrap", fontFamily: "var(--mono)", fontSize: "12px" } }, d.error));
  }
  drawList();
  const off = state.on((w) => { if (w === "jobs") { drawList(); if (sel) { clearTimeout(timer); timer = setTimeout(drawDet, 200); } } });
  return () => { off(); clearTimeout(timer); };
}
