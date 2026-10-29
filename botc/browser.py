"""Run the game inside the browser (Pyodide, in a Web Worker): the standalone, phone-friendly build.

The page sends the same requests it would send to the local server (web.py); `handle` answers
them. The game itself runs as an asyncio task on Pyodide's event loop, so between lines of the
game the worker is free to answer the page.
"""
import asyncio
import json
import random
import traceback

from .engine import Game
from .human import GameAborted, WebIO
from .i18n import LANGS
from .ui import SPEEDS, pacer, pick_seat, roles_payload, snapshot


class BrowserSession:
    def __init__(self):
        self.game = self.io = self.task = None
        self.error = None
        self.speed = "normal"

    def start(self, name, players, seed, seat, hints, lang, side=None):
        if self.io:
            self.io.abort()
        seed = seed if seed is not None else random.randrange(10**6)
        if seat is None:
            seat = pick_seat(players, seed, side)
        self.io = WebIO()
        self.game = Game(players, seed, out=None, human=seat, io=self.io, hints=hints, name=name or None,
                         lang=lang, pace=pacer(lambda: self.speed, lang),
                        step=lambda: self.speed == "step")
        self.error = None
        self.task = asyncio.ensure_future(self._run(self.game))

    async def _run(self, game):
        try:
            await game.run()
        except GameAborted:
            pass
        except Exception:
            self.error = traceback.format_exc()


session = BrowserSession()


def handle(path, query_json, body_json):
    """One request from the page: returns [status, json text]."""
    q, body = json.loads(query_json or "{}"), json.loads(body_json or "{}")
    lang = q.get("lang") if q.get("lang") in LANGS else "en"
    if path == "/api/state":
        return [200, json.dumps(snapshot(session.game, session.io, int(q.get("since", 0)), lang,
                                         session.speed, session.error), ensure_ascii=False)]
    if path == "/api/roles":
        return [200, json.dumps(roles_payload(lang), ensure_ascii=False)]
    if path == "/api/new":
        try:
            players = int(body.get("players", 8))
            seed = int(body["seed"]) if body.get("seed") not in (None, "") else None
            seat = int(body["seat"]) if body.get("seat") not in (None, "") else None
            if seat is not None and not 0 <= seat < players:
                raise ValueError("seat out of range")
            session.start(str(body.get("name", ""))[:20].strip(), players, seed, seat, bool(body.get("hints")),
                          body.get("lang") if body.get("lang") in LANGS else "en", body.get("side"))
        except ValueError as e:
            return [400, json.dumps({"error": str(e)})]
        return [200, json.dumps({"ok": True})]
    if path == "/api/answer":
        if session.io is None:
            return [400, json.dumps({"error": "no game"})]
        err = session.io.answer(body.get("id"), body.get("value"))
        return [400 if err else 200, json.dumps({"error": err} if err else {"ok": True})]
    if path == "/api/speed":
        if body.get("speed") in SPEEDS:
            session.speed = body["speed"]
        return [200, json.dumps({"speed": session.speed})]
    return [404, json.dumps({"error": "not found"})]
