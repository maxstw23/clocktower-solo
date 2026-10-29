"""Play in the browser. Standard library only.

The game runs in a background thread; whenever it needs the human it waits on WebIO, which the
page answers through POST /api/answer. The page polls GET /api/state for the log, the table and
the open question.
"""
import json
import random
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .engine import Game
from .human import GameAborted, WebIO
from .roles import KIND, pretty

PAGE = Path(__file__).with_name("static") / "index.html"


class Session:
    def __init__(self):
        self.game = self.io = None
        self.error = None
        self.lock = threading.Lock()

    def start(self, name, players, seed, seat, hints):
        with self.lock:
            if self.io:
                self.io.aborted = True
            seed = seed if seed is not None else random.randrange(10**6)
            if seat is None:
                seat = random.Random(f"seat-{seed}").randrange(players)
            io = WebIO()
            game = Game(players, seed, out=None, human=seat, io=io, hints=hints, name=name or None)
            self.game, self.io, self.error = game, io, None

            def run():
                try:
                    game.run()
                except GameAborted:
                    pass
                except Exception:
                    self.error = traceback.format_exc()

            threading.Thread(target=run, daemon=True).start()

    def state(self, since):
        g = self.game
        if g is None:
            return {"game": None}
        h, over = g.human, g.phase == "over"
        claims = g.pub.claims or (None,) * g.n
        you_evil = h in g.team
        seats = []
        for s in range(g.n):
            role = g.start_roles[s] if over else g.perceived[s] if s == h else g.roles[s] if you_evil and s in g.team else None
            seats.append({
                "seat": s, "name": g.name(s), "you": s == h, "alive": s not in g.dead,
                "ghost": s in g.dead and s not in g.ghosts_used,
                "claim": pretty(claims[s]) if claims[s] else None,
                "role": pretty(role) if role else None,
                "evil": (over or you_evil) and s in g.team,
            })
        return {"game": {
            "seed": g.seed, "players": g.n, "day": g.day, "night": g.night, "phase": g.phase,
            "you": h, "role": pretty(g.perceived[h]), "kind": KIND[g.perceived[h]], "evil": you_evil,
            "seats": seats, "log": [{"text": t, "private": p, "chat": c} for t, p, c in g.log[since:]], "log_len": len(g.log),
            "prompt": self.io.prompt, "notebook": g.notebook(), "winner": g.winner, "over": over,
            "error": self.error,
        }}


def make_handler(session):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path.startswith("/api/state"):
                since = 0
                if "since=" in self.path:
                    try:
                        since = int(self.path.split("since=")[1].split("&")[0])
                    except ValueError:
                        pass
                self._send(200, session.state(since))
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
                    session.start(str(body.get("name", ""))[:20].strip(), players, seed, seat, bool(body.get("hints")))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True})
            if self.path == "/api/answer":
                if session.io is None:
                    return self._send(400, {"error": "no game"})
                err = session.io.answer(body.get("id"), body.get("value"))
                return self._send(400 if err else 200, {"error": err} if err else {"ok": True})
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
