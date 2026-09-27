// Handbook: the engineering and software manual, served by the lab.
import { h } from "../core.js";

export async function render(main, params) {
  const anchor = params[0] ? `#${params[0]}` : "";
  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Handbook"),
    h("div", { class: "sub" }, "Software architecture and data flow, aerospace engineering basis of every model, and step-by-step workflows for this interface.")),
    h("div", { class: "actions" }, h("a", { class: "btn", href: "/handbook", target: "_blank", rel: "noopener" }, "Open in a new tab"))),
    h("iframe", { class: "doc", src: `/handbook${anchor}`, title: "UAV Energy Lab handbook" }));
}
