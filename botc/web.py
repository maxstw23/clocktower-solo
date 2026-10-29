"""Play in the browser. Standard library only.

The game runs in a background thread; whenever it needs the human it waits on WebIO, which the
page answers through POST /api/answer. The page polls GET /api/state for the log, the table and
the open question, rendered in the language it asks for. The game paces itself (a short wait
before each line) so players speak one at a time.
"""
import json
import random
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .engine import Game
from .human import GameAborted, WebIO
from .i18n import ABILITY, KIND_NAMES, LANGS, M, render, role_name, roles_reference
from .roles import KIND

PAGE = Path(__file__).with_name("static") / "index.html"
SPEEDS = {"slow": 1.7, "normal": 1.0, "fast": 0.4, "instant": 0.0}
WAIT = {"speech": 1.4, "event": 1.1, "private": 0.5}  # seconds before a line appears, at normal speed


class Session:
    def __init__(self):
        self.game = self.io = None
        self.error = None
        self.speed = "normal"
        self.lock = threading.Lock()

    def pace(self, kind):
        return WAIT[kind] * SPEEDS[self.speed]

    def start(self, name, players, seed, seat, hints, lang):
        with self.lock:
            if self.io:
                self.io.aborted = True
            seed = seed if seed is not None else random.randrange(10**6)
            if seat is None:
                seat = random.Random(f"seat-{seed}").randrange(players)
            io = WebIO()
            game = Game(players, seed, out=None, human=seat, io=io, hints=hints, name=name or None,
                        lang=lang, pace=self.pace)
            self.game, self.io, self.error = game, io, None

            def run():
                try:
                    game.run()
                except GameAborted:
                    pass
                except Exception:
                    self.error = traceback.format_exc()

            threading.Thread(target=run, daemon=True).start()

    def state(self, since, lang):
        g = self.game
        if g is None:
            return {"game": None}

        def t(m):
            return render(m, lang, g.names)

        h, over = g.human, g.phase == "over"
        claims = g.pub.claims or (None,) * g.n
        you_evil = h in g.team
        seats = []
        for s in range(g.n):
            role = g.start_roles[s] if over else g.perceived[s] if s == h else g.roles[s] if you_evil and s in g.team else None
            seats.append({
                "seat": s, "name": g.name(s), "you": s == h, "alive": s not in g.dead,
                "ghost": s in g.dead and s not in g.ghosts_used,
                "claim": role_name(claims[s], lang) if claims[s] else None, "claim_key": claims[s],
                "role": role_name(role, lang) if role else None, "role_key": role,
                "evil": (over or you_evil) and s in g.team,
                "history": [t(m) for m in g.history(s)],
            })
        log = []
        for e in g.log[since:]:
            m = e["m"]
            log.append({"text": t(m), "private": e["private"], "chat": e["chat"], "speaker": e["speaker"],
                        "key": m.key, "quote": t(m.args["text"]) if m.key == "speech" else None})
        prompt = None
        if self.io.prompt:
            p = dict(self.io.prompt)
            p["text"] = t(p["text"])
            if "labels" in p:
                p["labels"] = [t(x) for x in p["labels"]]
            prompt = p
        me = g.perceived[h]
        return {"game": {
            "seed": g.seed, "players": g.n, "day": g.day, "night": g.night, "phase": g.phase,
            "you": h, "role": role_name(me, lang), "role_key": me, "ability": ABILITY[lang][me],
            "kind": KIND[me], "kind_name": KIND_NAMES[lang][KIND[me]], "evil": you_evil,
            "seats": seats, "log": log, "log_len": len(g.log), "prompt": prompt,
            "notebook": [t(m) for m in g.notebook()], "winner": g.winner, "over": over,
            "speaking": g.speaking, "speed": self.speed, "error": self.error,
        }}


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
                self._send(200, {"roles": roles_reference(lang), "note": render(M("first_night_note"), lang)})
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
