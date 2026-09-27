// Mission map: local north/east plane (m) around home. Pan (drag), zoom (wheel),
// waypoint editing (add / drag / delete), runway + approach geometry, tracks, wind arrow.
import { h, cssVar, fmt } from "./core.js";
import { MODE_BAND } from "./charts.js";

export function missionMap(el, { height = 460, editable = false, onChange = null, onSelect = null } = {}) {
  const wrap = h("div", { class: "map-wrap", style: { height: height + "px" } });
  const cv = h("canvas", { tabindex: "0", "aria-label": "Mission map" });
  const info = h("div", { class: "map-info" }, "");
  const tools = h("div", { class: "map-tools" });
  wrap.append(cv, tools, info);
  el.append(wrap);
  let geo = null, wps = [], tracks = [], aircraft = null, fence = null;
  let view = { cx: 0, cy: 0, s: 0.25 };        // cx = east, cy = north, s = px per m
  let mode = "select", sel = -1, drag = null, fitted = false, userView = false;
  const ac = new AbortController();         // window listeners are removed on destroy()

  const btn = (label, m, title) => {
    const b = h("button", { class: "btn btn-sm", title, onclick: () => { mode = m; refreshTools(); } }, label);
    b.dataset.mode = m; return b;
  };
  function refreshTools() {
    for (const b of tools.querySelectorAll("button[data-mode]")) b.classList.toggle("btn-primary", b.dataset.mode === mode);
    cv.style.cursor = mode === "add" ? "copy" : "crosshair";
  }
  if (editable) {
    tools.append(btn("Select / move", "select", "Drag a waypoint to move it; Delete key removes the selected one"),
      btn("Add waypoint", "add", "Click on the map to append a waypoint"));
  }
  tools.append(h("button", { class: "btn btn-sm", title: "Zoom to fit the mission", onclick: () => { userView = false; fit(); draw(); } }, "Fit"));
  refreshTools();

  const W = () => wrap.clientWidth, H = () => height;
  const toPx = (e_, n_) => [W() / 2 + (e_ - view.cx) * view.s, H() / 2 - (n_ - view.cy) * view.s];
  const toW = (x, y) => [view.cx + (x - W() / 2) / view.s, view.cy - (y - H() / 2) / view.s];

  function fit() {
    const pts = [[0, 0]];
    for (const w of wps) pts.push([w.e, w.n]);
    if (geo) for (const k of ["align", "entry", "td"]) if (geo.approach?.[k]) pts.push([geo.approach[k][1], geo.approach[k][0]]);
    for (const t of tracks) for (let i = 0; i < t.e.length; i += 20) pts.push([t.e[i], t.n[i]]);
    const es = pts.map((p) => p[0]), ns = pts.map((p) => p[1]);
    const e0 = Math.min(...es), e1 = Math.max(...es), n0 = Math.min(...ns), n1 = Math.max(...ns);
    view.cx = (e0 + e1) / 2; view.cy = (n0 + n1) / 2;
    view.s = Math.min((W() - 90) / Math.max(e1 - e0, 200), (H() - 90) / Math.max(n1 - n0, 200));
    fitted = true;
  }

  function draw() {
    const w = W(), hh = H(), dpr = window.devicePixelRatio || 1;
    cv.width = w * dpr; cv.height = hh * dpr; cv.style.width = w + "px"; cv.style.height = hh + "px";
    const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = cssVar("--chart-bg"); ctx.fillRect(0, 0, w, hh);
    // grid
    const span = w / view.s; const steps = [50, 100, 200, 500, 1000, 2000, 5000];
    const g = steps.find((s) => span / s < 12) || 5000;
    const [e0, n1] = toW(0, 0), [e1, n0] = toW(w, hh);
    ctx.strokeStyle = cssVar("--grid"); ctx.lineWidth = 1; ctx.font = "10.5px system-ui"; ctx.fillStyle = cssVar("--text-3");
    for (let e = Math.ceil(e0 / g) * g; e <= e1; e += g) { const [x] = toPx(e, 0); ctx.beginPath(); ctx.moveTo(x + .5, 0); ctx.lineTo(x + .5, hh); ctx.stroke(); ctx.fillText(`${e} m E`, x + 3, hh - 4); }
    for (let n = Math.ceil(n0 / g) * g; n <= n1; n += g) { const [, y] = toPx(0, n); ctx.beginPath(); ctx.moveTo(0, y + .5); ctx.lineTo(w, y + .5); ctx.stroke(); if (y < hh - 22) ctx.fillText(`${n} m N`, 3, y - 3); }
    // geofence
    if (fence) { const [cx, cy] = toPx(0, 0); ctx.setLineDash([6, 4]); ctx.strokeStyle = cssVar("--warn"); ctx.beginPath();
      ctx.arc(cx, cy, fence * view.s, 0, 7); ctx.stroke(); ctx.setLineDash([]); }
    // runway & approach
    if (geo?.runway) {
      const [s, e] = [geo.runway.start, geo.runway.end];
      const [xs, ys] = toPx(s[1], s[0]), [xe, ye] = toPx(e[1], e[0]);
      ctx.strokeStyle = cssVar("--text-2"); ctx.lineWidth = Math.max(3, geo.runway.width * view.s); ctx.lineCap = "butt";
      ctx.beginPath(); ctx.moveTo(xs, ys); ctx.lineTo(xe, ye); ctx.stroke(); ctx.lineWidth = 1;
      const ap = geo.approach;
      if (ap) {
        ctx.setLineDash([3, 4]); ctx.strokeStyle = cssVar("--s3"); ctx.lineWidth = 1.5; ctx.beginPath();
        const pa = toPx(ap.align[1], ap.align[0]), pt = toPx(ap.td[1], ap.td[0]);
        ctx.moveTo(...pa); ctx.lineTo(...pt); ctx.stroke(); ctx.setLineDash([]);
        for (const k of ["align", "entry", "faf", "td"]) {
          const [x, y] = toPx(ap[k][1], ap[k][0]); ctx.fillStyle = cssVar("--s3"); ctx.fillRect(x - 3, y - 3, 6, 6);
          ctx.fillStyle = cssVar("--text-2"); ctx.fillText(k.toUpperCase(), x + 5, y - 5);
        }
      }
    }
    // planned route
    if (wps.length) {
      ctx.strokeStyle = cssVar("--accent"); ctx.lineWidth = 1.5; ctx.beginPath();
      const start = geo?.climbout ? toPx(geo.climbout[1], geo.climbout[0]) : toPx(0, 0);
      ctx.moveTo(...start); for (const p of wps) ctx.lineTo(...toPx(p.e, p.n));
      if (geo?.approach) ctx.lineTo(...toPx(geo.approach.align[1], geo.approach.align[0]));
      ctx.stroke();
    }
    // tracks
    for (const t of tracks) {
      ctx.lineWidth = 2;
      for (let i = 1; i < t.e.length; i++) {
        const band = t.mode ? MODE_BAND[t.mode[i]] : null;
        ctx.strokeStyle = t.color || (band ? cssVar(band) : cssVar("--s1"));
        ctx.beginPath(); ctx.moveTo(...toPx(t.e[i - 1], t.n[i - 1])); ctx.lineTo(...toPx(t.e[i], t.n[i])); ctx.stroke();
      }
    }
    // waypoints
    ctx.font = "11.5px system-ui";
    wps.forEach((p, i) => {
      const [x, y] = toPx(p.e, p.n);
      ctx.fillStyle = i === sel ? cssVar("--alarm") : cssVar("--accent");
      ctx.beginPath(); ctx.arc(x, y, i === sel ? 7 : 6, 0, 7); ctx.fill();
      ctx.strokeStyle = cssVar("--chart-bg"); ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = cssVar("--text"); ctx.fillText(`${p.name || "WP" + (i + 1)}  ${fmt.n(p.alt, 0)} m`, x + 9, y - 7);
    });
    // home
    const [hx, hy] = toPx(0, 0); ctx.strokeStyle = cssVar("--text"); ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(hx - 6, hy); ctx.lineTo(hx + 6, hy); ctx.moveTo(hx, hy - 6); ctx.lineTo(hx, hy + 6); ctx.stroke();
    // aircraft
    if (aircraft) {
      const [x, y] = toPx(aircraft.e, aircraft.n), a = aircraft.psi_deg * Math.PI / 180;
      ctx.save(); ctx.translate(x, y); ctx.rotate(a); ctx.fillStyle = cssVar("--alarm");
      ctx.beginPath(); ctx.moveTo(0, -10); ctx.lineTo(6, 7); ctx.lineTo(0, 4); ctx.lineTo(-6, 7); ctx.closePath(); ctx.fill(); ctx.restore();
    }
    // wind arrow (points where the air goes)
    if (geo?.wind10 && Math.hypot(...geo.wind10) > 0.05) {
      const [wn, we] = geo.wind10, sp = Math.hypot(wn, we), cx = w - 80, cy = 46, L = 26;
      const ux = we / sp, uy = -wn / sp;
      ctx.strokeStyle = cssVar("--text"); ctx.fillStyle = cssVar("--text"); ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(cx - ux * L, cy - uy * L); ctx.lineTo(cx + ux * L, cy + uy * L); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(cx + ux * L, cy + uy * L); ctx.lineTo(cx + ux * (L - 9) - uy * 5, cy + uy * (L - 9) + ux * 5);
      ctx.lineTo(cx + ux * (L - 9) + uy * 5, cy + uy * (L - 9) - ux * 5); ctx.closePath(); ctx.fill();
      ctx.font = "11px system-ui"; ctx.textAlign = "center"; ctx.fillText(`wind ${sp.toFixed(1)} m/s @10 m`, cx, cy + 42); ctx.textAlign = "left";
    }
    // scale bar
    ctx.fillStyle = cssVar("--text-2"); const sb = g * view.s;
    ctx.fillRect(w - 20 - sb, hh - 22, sb, 2); ctx.fillText(`${g} m`, w - 20 - sb, hh - 26);
  }

  function hit(x, y) {
    for (let i = wps.length - 1; i >= 0; i--) { const [px, py] = toPx(wps[i].e, wps[i].n); if ((px - x) ** 2 + (py - y) ** 2 < 100) return i; }
    return -1;
  }
  cv.addEventListener("mousedown", (e) => {
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const i = editable ? hit(x, y) : -1;
    if (editable && mode === "add" && i < 0) {
      const [ee, nn] = toW(x, y); const last = wps[wps.length - 1];
      wps.push({ name: `WP${wps.length + 1}`, n: Math.round(nn), e: Math.round(ee), alt: last ? last.alt : 100 });
      sel = wps.length - 1; onChange?.(wps, "add"); onSelect?.(sel); draw(); return;
    }
    if (i >= 0) { sel = i; drag = { kind: "wp", i }; onSelect?.(i); }
    else drag = { kind: "pan", x, y, cx: view.cx, cy: view.cy };
    draw();
  });
  window.addEventListener("mousemove", (e) => {
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (x >= 0 && y >= 0 && x <= W() && y <= H()) { const [ee, nn] = toW(x, y); info.textContent = `N ${nn.toFixed(0)} m   E ${ee.toFixed(0)} m`; }
    if (!drag) return;
    if (drag.kind === "pan") { view.cx = drag.cx - (x - drag.x) / view.s; view.cy = drag.cy + (y - drag.y) / view.s; userView = true; }
    else { const [ee, nn] = toW(x, y); wps[drag.i].e = Math.round(ee); wps[drag.i].n = Math.round(nn); drag.moved = true; }
    draw();
  }, { signal: ac.signal });
  window.addEventListener("mouseup", () => { if (drag?.kind === "wp" && drag.moved) onChange?.(wps, "move"); drag = null; },
    { signal: ac.signal });
  cv.addEventListener("wheel", (e) => {
    e.preventDefault(); const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const [ee, nn] = toW(x, y); view.s *= e.deltaY < 0 ? 1.15 : 1 / 1.15; userView = true;
    view.cx = ee - (x - W() / 2) / view.s; view.cy = nn + (y - H() / 2) / view.s; draw();
  }, { passive: false });
  cv.addEventListener("keydown", (e) => {
    if (editable && (e.key === "Delete" || e.key === "Backspace") && sel >= 0) {
      wps.splice(sel, 1); sel = -1; onChange?.(wps, "delete"); draw();
    }
  });
  const ro = new ResizeObserver(() => { if (!fitted) fit(); draw(); }); ro.observe(wrap);

  return {
    setGeometry(g) { geo = g; fence = null; draw(); },
    setFence(r) { fence = r; draw(); },
    // auto-fit to new content until the user pans or zooms by hand
    setWaypoints(list, refit = false) { wps = list; if (refit || !userView) fit(); draw(); },
    setTracks(t, refit = false) { tracks = t; if (refit || (!userView && !wps.length)) fit(); draw(); },
    setAircraft(a) { aircraft = a; draw(); },
    select(i) { sel = i; draw(); },
    fit() { fit(); draw(); },
    destroy() { ro.disconnect(); ac.abort(); wrap.remove(); },
  };
}
