// Live run monitor: progress, telemetry charts, track, decisions, stop.
import { h, clear, api, state, fmt, statusChip, toast, confirmBox, fill } from "../core.js";
import { timeChart } from "../charts.js";
import { missionMap } from "../map.js";
import { runScenario } from "../app.js";

export async function render(main) {
  const jobs = state.jobs.filter((j) => j.kind === "run");
  let job = jobs.find((j) => j.id === state.activeJobId) || jobs.find((j) => j.state === "running") || jobs[0];
  if (!job) {
    main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Live run"),
      h("div", { class: "sub" }, "Telemetry of a running simulation appears here."))),
      h("div", { class: "empty" }, "No simulation has been started in this session. ",
        h("button", { class: "btn btn-primary", onclick: runScenario }, "Run the current scenario")));
    return;
  }
  state.activeJobId = job.id;
  const T = { t: [], mode: [], alt: [], hcmd: [], tas: [], gs: [], vcmd: [], p: [], soc: [], n: [], e: [], wind: [] };
  let cur = { row: 0, ev: 0, log: 0 };
  let last = null, stopped = false, timer = null;

  const chip = h("span"), prog = h("div", { class: "progress", style: { width: "260px" } }, h("i")), msg = h("span", { class: "muted" });
  const btnStop = h("button", { class: "btn btn-danger", onclick: stop }, "Stop");
  let resultRef = null;
  const btnRes = h("button", { class: "btn btn-primary", hidden: true, onclick: () => { if (resultRef) location.hash = `#/results/${encodeURIComponent(resultRef)}`; } }, "Open results");
  const others = h("select", { id: "live-job", onchange: (e) => { state.activeJobId = e.target.value; location.hash = "#/live"; dispose(); render(clear(main)); } },
    jobs.map((j) => h("option", { value: j.id, selected: j.id === job.id }, `${j.title} · ${j.state}`)));
  main.append(h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, job.title), h("div", { class: "row" }, chip, prog, msg)),
    h("div", { class: "actions" }, others, btnStop, btnRes)));
  const kpis = h("div", { class: "kpis", style: { marginBottom: "12px" } });
  main.append(kpis);
  const g = h("div", { class: "grid g2" });
  const left = h("div", { class: "panel" }, h("div", { class: "ph" }, "Track (colour = flight phase)"), h("div", { class: "pb" }));
  const right = h("div", { class: "panel" }, h("div", { class: "ph" }, "Telemetry"), h("div", { class: "pb" }));
  g.append(left, right); main.append(g);
  const logP = h("div", { class: "panel", style: { marginTop: "12px" } }, h("div", { class: "ph" }, "Mode changes and decisions"), h("div", { class: "pb" }));
  const logEl = h("div", { class: "log", style: { maxHeight: "220px" } });
  logP.lastChild.append(logEl); main.append(logP);

  const map = missionMap(left.lastChild, { height: 520 });
  try { const cfg = await api(`/api/jobs/${job.id}/config`); if (cfg.mission) { const g2 = await api("/api/preview/mission", cfg); map.setGeometry(g2); map.setWaypoints(g2.waypoints.map((w) => ({ name: w.name, n: w.n, e: w.e, alt: w.alt })), true); } } catch (_) {}
  const rb = right.lastChild;
  const mk = (title, series, y) => { rb.append(h("div", { class: "chart-title" }, title)); return timeChart(rb, { series, yLabel: y, height: 118, sync: "live" }); };
  const cAlt = mk("Altitude AGL", [{ label: "altitude" }, { label: "command", dash: [5, 3] }], "m");
  const cSpd = mk("Speed", [{ label: "TAS" }, { label: "ground speed" }, { label: "command", dash: [5, 3] }], "m/s");
  const cPow = mk("Battery power", [{ label: "P batt" }], "W");
  const cSoc = mk("State of charge", [{ label: "SOC" }], "%");

  function kpi(k, v, unit, cls = "") { return h("div", { class: `kpi ${cls}` }, h("div", { class: "k" }, k), h("div", { class: "v" }, v, unit ? h("small", {}, unit) : null)); }

  async function poll() {
    try {
      const d = await api(`/api/jobs/${job.id}?since_row=${cur.row}&since_event=${cur.ev}&since_log=${cur.log}`);
      cur = { row: d.counts.rows, ev: d.counts.events, log: d.counts.log };
      for (const r of d.telemetry) {
        T.t.push(r.t_s); T.mode.push(r.mode); T.alt.push(r.alt_agl_m); T.hcmd.push(r.h_cmd_m); T.tas.push(r.tas_mps);
        T.gs.push(r.gs_mps); T.vcmd.push(r.v_cmd_mps); T.p.push(r.P_batt_W); T.soc.push(100 * r.soc); T.n.push(r.n_m); T.e.push(r.e_m);
        last = r;
      }
      for (const ev of d.events) {
        if (ev.kind === "waypoint" && ev.name === "leg_start") continue;
        const cls = ev.kind === "decision" ? "dec" : ev.kind === "terminal" ? "bad" : "";
        logEl.append(h("div", { class: cls }, `t=${ev.t_s.toFixed(1).padStart(7)} s  ${ev.kind.padEnd(9)} ${ev.name}  ${ev.data !== "{}" ? ev.data : ""}`));
        logEl.scrollTop = logEl.scrollHeight;
      }
      fill(chip, statusChip(d.state));
      prog.firstChild.style.width = `${Math.round(100 * d.progress)}%`;
      msg.textContent = d.message || "";
      if (d.telemetry.length) {
        cAlt.setData(T.t, [T.alt, T.hcmd], T.mode); cSpd.setData(T.t, [T.tas, T.gs, T.vcmd], T.mode);
        cPow.setData(T.t, [T.p], T.mode); cSoc.setData(T.t, [T.soc], T.mode);
        map.setTracks([{ n: T.n, e: T.e, mode: T.mode }]);
        if (last) map.setAircraft({ n: last.n_m, e: last.e_m, psi_deg: last.psi_deg });
      }
      if (last) {
        fill(kpis, kpi("Simulated time", fmt.n(last.t_s, 0), "s"), kpi("Flight mode", last.mode.replace("_", " ")),
          kpi("Altitude AGL", fmt.n(last.alt_agl_m, 1), "m"), kpi("True airspeed", fmt.n(last.tas_mps, 1), "m/s"),
          kpi("Battery power", fmt.n(last.P_batt_W, 0), "W"), kpi("State of charge", fmt.n(100 * last.soc, 1), "%", last.soc < 0.25 ? "alarm" : ""),
          kpi("Energy used", fmt.n(last.E_batt_Wh, 2), "Wh"), kpi("Distance", fmt.n(last.dist_ground_m / 1000, 2), "km"));
      }
      const fin = !["running", "queued"].includes(d.state);
      resultRef = d.result?.ref || null;
      const opt = others.querySelector(`option[value="${job.id}"]`);
      if (opt) opt.textContent = `${d.title} · ${d.state}`;
      btnStop.hidden = fin; btnRes.hidden = !(fin && d.result?.ref);
      if (d.state === "failed") logEl.append(h("div", { class: "bad" }, d.error));
      if (fin) { stopped = true; if (d.state === "done") toast(`Run finished: ${d.result?.status}`, d.result?.status === "LANDED" ? "ok" : "warn"); return; }
    } catch (e) { msg.textContent = e.message; }
    if (!stopped) timer = setTimeout(poll, 700);
  }
  async function stop() {
    if (!(await confirmBox("Stop the simulation?", "The run is terminated now. Logs written so far are kept only if the run reached its end.", "Stop run"))) return;
    await api(`/api/jobs/${job.id}/cancel`, {});
  }
  function dispose() { stopped = true; clearTimeout(timer); [cAlt, cSpd, cPow, cSoc].forEach((c) => c.destroy()); map.destroy(); }
  poll();
  return dispose;
}
