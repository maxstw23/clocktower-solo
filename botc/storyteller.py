"""The Storyteller as a balance controller.

Its only freedom is choosing among legal options (what a drunk or poisoned player sees, how the
Spy and Recluse register, the Mayor's bounce, the Demon's heir). It knows the grimoire, so it
steers by how much the town suspects the real Demon: low early, near certain around the final day.
It helps whichever side is behind that plan.
"""
from math import log


class Storyteller:
    def __init__(self, solver, rng, sample=6):
        self.solver = solver
        self.rng = rng
        self.sample = sample  # options scored per decision

    def target(self, game):
        """Desired effective number of Demon candidates; ~1 + days the game should still last."""
        return 1 + (len(game.alive) - 2) / 2

    def goal(self, game):
        """How much the town should suspect the real Demon by now: a fair guess among the
        living on the first day, rising to near certain at the final three."""
        return 1 / (len(game.alive) - 1)

    def on_track(self, game, b):
        """How the town's belief in the real Demon compares with the plan (1 = on plan, below 1 =
        the town is further from the truth than planned). Uncertainty alone isn't enough: a town
        that is sure of the wrong player is losing, however narrow its read."""
        goal = self.goal(game)
        found = b.demon[game.demon] / b.total if b.total else 0
        return max(found, 0.01) / goal

    def helps(self, game):
        """Which side the Storyteller's discretion should favour now: the one that's behind."""
        r = self.on_track(game, game.public_belief(game.forecast()))
        return "good" if r < 0.67 else "evil" if r > 1.5 else self.rng.choice(("good", "evil"))

    def pick_heir(self, game, heirs):
        """Several Minions could take over the Demon: the least suspected if evil is behind."""
        b = game.public_belief()
        ranked = sorted(heirs, key=lambda s: (b.suspicion(s), s))
        return ranked[0] if self.helps(game) == "evil" else ranked[-1]

    def mayor_bounce(self, game, mayor, protect):
        """The Demon attacks the Mayor: if good is behind, someone else may die instead."""
        if self.helps(game) != "good":
            return None
        options = [s for s in game.alive if s not in (mayor, protect, game.demon)
                   and game.roles[s] not in ("soldier", "mayor")]
        return self.rng.choice(options) if options else None

    def choose(self, game, options):
        options = list(dict.fromkeys(options))
        if len(options) == 1:
            return options[0]
        picks = self.rng.sample(options, min(self.sample, len(options)))
        base = game.forecast()
        return min(picks, key=lambda r: abs(log(self.on_track(game, game.public_belief(game.forecast(r), base)))))
