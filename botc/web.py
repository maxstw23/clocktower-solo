"""Play in the browser. Standard library only.

The game runs in a background thread; whenever it needs the human it waits on WebIO, which the
page answers through POST /api/answer. The page polls GET /api/state for the log, the table and
the open question, rendered in the language it asks for (see ui.py). The game paces itself (a
short wait before each line) so players speak one at a time.
"""
import asyncio
import json
import random
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .engine import Game
from .human import GameAborted, WebIO
from .i18n import LANGS
from .ui import SPEEDS, pacer, roles_payload, snapshot

PAGE = Path(__file__).with_name("static") / "index.html"


class Session:
    def __init__(self):
        self.game = self.io = None
        self.error = None
        self.speed = "normal"
        self.lock = threading.Lock()

    def start(self, name, players, seed, seat, hints, lang):
        with self.lock:
            if self.io:
                self.io.abort()
            seed = seed if seed is not None else random.randrange(10**6)
            if seat is None:
                seat = random.Random(f"seat-{seed}").randrange(players)
            io = WebIO()
            game = Game(players, seed, out=None, human=seat, io=io, hints=hints, name=name or None,
                        lang=lang, pace=pacer(lambda: self.speed, lang),
                        step=lambda: self.speed == "step")
            self.game, self.io, self.error = game, io, None

            def run():
                try:
                    asyncio.run(game.run())
                except GameAborted:
                    pass
                except Exception:
                    self.error = traceback.format_exc()

            threading.Thread(target=run, daemon=True).start()

    def state(self, since, lang):
        return snapshot(self.game, self.io, since, lang, self.speed, self.error)


def make_handler(session):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype if ctype != "application/json" else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            lang = q.get("lang", ["en"])[0]
            lang = lang if lang in LANGS else "en"
            if url.path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/state":
                try:
                    since = int(q.get("since", ["0"])[0])
                except ValueError:
                    since = 0
                self._send(200, session.state(since, lang))
            elif url.path == "/api/roles":
                self._send(200, roles_payload(lang))
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            if self.path == "/api/new":
                try:
                    players = int(body.get("players", 8))
                    seed = body.get("seed")
                    seed = int(seed) if seed not in (None, "") else None
                    seat = body.get("seat")
                    seat = int(seat) if seat not in (None, "") else None
                    if seat is not None and not 0 <= seat < players:
                        raise ValueError("seat out of range")
                    lang = body.get("lang") if body.get("lang") in LANGS else "en"
                    session.start(str(body.get("name", ""))[:20].strip(), players, seed, seat,
                                  bool(body.get("hints")), lang)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True})
            if self.path == "/api/answer":
                if session.io is None:
                    return self._send(400, {"error": "no game"})
                err = session.io.answer(body.get("id"), body.get("value"))
                return self._send(400 if err else 200, {"error": err} if err else {"ok": True})
            if self.path == "/api/speed":
                if body.get("speed") in SPEEDS:
                    session.speed = body["speed"]
                return self._send(200, {"speed": session.speed})
            self._send(404, {"error": "not found"})

    return Handler


def serve(port=8765, open_browser=True):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(Session()))
    url = f"http://127.0.0.1:{port}/"
    print(f"Blood on the Clocktower is running at {url}  (Ctrl+C to stop)")
    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
