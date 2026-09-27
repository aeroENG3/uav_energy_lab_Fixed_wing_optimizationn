// Render tools/poc_guide/build/poc_guide.filled.md to HTML (KaTeX MathML) and print it to PDF with
// Chromium (Playwright). Usage: node build_pdf.mjs [pages.json]   (pages.json = TOC page numbers, pass 2)
// Env: HANDBOOK_NODE_MODULES (marked, katex), PLAYWRIGHT_MODULE (path to the playwright package),
//      CHROMIUM (executable path, optional).
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const BUILD = path.join(HERE, "build");
const require = createRequire(process.env.HANDBOOK_NODE_MODULES
  ? path.join(process.env.HANDBOOK_NODE_MODULES, "_resolve.js") : import.meta.url);
const { marked } = require("marked");
const katex = require("katex");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const slug = (s) => s.toLowerCase().replace(/<[^>]+>/g, "").replace(/&[a-z]+;/g, "").replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "");

// Unicode mathematical letters for bold/script (see tools/handbook/build.mjs)
const SCRIPT_EXC = { B: 0x212C, E: 0x2130, F: 0x2131, H: 0x210B, I: 0x2110, L: 0x2112, M: 0x2133, R: 0x211B };
function mapChar(ch, variant) {
  const c = ch.codePointAt(0);
  const up = c >= 65 && c <= 90, lo = c >= 97 && c <= 122, dg = c >= 48 && c <= 57;
  const gu = c >= 0x391 && c <= 0x3A9, gl = c >= 0x3B1 && c <= 0x3C9;
  const base = { "bold": [0x1D400, 0x1D41A, 0x1D7CE, 0x1D6A8, 0x1D6C2], "bold-italic": [0x1D468, 0x1D482, 0x1D7CE, 0x1D71C, 0x1D736],
    "sans-serif": [0x1D5A0, 0x1D5BA, 0x1D7E2, null, null], "script": [0x1D49C, 0x1D4B6, null, null, null] }[variant];
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
const tex = (src, display) => fixVariants(katex.renderToString(src, { displayMode: display, output: "mathml", throwOnError: true, strict: "ignore" }));

const toc = [];
marked.use({
  gfm: true,
  extensions: [
    { name: "mathBlock", level: "block", start(src) { const m = src.match(/^\$\$/m); return m ? m.index : undefined; },
      tokenizer(src) { const m = /^\$\$[ \t]*\n?([\s\S]+?)\n?\$\$[ \t]*(?:\n+|$)/.exec(src); if (m) return { type: "mathBlock", raw: m[0], text: m[1].trim() }; },
      renderer(t) { return `<div class="math-d">${tex(t.text, true)}</div>\n`; } },
    { name: "mathInline", level: "inline", start(src) { const i = src.indexOf("$"); return i < 0 ? undefined : i; },
      tokenizer(src) { const m = /^\$(?!\s)((?:\\\$|[^$\n])+?)(?<!\s)\$(?!\d)/.exec(src); if (m) return { type: "mathInline", raw: m[0], text: m[1] }; },
      renderer(t) { return tex(t.text, false); } },
  ],
  renderer: {
    heading({ tokens, depth, text }) {
      const inner = this.parser.parseInline(tokens);
      const id = slug(text);
      if (depth <= 2) toc.push({ depth, id, text, html: inner });
      return `<h${depth} id="${id}">${inner}</h${depth}>\n`;
    },
    table(token) {
      const head = "<tr>" + token.header.map((c) => `<th>${this.parser.parseInline(c.tokens)}</th>`).join("") + "</tr>";
      const body = token.rows.map((r) => "<tr>" + r.map((c) => `<td>${this.parser.parseInline(c.tokens)}</td>`).join("") + "</tr>").join("");
      return `<div class="tbl"><table><thead>${head}</thead><tbody>${body}</tbody></table></div>\n`;
    },
    blockquote({ tokens }) { return `<aside class="note">${this.parser.parse(tokens)}</aside>\n`; },
    code({ text, lang }) { return `<pre class="code"${lang ? ` data-lang="${esc(lang)}"` : ""}><code>${esc(text)}</code></pre>\n`; },
  },
});

const md = fs.readFileSync(path.join(BUILD, "poc_guide.filled.md"), "utf8");
let body = marked.parse(md);
const pages = process.argv[2] && fs.existsSync(process.argv[2]) ? JSON.parse(fs.readFileSync(process.argv[2], "utf8")) : {};
const tocHTML = '<section class="toc"><h2 class="toc-h">Contents</h2><ol>' + toc.map((t) =>
  `<li class="d${t.depth}"><a href="#${t.id}"><span class="t">${t.html}</span><span class="dots"></span><span class="p">${pages[t.id] ?? ""}</span></a></li>`).join("") + "</ol></section>";
body = body.replace(/(<\/section>)/, `$1\n${tocHTML}`);   // after the cover
fs.writeFileSync(path.join(BUILD, "toc.json"), JSON.stringify(toc.map(({ depth, id, text }) => ({ depth, id, text })), null, 1));

const figCss = fs.readFileSync(path.join(ROOT, "tools", "handbook", "handbook.css"), "utf8")
  .split("\n").filter((l) => l.startsWith(".fig ")).join("\n");
const css = `
@page { size: A4; margin: 17mm 16mm 18mm 16mm; }
:root { --fg:#16191d; --muted:#555c65; --border:#cfd4da; --border-soft:#e4e7eb; --code-bg:#f3f4f6; --accent:#0a5fc2; --accent-soft:#e6f0fb;
  --fig-box:#ffffff; --fig-box2:#eef1f4; --ok:#1b7a36; --ok-soft:#e7f4ea; --alarm:#b3261e; --alarm-soft:#fbe9e7; --panel:#fff;
  --sans: Carlito, "Liberation Sans", "DejaVu Sans", sans-serif; --mono: "DejaVu Sans Mono", "Liberation Mono", monospace; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; font: 10.5pt/1.4 var(--sans); color: var(--fg); background: #fff; }
h1 { font-size: 19pt; margin: 0 0 10pt; padding-top: 2pt; border-bottom: 2px solid var(--fg); padding-bottom: 4pt; break-before: page; break-after: avoid; }
h2 { font-size: 13.5pt; margin: 16pt 0 6pt; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
p { margin: 5pt 0; }
ul, ol { margin: 4pt 0; padding-left: 18pt; }
li { margin: 2pt 0; }
a { color: var(--accent); text-decoration: none; }
code { font-family: var(--mono); font-size: 8.6pt; background: var(--code-bg); padding: 0 2pt; border-radius: 2px; }
pre.code { font-family: var(--mono); font-size: 8.2pt; line-height: 1.4; background: var(--code-bg); border: 1px solid var(--border-soft);
  padding: 6pt 8pt; border-radius: 3px; white-space: pre-wrap; break-inside: avoid; }
pre.code code { background: none; padding: 0; font-size: inherit; }
.tbl { margin: 7pt 0 9pt; }
table { border-collapse: collapse; width: 100%; font-size: 9.2pt; }
th, td { text-align: left; vertical-align: top; padding: 3.5pt 6pt; border-bottom: 1px solid var(--border-soft); }
th { background: #eef1f4; font-weight: 700; border-bottom: 1px solid var(--border); }
td.r, th.r { text-align: right; font-variant-numeric: tabular-nums; }
table.small { font-size: 8.4pt; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
.note { margin: 8pt 0; padding: 6pt 10pt; background: #f4f6f8; border-left: 3px solid var(--accent); break-inside: avoid; }
.note p { margin: 3pt 0; }
.math-d { margin: 7pt 0; text-align: center; break-inside: avoid; }
math { font-family: "Latin Modern Math", "STIX Two Math", "Cambria Math", math; font-size: 1.08em; }
math[display="block"] { display: block math; }
.chip { display: inline-block; font: 700 7.5pt var(--sans); letter-spacing: .05em; padding: 1pt 5pt; border-radius: 3px; }
.chip.pass { color: var(--ok); background: var(--ok-soft); } .chip.fail { color: var(--alarm); background: var(--alarm-soft); }
.chip.na { color: var(--muted); background: #eee; }
/* figures */
.fig { margin: 8pt 0 10pt; break-inside: avoid; }
.fig-scroll { border: 1px solid var(--border-soft); border-radius: 3px; padding: 6pt; }
.fig svg { display: block; width: 100%; height: auto; max-height: 122mm; color: var(--fg); font-family: var(--sans); font-size: 12px; }
.fig.img img { display: block; width: 100%; height: auto; max-height: 158mm; object-fit: contain; }
.fig figcaption { font-size: 8.8pt; color: var(--muted); margin-top: 4pt; }
.fig figcaption b { color: var(--fg); }
${figCss}
/* cover */
.cover { height: 247mm; display: flex; flex-direction: column; justify-content: center; padding: 0 6mm; break-after: page; }
.cover .eyebrow { font: 700 9.5pt var(--sans); letter-spacing: .12em; text-transform: uppercase; color: var(--accent); }
.cover h1.title { font-size: 28pt; line-height: 1.15; border: none; margin: 10pt 0 8pt; break-before: auto; }
.cover .subtitle { font-size: 12.5pt; color: var(--muted); margin: 0 0 22pt; max-width: 150mm; }
.tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8pt; margin: 6pt 0 26pt; }
.tile { border: 1px solid var(--border); border-radius: 4px; padding: 9pt 10pt; }
.tile .k { font-size: 8.5pt; color: var(--muted); } .tile .v { font-size: 17pt; font-weight: 700; margin: 3pt 0; font-variant-numeric: tabular-nums; }
.tile .s { font-size: 8pt; color: var(--muted); }
.cover .meta { font-size: 9.5pt; color: var(--muted); line-height: 1.6; }
/* contents */
.toc { break-after: page; }
.toc-h { font-size: 19pt; border-bottom: 2px solid var(--fg); padding-bottom: 4pt; margin: 0 0 10pt; }
.toc ol { list-style: none; padding: 0; margin: 0; }
.toc li a { display: flex; align-items: baseline; color: var(--fg); }
.toc li.d1 { margin-top: 4.5pt; font-weight: 700; font-size: 10.5pt; }
.toc li.d2 { padding-left: 14pt; font-size: 9.6pt; margin: 0.6pt 0; line-height: 1.3; }
.toc .dots { flex: 1; border-bottom: 1px dotted #b5bac1; margin: 0 5pt; transform: translateY(-3pt); }
.toc .p { font-variant-numeric: tabular-nums; min-width: 14pt; text-align: right; }
`;
const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Proof of concept: wind-adaptive energy optimisation</title>
<style>${css}</style></head><body>${body}</body></html>`;
const htmlPath = path.join(BUILD, "poc_guide.html");
fs.writeFileSync(htmlPath, html);

const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
const page = await browser.newPage();
await page.goto("file://" + htmlPath, { waitUntil: "load" });
await page.waitForTimeout(300);
const out = path.join(ROOT, "docs", "poc", "POC_GUIDE.pdf");
fs.mkdirSync(path.dirname(out), { recursive: true });
await page.pdf({
  path: out, format: "A4", printBackground: true, preferCSSPageSize: true, displayHeaderFooter: true,
  headerTemplate: "<span></span>",
  footerTemplate: `<div style="width:100%; font: 7.5px Carlito, sans-serif; color:#6b7280; padding: 0 16mm; display:flex; justify-content:space-between;">
    <span>UAV Energy Lab · Proof of concept: wind-adaptive energy optimisation</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
});
await browser.close();
console.log("pdf:", out);
