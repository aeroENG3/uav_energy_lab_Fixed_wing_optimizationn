"""Build docs/poc/POC_GUIDE.pdf from docs/poc/src/poc_guide.md and poc_results/.

    python tools/poc_guide/build.py

Needs Node.js with marked, katex and playwright (see tools/handbook/package.json; set
HANDBOOK_NODE_MODULES / PLAYWRIGHT_MODULE if they are not installed next to the scripts).
Two passes: the second fills the page numbers of the table of contents.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PDF = ROOT / "docs" / "poc" / "POC_GUIDE.pdf"


def node(*args):
    subprocess.run(["node", str(HERE / "build_pdf.mjs"), *args], check=True, cwd=HERE, env=os.environ.copy())


def paginate():
    import pdfplumber
    toc = json.loads((HERE / "build" / "toc.json").read_text(encoding="utf-8"))
    pages = {}
    with pdfplumber.open(PDF) as pdf:
        texts = [(p.extract_text() or "").splitlines() for p in pdf.pages]
    start = 2                                    # skip the cover and the contents page(s)
    for i, lines in enumerate(texts):
        if any(l.strip() == "Contents" for l in lines[:2]):
            start = i + 1
    cursor = start
    for t in toc:
        key = " ".join(t["text"].split())[:40]
        for i in range(cursor, len(texts)):
            if any(" ".join(l.split()).startswith(key) for l in texts[i]):
                pages[t["id"]] = i + 1
                cursor = i
                break
    return pages


def main():
    subprocess.run([sys.executable, str(HERE / "prepare.py")], check=True)
    node()
    pages = paginate()
    (HERE / "build" / "pages.json").write_text(json.dumps(pages), encoding="utf-8")
    node(str(HERE / "build" / "pages.json"))
    missing = [t["text"] for t in json.loads((HERE / "build" / "toc.json").read_text(encoding="utf-8")) if t["id"] not in pages]
    print("pages found:", len(pages), "missing:", missing)


if __name__ == "__main__":
    main()
