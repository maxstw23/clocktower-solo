"""A human player at the table, making the same structured moves as the AI players.

Every prompt has a default (Enter, or end of input), so a game can also be driven by a script.
"""
import random

from .agents import PROFILES, Agent
from .roles import pretty


class HumanAgent(Agent):
    def __init__(self, seat, role, game, inp=input, out=print):
        # The profile is only used for optional hints.
        super().__init__(seat, PROFILES["veteran"], game.n, random.Random(0))
        self.role = role  # what they believe they are
        self.game = game
        self.inp = inp
        self.out = out
        self.slayer_used = False
        self.team = frozenset()
        self.survived = set()

    # --- prompting ---------------------------------------------------------------------------

    def ask(self, prompt, parse, default=None):
        while True:
            try:
                raw = self.inp(f"> {prompt} ").strip()
            except EOFError:
                return default
            if not raw:
                return default
            try:
                return parse(raw)
            except ValueError as e:
                self.out(f"  {e}")

    def seat_of(self, raw, allowed):
        g = self.game
        if raw.isdigit():
            s = int(raw)
        else:
            matches = [s for s in range(g.n) if g.name(s).lower().startswith(raw.lower())]
            if len(matches) != 1:
                raise ValueError(f"No single player matches '{raw}'.")
            s = matches[0]
        if s not in allowed:
            raise ValueError(f"{g.name(s)} can't be chosen here.")
        return s

    def pick(self, prompt, allowed, default=None):
        names = ", ".join(self.game.name(s) for s in allowed)
        return self.ask(f"{prompt} ({names})", lambda r: self.seat_of(r, allowed), default)

    def menu(self, prompt, labels):
        """Choose one of several labelled options; returns its index (default 0)."""
        for i, label in enumerate(labels, 1):
            self.out(f"  {i}. {label}")

        def parse(raw):
            if not raw.isdigit() or not 1 <= int(raw) <= len(labels):
                raise ValueError(f"Enter a number from 1 to {len(labels)}.")
            return int(raw) - 1
        return self.ask(f"{prompt} [1]", parse, 0)

    def _others(self, alive_only=True):
        g = self.game
        return [s for s in (g.alive if alive_only else range(g.n)) if s != self.seat]

    # --- night -------------------------------------------------------------------------------

    def ft_pick(self, game):
        allowed = self._others(alive_only=False)

        def parse(raw):
            parts = raw.replace(",", " ").split()
            if len(parts) != 2:
                raise ValueError("Name exactly two players.")
            a, b = (self.seat_of(p, allowed) for p in parts)
            if a == b:
                raise ValueError("Choose two different players.")
            return min(a, b), max(a, b)
        return self.ask("Fortune Teller: choose two players, e.g. 'Ada Ben'", parse, tuple(allowed[:2]))

    def monk_pick(self, game):
        return self.pick("Monk: who do you protect tonight?", self._others(), self._others()[0])

    def rk_pick(self, game):
        return self.pick("Ravenkeeper: you died tonight. Whose character do you learn?", self._others(), self._others()[0])

    def butler_pick(self, game):
        return self.pick("Butler: choose your master", self._others(), self._others()[0])

    def poison_pick(self, game):
        others = self._others()
        return self.pick("Poisoner: who do you poison tonight?", others, others[0])

    def kill_pick(self, game):
        others = self._others()
        targets = [s for s in others if s not in self.team] or others
        return self.pick("Imp: who do you kill tonight?", others, targets[0])

    # --- day ---------------------------------------------------------------------------------

    def slayer_pick(self, game):
        return self.pick("Slayer: shoot someone now? (Enter to keep your shot)", self._others())

    def nominate(self, game, nominated):
        if self.seat in game.dead:
            return None
        allowed = [s for s in self._others() if s not in nominated]
        if not allowed:
            return None
        return self.pick("Nominate someone? (Enter to pass)", allowed)

    def vote(self, game, nominee, yes, needed, block, ghost):
        status = f"{yes} vote(s) so far, {needed} needed"
        if block is not None:
            status += f"; {game.name(block)} is on the block"
        kind = "ghost vote (you get one)" if ghost else "vote"
        prompt = f"Use your {kind} to execute {game.name(nominee)}? ({status}) [y/N]"

        def parse(raw):
            if raw.lower() not in ("y", "yes", "n", "no"):
                raise ValueError("Answer y or n.")
            return raw.lower().startswith("y")
        return self.ask(prompt, parse, False)

    # --- evil bluffing -----------------------------------------------------------------------

    def choose_claim(self, options):
        self.out("Which character will you claim to be on day 1?")
        return options[self.menu("Claim", [pretty(r) for r in options])]

    def choose_report(self, game, options):
        self.out(f"What will you say your {pretty(options[0].kind)} ability told you?")
        return options[self.menu("Report", [game.describe(r).split(": ", 1)[1] for r in options])]
