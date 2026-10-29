"""Build the standalone game: a folder of static files that runs entirely in the browser.

    python build_web.py                          # writes dist/, loads Pyodide from its CDN
    python build_web.py --pyodide path/to/pyodide/package   # also copy Pyodide into dist/pyodide/

Serve the folder from any static host (or `python -m http.server -d dist`) and open it on a phone.
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
PYODIDE_FILES = ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="dist")
    p.add_argument("--pyodide", help="a Pyodide distribution folder to bundle (the npm package works)")
    p.add_argument("--fragment", action="store_true",
                   help="write index.html without the html/head/body wrapper (for hosts that add their own)")
    args = p.parse_args()
    out = ROOT / args.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    sources = {str(f.relative_to(ROOT)): f.read_text(encoding="utf-8") for f in sorted((ROOT / "botc").glob("*.py"))}
    (out / "botc-src.json").write_text(json.dumps(sources, ensure_ascii=False), encoding="utf-8")

    pyodide = "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/"
    if args.pyodide:
        (out / "pyodide").mkdir()
        for name in PYODIDE_FILES:
            shutil.copy(Path(args.pyodide) / name, out / "pyodide" / name)
        pyodide = "pyodide/"
    page = (ROOT / "botc" / "static" / "index.html").read_text(encoding="utf-8")
    flag = f'<script>window.CT_STANDALONE = {{ pyodide: {json.dumps(pyodide)} }};</script>\n'
    page = page.replace("<script>", flag + "<script>", 1)
    if args.fragment:
        for tag in ("<!doctype html>", '<html lang="en">', "<head>", "</head>", "<body>", "</body>", "</html>",
                    '<meta charset="utf-8">', '<meta name="viewport" content="width=device-width, initial-scale=1">'):
            page = page.replace(tag, "")
        page = page.strip() + "\n"
    (out / "index.html").write_text(page, encoding="utf-8")
    shutil.copy(ROOT / "web" / "worker.js", out / "worker.js")
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"Built {out} ({size / 1e6:.1f} MB). Pyodide from: {pyodide}")


if __name__ == "__main__":
    main()
