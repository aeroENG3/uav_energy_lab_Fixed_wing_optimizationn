// Core helpers: DOM builder, API client, formatting, toasts, modal, app state.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

// replace the children of el, skipping null / undefined / false entries
export function fill(el, ...kids) {
  clear(el);
  for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined && k !== false) el.append(k);
  return el;
}

export async function api(path, body, opts = {}) {
  const init = body === undefined ? { method: opts.method || "GET" } :
    { method: opts.method || "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let r;
  try { r = await fetch(path, init); }
  catch (e) { throw new Error("The lab server is not reachable. Is `python -m uavlab ui` still running?"); }
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = j.detail ? (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) : msg; } catch (_) {}
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

export const fmt = {
  n(v, d = 2) { return v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toFixed(d); },
  int(v) { return v === null || v === undefined ? "–" : Math.round(v).toLocaleString("en-US"); },
  pct(v, d = 1) { return v === null || v === undefined ? "–" : (100 * v).toFixed(d) + " %"; },
  dur(s) {
    if (s === null || s === undefined) return "–";
    const m = Math.floor(s / 60), r = Math.round(s % 60);
    return m ? `${m} min ${String(r).padStart(2, "0")} s` : `${r} s`;
  },
  time(ts) { const d = new Date(ts * 1000); return d.toLocaleString("en-GB", { dateStyle: "short", timeStyle: "medium" }); },
  auto(v) {
    if (v === null || v === undefined) return "–";
    if (typeof v === "number") return Math.abs(v) >= 1000 || Number.isInteger(v) ? String(Math.round(v * 1000) / 1000) : String(parseFloat(v.toPrecision(4)));
    return String(v);
  },
};

export function statusChip(status) {
  const map = { LANDED: "ok", done: "ok", PASS: "ok", CRASHED: "alarm", failed: "alarm", FAIL: "alarm", NO_GO: "warn",
    TIMEOUT: "warn", cancelled: "warn", running: "run", queued: "neutral", RUNNING: "run" };
  return h("span", { class: `chip ${map[status] || "neutral"}` }, String(status || "–").replace("_", " "));
}

export function toast(msg, kind = "") {
  const t = h("div", { class: `toast ${kind}`, role: "status" }, msg);
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), kind === "alarm" ? 9000 : 4500);
}

export function modal(title, body, buttons = []) {
  const root = document.getElementById("modal-root");
  const close = () => { clear(root); document.removeEventListener("keydown", esc); };
  const esc = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", esc);
  const box = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title },
    h("div", { class: "mh" }, title, h("button", { class: "btn btn-sm btn-ghost", onclick: close, "aria-label": "Close" }, "Close")),
    h("div", { class: "mb" }, body),
    buttons.length ? h("div", { class: "mf" }, buttons.map((b) =>
      h("button", { class: `btn ${b.primary ? "btn-primary" : ""} ${b.danger ? "btn-danger" : ""}`,
        onclick: async () => { const keep = await b.onclick?.(); if (!keep) close(); } }, b.label))) : null);
  clear(root).append(h("div", { class: "modal-back", onclick: (e) => { if (e.target.classList.contains("modal-back")) close(); } }, box));
  return { close };
}

export function confirmBox(title, text, okLabel = "Confirm") {
  return new Promise((res) => {
    modal(title, h("p", {}, text), [
      { label: "Cancel", onclick: () => res(false) },
      { label: okLabel, primary: true, onclick: () => res(true) }]);
  });
}

export function debounce(fn, ms = 400) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export function get(obj, path) { return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj); }
export function set(obj, path, val) {
  const ks = path.split("."); let o = obj;
  for (const k of ks.slice(0, -1)) { if (o[k] == null || typeof o[k] !== "object") o[k] = {}; o = o[k]; }
  o[ks[ks.length - 1]] = val;
}
export const clone = (o) => JSON.parse(JSON.stringify(o));
export function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
export const SERIES = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"];
export const seriesColor = (i) => cssVar(SERIES[i % SERIES.length]);

export function download(url) { const a = h("a", { href: url }); document.body.append(a); a.click(); a.remove(); }

export const icons = {
  overview: '<path d="M2 2h5v5H2zM9 2h5v3H9zM9 7h5v7H9zM2 9h5v5H2z"/>',
  scenario: '<path d="M2 3h12M2 8h12M2 13h12"/><circle cx="5" cy="3" r="1.6"/><circle cx="10" cy="8" r="1.6"/><circle cx="7" cy="13" r="1.6"/>',
  live: '<path d="M1 9h3l2-5 3 9 2-6 1 2h3"/>',
  results: '<path d="M2 14V2M2 14h12M5 11V7M8 11V4M11 11V8"/>',
  compare: '<path d="M4 2v12M12 2v12M1 6h6M9 10h6"/>',
  doe: '<path d="M2 2h4v4H2zM10 2h4v4h-4zM2 10h4v4H2zM10 10h4v4h-4z"/>',
  opt: '<path d="M2 13c3-9 5-9 6-2s3 5 6-8"/><circle cx="8" cy="11" r="1.5"/>',
  perf: '<path d="M2 3c2 9 5 11 12 11M2 14h12"/>',
  vv: '<path d="M3 8l3 3 7-7"/><path d="M2 2h12v12H2z"/>',
  book: '<path d="M3 2h8l2 2v10H3zM6 6h5M6 9h5"/>',
  jobs: '<path d="M2 4h12M2 8h12M2 12h8"/>',
};
export function icon(name, size = 16) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 16 16"); s.setAttribute("width", size); s.setAttribute("height", size);
  s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", "1.4");
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = icons[name] || "";
  return s;
}

// ------------------------------------------------------------------ app state
const listeners = new Set();
export const state = {
  schema: null, meta: null, defaults: null,
  config: null, name: "untitled", dirty: false, lastRunRef: null,
  compare: [], activeJobId: null, jobs: [],
  on(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  emit(what) { for (const fn of listeners) { try { fn(what); } catch (e) { console.error(e); } } },
  setConfig(cfg, name, dirty = false) {
    this.config = cfg; if (name !== undefined) this.name = name; this.dirty = dirty;
    this.persist(); this.emit("config");
  },
  touch() { this.dirty = true; this.persist(); this.emit("dirty"); },
  persist() {
    try { localStorage.setItem("uavlab.scenario", JSON.stringify({ config: this.config, name: this.name, dirty: this.dirty })); } catch (_) {}
  },
  restore() {
    try { const s = JSON.parse(localStorage.getItem("uavlab.scenario") || "null"); if (s && s.config) return s; } catch (_) {}
    return null;
  },
};

export function fieldByPath(path) { return state.schema.fields.find((f) => f.path === path); }
export function modifiedCount(prefix = "") {
  if (!state.schema || !state.config) return 0;
  let n = 0;
  for (const f of state.schema.fields) {
    if (prefix && !f.path.startsWith(prefix)) continue;
    if (JSON.stringify(get(state.config, f.path)) !== JSON.stringify(get(state.defaults, f.path))) n++;
  }
  return n;
}
