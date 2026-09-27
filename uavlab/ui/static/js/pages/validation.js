// Verification & validation: latest results, run the suite, open the full report.
import { h, clear, api, fmt, statusChip, toast, fill } from "../core.js";

export async function render(main) {
  let jobId = null, timer = null;
  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Verification & validation"),
    h("div", { class: "sub" }, "Evidence that each model is implemented correctly (verification) and that the complete simulation behaves as physics and practice say (validation). ",
      "Every check states its criterion before it runs.")),
    h("div", { class: "actions" },
      h("a", { class: "btn", href: "/reports/validation", target: "_blank", rel: "noopener" }, "Open full report"),
      h("button", { class: "btn", onclick: () => start(true) }, "Run quick suite"),
      h("button", { class: "btn btn-primary", onclick: () => start(false) }, "Run full suite"))));
  const prog = h("div", { style: { marginBottom: "10px" } }), body = h("div");
  main.append(prog, body);
  async function start(quick) {
    try { const j = await api("/api/tools/validate", { quick }); jobId = j.id; toast("V&V suite started. The full suite takes about 10-25 minutes.", "ok"); poll(); }
    catch (e) { toast(e.message, "alarm"); }
  }
  async function poll() {
    const d = await api(`/api/jobs/${jobId}`);
    fill(prog, h("div", { class: "row" }, statusChip(d.state), h("div", { class: "progress", style: { width: "220px" } }, h("i", { style: { width: `${Math.round(100 * d.progress)}%` } })),
      h("span", { class: "muted mono small" }, d.message)), h("div", { class: "log", style: { maxHeight: "160px", marginTop: "6px" } }, d.log.slice(-14).join("\n")));
    if (["running", "queued"].includes(d.state)) timer = setTimeout(poll, 2000); else load();
  }
  async function load() {
    clear(body);
    const r = await api("/api/validation");
    if (!r.checks?.length) { body.append(h("div", { class: "empty" }, "No V&V results yet.")); return; }
    body.append(h("div", { class: "kpis", style: { marginBottom: "12px" } },
      h("div", { class: `kpi ${r.passed === r.total ? "ok" : "alarm"}` }, h("div", { class: "k" }, "Checks passed"), h("div", { class: "v" }, `${r.passed} / ${r.total}`)),
      h("div", { class: "kpi" }, h("div", { class: "k" }, "Generated"), h("div", { class: "v", style: { fontSize: "14px" } }, r.meta.date)),
      h("div", { class: "kpi" }, h("div", { class: "k" }, "JSBSim"), h("div", { class: "v" }, r.meta.jsbsim)),
      h("div", { class: "kpi" }, h("div", { class: "k" }, "Mode"), h("div", { class: "v", style: { fontSize: "14px" } }, r.meta.quick ? "quick" : "full"))));
    const t = h("table", { class: "tbl" }, h("thead", {}, h("tr", {}, ["ID", "Check", "Criterion", "Result", "Status"].map((x) => h("th", {}, x)))),
      h("tbody", {}, r.checks.map((c) => h("tr", {}, h("td", { class: "mono" }, c.id), h("td", {}, c.title),
        h("td", { class: "small muted", style: { whiteSpace: "normal", minWidth: "260px" } }, c.criterion), h("td", { class: "mono small", style: { whiteSpace: "normal" } }, c.value),
        h("td", {}, statusChip(c.passed ? "PASS" : "FAIL"))))));
    body.append(h("div", { class: "panel" }, h("div", { class: "ph" }, `Checks (${r.source})`), h("div", { class: "pb flush" }, h("div", { class: "tbl-wrap" }, t))));
  }
  load();
  return () => clearTimeout(timer);
}
