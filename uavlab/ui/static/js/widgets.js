// Engineering form widgets: schema-driven property grid and editable tables.
import { h, clear, get, set, state, fmt } from "./core.js";

function parseValue(f, raw) {
  if (f.type === "bool") return !!raw;
  if (f.type === "enum" || f.type === "str") return raw;
  if (f.type === "list") {
    const parts = String(raw).split(/[,;\s]+/).filter(Boolean).map(Number);
    if (parts.some((x) => !Number.isFinite(x))) throw new Error("enter numbers separated by commas");
    return parts;
  }
  if (raw === "" || raw === null) {
    if (f.nullable) return null;
    throw new Error("a value is required");
  }
  const v = Number(raw);
  if (!Number.isFinite(v)) throw new Error("not a number");
  if (f.type === "int" && !Number.isInteger(v)) throw new Error("must be a whole number");
  if (f.min !== undefined && v < f.min) throw new Error(`minimum ${f.min}`);
  if (f.max !== undefined && v > f.max) throw new Error(`maximum ${f.max}`);
  return v;
}

// fields: schema fields; the grid edits state.config in place.
export function propertyGrid(el, fields, { onChange, filter = "", title } = {}) {
  const table = h("table", { class: "pgrid" });
  const cfg = state.config, dft = state.defaults;
  let lastSec = null;
  const q = filter.trim().toLowerCase();
  const shown = fields.filter((f) => !q || f.path.toLowerCase().includes(q) || f.label.toLowerCase().includes(q) ||
    (f.description || "").toLowerCase().includes(q));
  // keep every section together, in order of first appearance
  const order = new Map();
  shown.forEach((f) => { const k = f.group + "." + f.section; if (!order.has(k)) order.set(k, order.size); });
  shown.sort((a, b) => order.get(a.group + "." + a.section) - order.get(b.group + "." + b.section));
  if (!shown.length) { el.append(h("div", { class: "empty" }, "No parameter matches the search.")); return; }
  for (const f of shown) {
    const sec = f.group + "." + f.section;
    if (sec !== lastSec) {
      lastSec = sec;
      const secLabel = (f.section === "general" ? f.group : f.section).replaceAll(".", " / ").replaceAll("_", " ");
      table.append(h("tr", { class: "sec" }, h("td", { colspan: 4 }, secLabel)));
    }
    const cur = get(cfg, f.path), def = get(dft, f.path);
    const tr = h("tr", { class: JSON.stringify(cur) !== JSON.stringify(def) ? "modified" : "" });
    const id = "f_" + f.path.replaceAll(".", "_");
    let input;
    if (f.type === "bool") {
      input = h("input", { type: "checkbox", id });
      input.checked = !!cur;
    } else if (f.type === "enum") {
      input = h("select", { id }, f.choices.map((c) => h("option", { value: c, selected: c === cur }, c)));
    } else if (f.type === "list") {
      input = h("input", { type: "text", id, value: (cur || []).join(", ") });
    } else if (f.type === "str") {
      input = h("input", { type: "text", id, value: cur ?? "" });
    } else {
      input = h("input", { type: "number", id, step: "any", value: cur ?? "",
        placeholder: f.nullable ? "auto" : "", min: f.min, max: f.max });
    }
    const errEl = h("div", { class: "d", style: { color: "var(--alarm)" } });
    const commit = () => {
      try {
        const raw = f.type === "bool" ? input.checked : input.value;
        const v = parseValue(f, raw);
        set(cfg, f.path, v);
        input.classList.remove("invalid"); errEl.textContent = "";
        tr.classList.toggle("modified", JSON.stringify(v) !== JSON.stringify(def));
        onChange?.(f, v);
      } catch (e) { input.classList.add("invalid"); errEl.textContent = e.message; }
    };
    input.addEventListener("change", commit);
    const reset = h("button", { class: "rbtn", title: `Reset to default (${fmt.auto(def)})`, "aria-label": "Reset to default",
      onclick: () => {
        set(cfg, f.path, JSON.parse(JSON.stringify(def)));
        if (f.type === "bool") input.checked = !!def; else input.value = Array.isArray(def) ? def.join(", ") : (def ?? "");
        input.classList.remove("invalid"); errEl.textContent = ""; tr.classList.remove("modified"); onChange?.(f, def);
      } }, "↺");
    tr.append(
      h("td", { class: "lab" }, h("label", { class: "l", for: id }, h("span", {}, f.label),
        f.tag ? h("span", { class: `tag ${f.tag}`, title: tagTitle(f.tag) }, f.tag) : null),
      f.description ? h("div", { class: "d" }, f.description) : null, errEl),
      h("td", { class: "val" }, input), h("td", { class: "unit" }, f.unit), h("td", { class: "rst" }, reset));
    table.append(tr);
  }
  el.append(table);
}

export function tagTitle(t) {
  return { REP: "Representative value for this aircraft class: replace with your measured hardware",
    DATA: "From a manufacturer data file", SPEC: "From a published standard or specification",
    TUNE: "Controller tuning value" }[t] || t;
}

// columns: [{key, label, unit?, type: "num"|"text"|"select", options?, optional?, width?}]
export function editTable(el, { columns, rows, onChange, newRow, minRows = 0, reorder = true, emptyText = "No rows." }) {
  const wrap = h("div", {});
  el.append(wrap);
  function render() {
    clear(wrap);
    const tb = h("table", { class: "tbl edit" });
    tb.append(h("thead", {}, h("tr", {}, h("th", { style: { width: "32px" } }, "#"),
      columns.map((c) => h("th", { style: c.width ? { width: c.width } : {} }, c.label + (c.unit ? ` (${c.unit})` : ""))),
      h("th", { style: { width: reorder ? "96px" : "40px" } }, ""))));
    const body = h("tbody");
    rows.forEach((r, i) => {
      const tr = h("tr");
      tr.append(h("td", { class: "n muted" }, i + 1));
      for (const c of columns) {
        let inp;
        if (c.type === "select") inp = h("select", {}, c.options.map((o) => h("option", { value: o, selected: String(r[c.key]) === String(o) }, o)));
        else inp = h("input", { type: c.type === "num" ? "number" : "text", step: "any", value: r[c.key] ?? "",
          placeholder: c.optional ? "default" : "", "aria-label": `${c.label} row ${i + 1}` });
        inp.addEventListener("change", () => {
          let v = inp.value;
          if (c.type === "num") {
            if (v === "" && c.optional) { delete r[c.key]; inp.classList.remove("invalid"); onChange?.(rows); return; }
            v = Number(v);
            if (!Number.isFinite(v)) { inp.classList.add("invalid"); return; }
          }
          inp.classList.remove("invalid"); r[c.key] = v; onChange?.(rows);
        });
        tr.append(h("td", {}, inp));
      }
      const act = h("td", { class: "row", style: { flexWrap: "nowrap", gap: "2px" } });
      if (reorder) {
        act.append(h("button", { class: "btn btn-sm btn-icon", title: "Move up", disabled: i === 0,
          onclick: () => { [rows[i - 1], rows[i]] = [rows[i], rows[i - 1]]; onChange?.(rows); render(); } }, "↑"),
        h("button", { class: "btn btn-sm btn-icon", title: "Move down", disabled: i === rows.length - 1,
          onclick: () => { [rows[i + 1], rows[i]] = [rows[i], rows[i + 1]]; onChange?.(rows); render(); } }, "↓"));
      }
      act.append(h("button", { class: "btn btn-sm btn-icon btn-danger", title: "Delete row", disabled: rows.length <= minRows,
        onclick: () => { rows.splice(i, 1); onChange?.(rows); render(); } }, "×"));
      tr.append(act);
      body.append(tr);
    });
    tb.append(body);
    wrap.append(h("div", { class: "tbl-wrap" }, tb));
    if (!rows.length) wrap.append(h("div", { class: "hint", style: { padding: "6px" } }, emptyText));
    if (newRow) wrap.append(h("div", { style: { marginTop: "6px" } },
      h("button", { class: "btn btn-sm", onclick: () => { rows.push(newRow(rows)); onChange?.(rows); render(); } }, "Add row")));
  }
  render();
  return { render };
}

// Sortable read-only table. cols: [{key, label, fmt?, num?}]; onRow(row)
export function dataTable(el, { cols, rows, onRow, selected, maxHeight = 520, sortKey, sortDir = -1, rowClass }) {
  let sk = sortKey, sd = sortDir;
  const wrap = h("div", { class: "tbl-wrap", style: { maxHeight: maxHeight + "px" } });
  el.append(wrap);
  function render() {
    clear(wrap);
    const data = [...rows];
    if (sk) data.sort((a, b) => {
      const x = a[sk], y = b[sk];
      if (x == null) return 1; if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * sd;
    });
    const t = h("table", { class: "tbl" });
    t.append(h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: "sortable", title: "Sort",
      onclick: () => { if (sk === c.key) sd = -sd; else { sk = c.key; sd = c.num ? -1 : 1; } render(); } },
      c.label, sk === c.key ? (sd > 0 ? " ▲" : " ▼") : "")))));
    const tb = h("tbody");
    for (const r of data) {
      const tr = h("tr", { class: `${onRow ? "clickable" : ""} ${selected?.(r) ? "sel" : ""} ${rowClass?.(r) || ""}`,
        onclick: () => onRow?.(r) });
      for (const c of cols) {
        const v = r[c.key];
        const cell = c.fmt ? c.fmt(v, r) : fmt.auto(v);
        tr.append(h("td", { class: c.num ? "n" : "" }, cell));
      }
      tb.append(tr);
    }
    t.append(tb);
    wrap.append(t);
    if (!rows.length) wrap.append(h("div", { class: "empty" }, "Nothing here yet."));
  }
  render();
  return { render, setRows(r) { rows = r; render(); } };
}
