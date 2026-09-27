// Charts: uPlot time series (with flight-mode bands and a synchronised cursor),
// a canvas XY plot (profiles, scatter, convergence) and simple horizontal bars.
import { h, cssVar, seriesColor, fmt } from "./core.js";

export const MODE_BAND = {
  TAKEOFF_ROLL: "--s2", ROTATE: "--s2", CLIMB_OUT: "--s4", APPROACH: "--s3", GO_AROUND: "--s8",
  FLARE: "--s5", ROLLOUT: "--s7",
};

function axis(label) {
  return {
    label, stroke: cssVar("--text-2"), labelSize: 16, size: 48, font: "11px system-ui", labelFont: "11px system-ui",
    grid: { stroke: cssVar("--grid"), width: 1 }, ticks: { stroke: cssVar("--grid"), width: 1 },
  };
}

// Time-series chart. series: [{label, color?, dash?, width?}]
export function timeChart(el, { series, yLabel = "", height = 180, sync = "tsync", modes = true, xLabel = "time (s)" }) {
  const box = h("div", { class: "chart" });
  el.append(box);
  let modeArr = null, xArr = null;
  const opts = {
    width: Math.max(box.clientWidth, 300), height,
    cursor: { sync: { key: sync }, drag: { x: true, y: false } },
    scales: { x: { time: false } },
    axes: [axis(xLabel), axis(yLabel)],
    legend: { live: true },
    series: [{ label: "t (s)", value: (u, v) => (v == null ? "–" : v.toFixed(1)) },
      ...series.map((s, i) => ({
        label: s.label, stroke: s.color || seriesColor(i), width: s.width || 1.5, dash: s.dash,
        value: (u, v) => (v == null ? "–" : fmt.auto(v)), points: { show: false },
      }))],
    hooks: {
      drawClear: [(u) => {
        if (!modes || !modeArr || !xArr || !xArr.length) return;
        const ctx = u.ctx; ctx.save(); ctx.globalAlpha = 0.10;
        let i0 = 0;
        for (let i = 1; i <= modeArr.length; i++) {
          if (i === modeArr.length || modeArr[i] !== modeArr[i0]) {
            const band = MODE_BAND[modeArr[i0]];
            if (band) {
              const x0 = u.valToPos(xArr[i0], "x", true), x1 = u.valToPos(xArr[Math.min(i, xArr.length - 1)], "x", true);
              ctx.fillStyle = cssVar(band);
              ctx.fillRect(x0, u.bbox.top, Math.max(1, x1 - x0), u.bbox.height);
            }
            i0 = i;
          }
        }
        ctx.restore();
      }],
    },
  };
  const u = new uPlot(opts, [[], ...series.map(() => [])], box);
  const ro = new ResizeObserver(() => { const w = box.clientWidth; if (w > 50) u.setSize({ width: w, height }); });
  ro.observe(box);
  return {
    u,
    setData(x, ys, modeList) {
      xArr = x; modeArr = modeList || null;
      u.setData([x, ...ys], true);
    },
    destroy() { ro.disconnect(); u.destroy(); box.remove(); },
  };
}

// ----------------------------------------------------------------- XY canvas plot
function niceStep(range, n) {
  const raw = range / Math.max(n, 1), p = Math.pow(10, Math.floor(Math.log10(raw))), r = raw / p;
  return (r < 1.5 ? 1 : r < 3 ? 2 : r < 7 ? 5 : 10) * p;
}
function ticks(lo, hi, n = 6) {
  if (!(hi > lo)) { hi = lo + 1; }
  const s = niceStep(hi - lo, n), out = [];
  for (let v = Math.ceil(lo / s) * s; v <= hi + 1e-9 * s; v += s) out.push(Math.abs(v) < s * 1e-9 ? 0 : v);
  return out;
}

// series: [{label, points: [[x, y], ...], color?, mode: "line"|"scatter"|"both", dash?, size?}]
export function xyPlot(el, { height = 240, xLabel = "", yLabel = "", xDomain, yDomain, series = [], vlines = [], legend = true }) {
  const wrap = h("div", { class: "chart", style: { height: height + "px" } });
  const cv = h("canvas", { class: "xy" });
  const tip = h("div", { style: { position: "absolute", pointerEvents: "none", fontSize: "11.5px", fontFamily: "var(--mono)",
    background: "var(--panel)", border: "1px solid var(--border)", padding: "2px 5px", display: "none" } });
  wrap.append(cv, tip);
  const leg = legend ? h("div", { class: "legend-row" }) : null;
  el.append(wrap); if (leg) el.append(leg);
  let data = series, pts = [];
  const pad = { l: 56, r: 12, t: 10, b: 36 };

  function draw() {
    const W = wrap.clientWidth, H = height, dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + "px";
    const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
    const all = data.flatMap((s) => s.points).filter((p) => p && Number.isFinite(p[0]) && Number.isFinite(p[1]));
    let [x0, x1] = xDomain || [Math.min(...all.map((p) => p[0])), Math.max(...all.map((p) => p[0]))];
    let [y0, y1] = yDomain || [Math.min(...all.map((p) => p[1])), Math.max(...all.map((p) => p[1]))];
    if (!all.length) { x0 = 0; x1 = 1; y0 = 0; y1 = 1; }
    if (x1 === x0) { x0 -= 1; x1 += 1; }
    if (y1 === y0) { y0 -= 1; y1 += 1; }
    if (!yDomain) { const m = (y1 - y0) * 0.06; y0 -= m; y1 += m; }
    if (!xDomain) { const m = (x1 - x0) * 0.03; x0 -= m; x1 += m; }
    const X = (v) => pad.l + (v - x0) / (x1 - x0) * (W - pad.l - pad.r);
    const Y = (v) => H - pad.b - (v - y0) / (y1 - y0) * (H - pad.t - pad.b);
    ctx.font = "11px system-ui"; ctx.strokeStyle = cssVar("--grid"); ctx.fillStyle = cssVar("--text-2"); ctx.lineWidth = 1;
    for (const t of ticks(x0, x1)) { const x = Math.round(X(t)) + .5; ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, H - pad.b); ctx.stroke();
      ctx.textAlign = "center"; ctx.fillText(fmt.auto(+t.toPrecision(6)), x, H - pad.b + 14); }
    for (const t of ticks(y0, y1, 5)) { const y = Math.round(Y(t)) + .5; ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
      ctx.textAlign = "right"; ctx.fillText(fmt.auto(+t.toPrecision(6)), pad.l - 5, y + 4); }
    ctx.textAlign = "center"; ctx.fillText(xLabel, (pad.l + W - pad.r) / 2, H - 6);
    ctx.save(); ctx.translate(12, (pad.t + H - pad.b) / 2); ctx.rotate(-Math.PI / 2); ctx.fillText(yLabel, 0, 0); ctx.restore();
    for (const v of vlines) { const x = X(v.x); ctx.setLineDash([4, 3]); ctx.strokeStyle = cssVar("--text-3");
      ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, H - pad.b); ctx.stroke(); ctx.setLineDash([]);
      if (v.label) { ctx.fillStyle = cssVar("--text-2"); ctx.textAlign = "left"; ctx.fillText(v.label, x + 4, pad.t + 11); } }
    pts = [];
    data.forEach((s, i) => {
      const col = s.color || seriesColor(i); const P = s.points.filter((p) => p && Number.isFinite(p[0]) && Number.isFinite(p[1]));
      ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = s.width || 2;
      if (s.mode !== "scatter" && P.length > 1) {
        ctx.setLineDash(s.dash || []); ctx.beginPath();
        P.forEach((p, k) => (k ? ctx.lineTo(X(p[0]), Y(p[1])) : ctx.moveTo(X(p[0]), Y(p[1])))); ctx.stroke(); ctx.setLineDash([]);
      }
      if (s.mode === "scatter" || s.mode === "both") {
        for (const p of P) {
          const c = p[2] !== undefined && s.colorOf ? s.colorOf(p[2]) : col;
          ctx.fillStyle = c; ctx.beginPath(); ctx.arc(X(p[0]), Y(p[1]), s.size || 4, 0, 7); ctx.fill();
          ctx.strokeStyle = cssVar("--chart-bg"); ctx.lineWidth = 1; ctx.stroke();
        }
      }
      for (const p of P) pts.push({ x: X(p[0]), y: Y(p[1]), p, s });
    });
    if (leg) { leg.innerHTML = ""; data.forEach((s, i) => { if (s.label) leg.append(h("span", {}, h("i", { style: { background: s.color || seriesColor(i) } }), s.label)); }); }
  }
  cv.addEventListener("mousemove", (e) => {
    const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    let best = null, bd = 400;
    for (const q of pts) { const d = (q.x - mx) ** 2 + (q.y - my) ** 2; if (d < bd) { bd = d; best = q; } }
    if (!best) { tip.style.display = "none"; return; }
    tip.style.display = "block"; tip.style.left = Math.min(best.x + 8, wrap.clientWidth - 160) + "px"; tip.style.top = Math.max(best.y - 28, 0) + "px";
    tip.textContent = `${best.s.label ? best.s.label + ": " : ""}${fmt.auto(best.p[0])}, ${fmt.auto(best.p[1])}${best.p[3] ? "  " + best.p[3] : ""}`;
  });
  cv.addEventListener("mouseleave", () => { tip.style.display = "none"; });
  const ro = new ResizeObserver(draw); ro.observe(wrap);
  draw();
  return { update(s) { data = s; draw(); }, destroy() { ro.disconnect(); wrap.remove(); leg?.remove(); } };
}

// horizontal bars: items [{label, value, color?}]
export function bars(el, items, unit = "") {
  const max = Math.max(...items.map((i) => Math.abs(i.value || 0)), 1e-9);
  const t = h("div", { style: { display: "grid", gridTemplateColumns: "minmax(120px, 190px) 1fr 80px", gap: "4px 8px", alignItems: "center", fontSize: "12.5px" } });
  for (const it of items) {
    t.append(h("div", { class: "muted" }, it.label),
      h("div", { style: { background: "var(--panel-2)", border: "1px solid var(--border-soft)", height: "14px" } },
        h("div", { style: { width: `${100 * Math.abs(it.value || 0) / max}%`, height: "100%", background: it.color || "var(--s1)" } })),
      h("div", { class: "num", style: { textAlign: "right" } }, `${fmt.n(it.value, 2)} ${unit}`));
  }
  el.append(t);
  return t;
}
