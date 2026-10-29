"""A human player at the table, making the same structured moves as the AI players.

The game asks through an IO object with four kinds of question: choose one of several options,
pick a player (or pass), pick several players, or yes/no. TerminalIO asks in a terminal; WebIO
hands each question to the browser (see web.py). Every question has a default.
"""
import asyncio
import inspect
import random

from .agents import PROFILES, Agent
from .i18n import L, M, S


class GameAborted(Exception):
    """The human left (e.g. started a new game in the browser)."""


class TerminalIO:
    """Text prompts. Enter, or end of input, takes the default. 'notes' or '?' shows the notebook."""

    def __init__(self, inp=input, out=print):
        self.inp, self.out, self.game = inp, out, None

    def _ask(self, prompt, parse, default):
        while True:
            try:
                raw = self.inp(f"> {prompt} ").strip()
            except EOFError:
                return default
            if raw.lower() in ("?", "notes") and self.game:
                for line in self.game.notebook():
                    self.out(self.game.text(line))
                continue
            if not raw:
                return default
            try:
                return parse(raw)
            except ValueError as e:
                self.out(f"  {e}")

    def _seat_of(self, raw, allowed):
        g = self.game
        matches = [s for s in range(g.n) if g.name(s).lower().startswith(raw.lower())]
        if raw.isdigit():
            matches = [int(raw)]
        if len(matches) != 1 or matches[0] not in allowed:
            raise ValueError(f"Choose one of: {', '.join(g.name(s) for s in allowed)}.")
        return matches[0]

    def _t(self, m):
        return self.game.text(m)

    def choose(self, prompt, labels, default=0):
        prompt = self._t(prompt)
        for i, label in enumerate(labels, 1):
            self.out(f"  {i}. {self._t(label)}")

        def parse(raw):
            if not raw.isdigit() or not 1 <= int(raw) <= len(labels):
                raise ValueError(f"Enter a number from 1 to {len(labels)}.")
            return int(raw) - 1
        return self._ask(f"{prompt} [{default + 1}]", parse, default)

    def seat(self, prompt, seats, default=None):
        prompt = self._t(prompt)
        names = ", ".join(self.game.name(s) for s in seats)
        hint = "Enter to pass" if default is None else f"Enter for {self.game.name(default)}"
        return self._ask(f"{prompt} ({names}; {hint})", lambda r: self._seat_of(r, seats), default)

    def seats(self, prompt, seats, k, default):
        prompt = self._t(prompt)

        def parse(raw):
            chosen = [self._seat_of(p, seats) for p in raw.replace(",", " ").split()]
            if len(chosen) != k or len(set(chosen)) != k:
                raise ValueError(f"Name {k} different players.")
            return chosen
        names = ", ".join(self.game.name(s) for s in seats)
        return self._ask(f"{prompt} ({names})", parse, list(default))

    def ack(self, title, body=None):
        self.out(f"== {self._t(title)} ==" + (f" {self._t(body)}" if body else ""))

    def next(self):
        return None

    def yes_no(self, prompt, default=False):
        prompt = self._t(prompt)

        def parse(raw):
            if raw.lower() not in ("y", "yes", "n", "no"):
                raise ValueError("Answer y or n.")
            return raw.lower().startswith("y")
        return self._ask(f"{prompt} [{'Y/n' if default else 'y/N'}]", parse, default)


class WebIO:
    """Questions wait in `prompt` until the page answers through `answer`. Works with the local
    server (the game runs in its own thread) and in the browser (one thread, Pyodide)."""

    def __init__(self):
        self.prompt = None
        self.game = None
        self._future = None
        self._loop = None
        self._next = 0
        self.aborted = False

    async def _ask(self, spec):
        self._loop = asyncio.get_running_loop()
        self._future = self._loop.create_future()
        self._next += 1
        spec["id"] = self._next
        self.prompt = spec
        try:
            return await self._future
        finally:
            self.prompt = None

    def abort(self):
        self.aborted = True
        if self._future and not self._future.done():
            self._loop.call_soon_threadsafe(self._future.set_exception, GameAborted())

    def answer(self, pid, value):
        """Validate and deliver an answer; returns an error message or None."""
        p = self.prompt
        if p is None or p["id"] != pid or self._future is None:
            return "That question is no longer open."
        kind = p["type"]
        if kind == "choose" and not (isinstance(value, int) and 0 <= value < len(p["labels"])):
            return "Invalid choice."
        if kind == "seat" and not (value in p["seats"] or (value is None and p["default"] is None)):
            return "Choose one of the highlighted players."
        if kind == "seats" and not (isinstance(value, list) and len(value) == p["k"]
                                    and len(set(value)) == p["k"] and all(v in p["seats"] for v in value)):
            return f"Choose {p['k']} different players."
        if kind == "yesno" and not isinstance(value, bool):
            return "Answer yes or no."
        if kind in ("ack", "next"):
            value = True
        fut = self._future
        self._loop.call_soon_threadsafe(lambda: fut.done() or fut.set_result(value))
        return None

    def choose(self, prompt, labels, default=0):
        return self._ask({"type": "choose", "text": prompt, "labels": list(labels), "default": default})

    def seat(self, prompt, seats, default=None):
        return self._ask({"type": "seat", "text": prompt, "seats": list(seats), "default": default})

    def seats(self, prompt, seats, k, default):
        return self._ask({"type": "seats", "text": prompt, "seats": list(seats), "k": k, "default": list(default)})

    def yes_no(self, prompt, default=False):
        return self._ask({"type": "yesno", "text": prompt, "default": default})

    def ack(self, title, body=None):
        return self._ask({"type": "ack", "title": title, "text": body})

    def next(self):
        return self._ask({"type": "next", "text": None})


class ChoiceIO:
    """Lets the engine `await` every question, whether the IO answers at once or later."""

    def __init__(self, io):
        self.raw = io

    async def _call(self, name, *args):
        answer = getattr(self.raw, name)(*args)
        return await answer if inspect.isawaitable(answer) else answer

    def choose(self, prompt, labels, default=0):
        return self._call("choose", prompt, labels, default)

    def seat(self, prompt, seats, default=None):
        return self._call("seat", prompt, seats, default)

    def seats(self, prompt, seats, k, default):
        return self._call("seats", prompt, seats, k, default)

    def yes_no(self, prompt, default=False):
        return self._call("yes_no", prompt, default)

    async def ack(self, title, body=None):
        if hasattr(self.raw, "ack"):
            await self._call("ack", title, body)

    async def next(self):
        if hasattr(self.raw, "next"):
            await self._call("next")


class HumanAgent(Agent):
    def __init__(self, seat, role, game, io):
        # The profile is only used for optional hints.
        super().__init__(seat, PROFILES["veteran"], game.n, random.Random(0))
        self.role = role  # what they believe they are
        self.game = game
        self.io = ChoiceIO(io)
        io.game = game
        self.slayer_used = False
        self.team = frozenset()
        self.survived = set()

    def _others(self, alive_only=True):
        g = self.game
        return [s for s in (g.alive if alive_only else range(g.n)) if s != self.seat]

    # --- night -------------------------------------------------------------------------------

    async def ft_pick(self, game):
        a, b = await self.io.seats(M("q_ft"), self._others(False), 2, self._others(False)[:2])
        return min(a, b), max(a, b)

    async def monk_pick(self, game):
        return await self.io.seat(M("q_monk"), self._others(), self._others()[0])

    async def rk_pick(self, game):
        return await self.io.seat(M("q_rk"), self._others(), self._others()[0])

    async def butler_pick(self, game):
        return await self.io.seat(M("q_butler"), self._others(), self._others()[0])

    async def poison_pick(self, game):
        targets = [s for s in self._others() if s not in self.team] or self._others()
        return await self.io.seat(M("q_poison"), self._others(), targets[0])

    async def kill_pick(self, game):
        claims = game.pub.claims or (None,) * game.n
        targets = ([s for s in self._others() if s not in self.team and claims[s] != "soldier" and s not in game.survived]
                   or [s for s in self._others() if s not in self.team] or self._others())
        # The Imp may choose itself: a Minion then becomes the Imp.
        return await self.io.seat(M("q_kill"), self._others() + [self.seat], targets[0])

    # --- day ---------------------------------------------------------------------------------

    def statement(self, game):
        return None  # the human speaks in their own turn

    async def invite(self, game, free):
        n = await self.io.choose(M("q_aside"), [M("aside_no"), M("aside_one"), M("aside_two")], default=0)
        if n == 0:
            return []
        if n == 1 or len(free) < 2:
            s = await self.io.seat(M("q_invite"), free)
            return [] if s is None else [s]
        return list(await self.io.seats(M("q_invite"), free, 2, free[:2]))

    async def accept(self, game, inviter, invited):
        others = [S(x) for x in invited if x != self.seat]
        extra = M("together", list=L(others, conj=True)) if others else ""
        return await self.io.yes_no(M("q_accept", p=S(inviter), extra=extra))

    async def nominate(self, game, nominated):
        if self.seat in game.dead:
            return None
        allowed = [s for s in self._others() if s not in nominated]
        if not allowed:
            return None
        return await self.io.seat(M("q_nominate"), allowed)

    async def vote(self, game, nominee, yes, needed, block, ghost):
        kind = M("your_ghost_vote") if ghost else M("your_vote")
        return await self.io.yes_no(M("q_vote", t=S(nominee), kind=kind, yes=yes, needed=needed))
