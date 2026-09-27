// Builds docs/handbook/handbook.html: one self-contained, theme-aware HTML page.
//   Markdown (docs/handbook/src/*.md, in file-name order)
//   + KaTeX math rendered to MathML at build time ($$ … $$ blocks, $ … $ inline)
//   + inline SVG figures (docs/handbook/figs/*.html, from make_figures.py; placeholder @@FIG:name@@)
//   + the parameter reference generated from configs/defaults.yaml via uavlab.ui.schema (@@PARAMS@@)
// Usage (from tools/handbook):  npm install && npm run build
// HANDBOOK_NODE_MODULES=/path/to/node_modules may point at an existing install instead.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const DOC = path.join(ROOT, "docs", "handbook");
const require = createRequire(process.env.HANDBOOK_NODE_MODULES
  ? path.join(process.env.HANDBOOK_NODE_MODULES, "_resolve.js") : import.meta.url);
const { marked } = require("marked");
const katex = require("katex");

// ------------------------------------------------------------------ helpers
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const slug = (s) => s.toLowerCase().replace(/<[^>]+>/g, "").replace(/&[a-z]+;/g, "").replace(/[^\p{L}\p{N}]+/gu, "-")
  .replace(/^-+|-+$/g, "");
// Chromium's MathML Core ignores mathvariant (bold, script, sans-serif). Map those letters to the
// Unicode mathematical alphanumeric symbols instead, which every engine renders.
const SCRIPT_EXC = { B: 0x212C, E: 0x2130, F: 0x2131, H: 0x210B, I: 0x2110, L: 0x2112, M: 0x2133, R: 0x211B };
function mapChar(ch, variant) {
  const c = ch.codePointAt(0);
  const up = c >= 65 && c <= 90, lo = c >= 97 && c <= 122, dg = c >= 48 && c <= 57;
  const gu = c >= 0x391 && c <= 0x3A9, gl = c >= 0x3B1 && c <= 0x3C9;
  const base = {
    "bold": [0x1D400, 0x1D41A, 0x1D7CE, 0x1D6A8, 0x1D6C2],
    "bold-italic": [0x1D468, 0x1D482, 0x1D7CE, 0x1D71C, 0x1D736],
    "sans-serif": [0x1D5A0, 0x1D5BA, 0x1D7E2, null, null],
    "script": [0x1D49C, 0x1D4B6, null, null, null],
  }[variant];
  if (!base) return ch;
  if (variant === "script" && up && SCRIPT_EXC[ch]) return String.fromCodePoint(SCRIPT_EXC[ch]);
  if (up && base[0]) return String.fromCodePoint(base[0] + c - 65);
  if (lo && base[1]) return String.fromCodePoint(base[1] + c - 97);
  if (dg && base[2]) return String.fromCodePoint(base[2] + c - 48);
  if (gu && base[3]) return String.fromCodePoint(base[3] + c - 0x391);
  if (gl && base[4]) return String.fromCodePoint(base[4] + c - 0x3B1);
  return ch;
}
const fixVariants = (s) => s.replace(/<(mi|mn|mo)([^>]*?) mathvariant="(bold|bold-italic|sans-serif|script)"([^>]*)>([^<]*)<\/\1>/g,
  (_, tag, a, v, b, txt) => `<${tag}${a}${b}${tag === "mi" ? ' mathvariant="normal"' : ""}>${[...txt].map((ch) => mapChar(ch, v)).join("")}</${tag}>`);
const tex = (src, display) => fixVariants(katex.renderToString(src, { displayMode: display, output: "mathml",
  throwOnError: true, strict: "ignore" }));

// ------------------------------------------------------------------ markdown setup
const toc = [];
const usedIds = new Set();
let docTitle = "";

marked.use({
  gfm: true,
  extensions: [
    {
      name: "mathBlock", level: "block",
      start(src) { const m = src.match(/^\$\$/m); return m ? m.index : undefined; },
      tokenizer(src) {
        const m = /^\$\$[ \t]*\n?([\s\S]+?)\n?\$\$[ \t]*(?:\n+|$)/.exec(src);
        if (m) return { type: "mathBlock", raw: m[0], text: m[1].trim() };
      },
      renderer(t) { return `<div class="math-d">${tex(t.text, true)}</div>\n`; },
    },
    {
      name: "mathInline", level: "inline",
      start(src) { const i = src.indexOf("$"); return i < 0 ? undefined : i; },
      tokenizer(src) {
        const m = /^\$(?!\s)((?:\\\$|[^$\n])+?)(?<!\s)\$(?!\d)/.exec(src);
        if (m) return { type: "mathInline", raw: m[0], text: m[1] };
      },
      renderer(t) { return tex(t.text, false); },
    },
  ],
  renderer: {
    heading({ tokens, depth, text }) {
      const inner = this.parser.parseInline(tokens);
      if (depth === 1 && !docTitle) { docTitle = text; return ""; }   // first H1 = page title (in the header)
      let id = slug(text) || `h-${usedIds.size}`;
      while (usedIds.has(id)) id += "-x";
      usedIds.add(id);
      if (depth <= 2) toc.push({ depth, id, html: inner });
      const cls = depth === 1 ? ' class="part"' : "";
      return `<h${depth} id="${id}"${cls}><a class="anchor" href="#${id}" aria-label="Link to this section">#</a>${inner}</h${depth}>\n`;
    },
    table(token) {
      // default table rendering, wrapped in a horizontally scrollable container
      let head = "<tr>" + token.header.map((c) => `<th${c.align ? ` style="text-align:${c.align}"` : ""}>${this.parser.parseInline(c.tokens)}</th>`).join("") + "</tr>";
      let body = token.rows.map((r) => "<tr>" + r.map((c) => `<td${c.align ? ` style="text-align:${c.align}"` : ""}>${this.parser.parseInline(c.tokens)}</td>`).join("") + "</tr>").join("\n");
      return `<div class="tbl-wrap"><table><thead>${head}</thead><tbody>${body}</tbody></table></div>\n`;
    },
    blockquote({ tokens }) {
      return `<aside class="note">${this.parser.parse(tokens)}</aside>\n`;
    },
    code({ text, lang }) {
      return `<pre class="code"${lang ? ` data-lang="${esc(lang)}"` : ""}><code>${esc(text)}</code></pre>\n`;
    },
  },
});

// ------------------------------------------------------------------ parameter reference
function schemaJSON() {
  const py = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
  const out = execFileSync(py, ["-c", "import json; from uavlab.ui.schema import build_schema; print(json.dumps(build_schema(), default=str))"],
    { cwd: ROOT, maxBuffer: 64 * 1024 * 1024 });
  return JSON.parse(out.toString());
}

function fmtDefault(v) {
  if (v === null || v === undefined) return "<span class=\"muted\">auto / none</span>";
  if (Array.isArray(v)) {
    if (!v.length) return "<span class=\"muted\">empty</span>";
    if (v.every((x) => typeof x !== "object")) {
      const s = v.join(", ");
      return `<code>${esc(s.length > 48 ? s.slice(0, 45) + " …" : s)}</code>`;
    }
    return `<span class="muted">${v.length} entries</span>`;
  }
  if (typeof v === "object") return `<span class="muted">table</span>`;
  if (typeof v === "boolean") return `<code>${v}</code>`;
  return `<code>${esc(v)}</code>`;
}

function paramsHTML(schema) {
  const groups = new Map(schema.groups.map((g) => [g.id, g]));
  const byGroup = new Map();
  for (const f of schema.fields) {
    if (!byGroup.has(f.group)) byGroup.set(f.group, []);
    byGroup.get(f.group).push(f);
  }
  let html = "", n = 0;
  for (const [gid, fields] of byGroup) {
    n += 1;
    const g = groups.get(gid) || { label: gid, description: "" };
    const id = `params-${gid}`;
    usedIds.add(id);
    html += `<h3 id="${id}"><a class="anchor" href="#${id}" aria-label="Link to this section">#</a>A.${n} ${esc(g.label)} <code class="h-code">${esc(gid)}</code></h3>\n`;
    if (g.description) html += `<p>${esc(g.description)}</p>\n`;
    html += `<div class="tbl-wrap"><table class="params"><thead><tr><th>Parameter</th><th>Default</th><th>Unit</th><th>Limits / choices</th><th>Tag</th><th>Meaning</th></tr></thead><tbody>\n`;
    let sec = null;
    for (const f of fields) {
      if (f.section !== sec) {
        sec = f.section;
        if (sec && sec !== "general") html += `<tr class="sec"><td colspan="6">${esc(sec.replaceAll(".", " / ").replaceAll("_", " "))}</td></tr>\n`;
      }
      let lim = "";
      if (f.choices?.length) lim = f.choices.map((c) => `<code>${esc(c)}</code>`).join(" ");
      else if (f.min !== undefined && f.min !== null || f.max !== undefined && f.max !== null)
        lim = `${f.min ?? "−∞"} … ${f.max ?? "∞"}`;
      html += `<tr><td><code class="path">${esc(f.path)}</code><div class="lab">${esc(f.label)}</div></td>`
        + `<td class="num">${fmtDefault(f.default)}</td><td>${esc(f.unit || "")}</td><td class="small">${lim}</td>`
        + `<td>${f.tag ? `<span class="tag">${esc(f.tag)}</span>` : ""}</td><td class="small">${esc(f.description || "")}</td></tr>\n`;
    }
    html += "</tbody></table></div>\n";
  }
  return { html, count: schema.fields.length };
}

// ------------------------------------------------------------------ assemble
const srcDir = path.join(DOC, "src");
const files = fs.readdirSync(srcDir).filter((f) => f.endsWith(".md")).sort();
const md = files.map((f) => fs.readFileSync(path.join(srcDir, f), "utf8")).join("\n\n");
let body = marked.parse(md);

const schema = schemaJSON();
const params = paramsHTML(schema);
body = body.replace(/<p>@@PARAMS@@<\/p>/, params.html);

let figNo = 0;
body = body.replace(/<p>@@FIG:([\w-]+)@@<\/p>/g, (_, name) => {
  const p = path.join(DOC, "figs", `${name}.html`);
  if (!fs.existsSync(p)) throw new Error(`missing figure ${name}; run make_figures.py`);
  figNo += 1;
  return fs.readFileSync(p, "utf8").replace("<figcaption>", `<figcaption><b>Figure ${figNo}.</b> `);
});
const left = body.match(/@@(FIG|PARAMS)[^@]*@@/);
if (left) throw new Error(`unresolved placeholder ${left[0]}`);

// table of contents (parts + chapters)
let tocHTML = "<ol class=\"toc-list\">";
let open = false;
for (const t of toc) {
  if (t.depth === 1) {
    if (open) tocHTML += "</ol></li>";
    tocHTML += `<li class="toc-part"><a href="#${t.id}">${t.html}</a><ol>`;
    open = true;
  } else {
    tocHTML += `<li><a href="#${t.id}">${t.html}</a></li>`;
  }
}
if (open) tocHTML += "</ol></li>";
tocHTML += "</ol>";

const version = (() => {
  try { return fs.readFileSync(path.join(ROOT, "uavlab", "__init__.py"), "utf8").match(/__version__\s*=\s*"([^"]+)"/)[1]; }
  catch { return ""; }
})();
const built = new Date().toISOString().slice(0, 10);

const css = fs.readFileSync(path.join(HERE, "handbook.css"), "utf8");
const page = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UAV Energy Handbook</title>
<meta name="description" content="Engineering handbook of the uavlab UAV energy simulation lab: software architecture and data flow, aerospace engineering basis of every model, and user-interface workflows.">
<script>
// theme: follow the lab's interface when embedded, else the viewer's choice or system setting
(function () {
  var t = null;
  try { if (window.parent !== window) t = window.parent.document.documentElement.getAttribute("data-theme"); } catch (e) {}
  if (!t) { try { t = localStorage.getItem("uavlab.theme"); } catch (e) {} }
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
})();
</script>
<style>
${css}
</style>
</head>
<body>
<a class="skip" href="#content">Skip to content</a>
<header class="top">
  <div class="brand"><span class="logo" aria-hidden="true">
    <svg viewBox="0 0 24 24" width="22" height="22"><path d="M2 13 L22 9 L13 13 L22 17 Z M9 11 L6 5 M9 14 L6 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>
  </span><span><b>UAV Energy Lab</b> <span class="muted">Handbook</span></span></div>
  <div class="meta muted">uavlab ${esc(version)} · JSBSim 1.3.1 · built ${built}</div>
  <button class="theme" id="theme-btn" type="button" aria-label="Switch between light and dark theme">Theme</button>
</header>
<div class="layout">
  <nav class="toc" aria-label="Contents"><div class="toc-h">Contents</div>${tocHTML}</nav>
  <main id="content">
    <div class="hero">
      <h1>${esc(docTitle)}</h1>
      <p class="lede">Software architecture and data flow, the aerospace-engineering basis of every model, and step-by-step workflows for the interface of the Rascal 110 electric UAV energy simulation lab.</p>
    </div>
    <details class="toc-mobile"><summary>Contents</summary>${tocHTML}</details>
${body}
    <footer class="foot muted">Built from <code>docs/handbook/src/*.md</code> with <code>tools/handbook</code> (${figNo} figures, ${params.count} parameters). Edit the Markdown sources, then run <code>npm run build</code> in <code>tools/handbook</code>.</footer>
  </main>
</div>
<script>
(function () {
  var root = document.documentElement, btn = document.getElementById("theme-btn");
  function current() {
    var t = root.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  btn.addEventListener("click", function () {
    var t = current() === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", t);
    try { localStorage.setItem("uavlab.theme", t); } catch (e) {}
  });
  // highlight the section in view
  var links = {}, items = document.querySelectorAll(".toc a");
  items.forEach(function (a) { (links[a.getAttribute("href").slice(1)] = links[a.getAttribute("href").slice(1)] || []).push(a); });
  if ("IntersectionObserver" in window) {
    var obs = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        items.forEach(function (a) { a.classList.remove("on"); });
        (links[e.target.id] || []).forEach(function (a) { a.classList.add("on"); });
      });
    }, { rootMargin: "0px 0px -75% 0px" });
    document.querySelectorAll("main h1[id], main h2[id]").forEach(function (h) { obs.observe(h); });
  }
})();
</script>
</body>
</html>
`;
fs.writeFileSync(path.join(DOC, "handbook.html"), page);
console.log(`handbook.html: ${(page.length / 1024).toFixed(0)} kB, ${figNo} figures, ${toc.length} TOC entries, ${params.count} parameters`);
