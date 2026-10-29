// Runs the Python game engine with Pyodide, off the page's main thread.
// The page posts {id, path, query, body}; we answer {id, status, data}.
const PYODIDE = self.location.search.includes("pyodide=")
  ? decodeURIComponent(self.location.search.split("pyodide=")[1].split("&")[0])
  : "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/";
const BASE = new URL(PYODIDE, self.location).href;
importScripts(BASE + "pyodide.js");

const ready = (async () => {
  const py = await loadPyodide({ indexURL: BASE });
  const files = await (await fetch("botc-src.json")).json();
  py.FS.mkdirTree("/home/pyodide/botc/static");
  for (const [name, text] of Object.entries(files)) py.FS.writeFile("/home/pyodide/" + name, text);
  py.runPython("import sys; sys.path.insert(0, '/home/pyodide'); from botc.browser import handle");
  return py.globals.get("handle");
})();

self.onmessage = async (e) => {
  const { id, path, query, body } = e.data;
  try {
    const handle = await ready;
    const res = handle(path, JSON.stringify(query || {}), JSON.stringify(body || {}));
    const [status, text] = res.toJs();
    res.destroy();
    self.postMessage({ id, status, data: JSON.parse(text) });
  } catch (err) {
    self.postMessage({ id, status: 500, data: { error: String(err), engine: true } });
  }
};
