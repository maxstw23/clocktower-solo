"""The Storyteller as a balance controller.

Its only freedom is choosing among legal options (what a drunk or poisoned player sees, how the
Spy and Recluse register). It picks the option that keeps the town's uncertainty about the Demon
on a planned trajectory: wide early, narrowing to one candidate around the final day.
"""


class Storyteller:
    def __init__(self, solver, rng, sample=6):
        self.solver = solver
        self.rng = rng
        self.sample = sample  # options scored per decision

    def target(self, game):
        """Desired effective number of Demon candidates; ~1 + days the game should still last."""
        return 1 + (len(game.alive) - 2) / 2

    def helps(self, game):
        """Which side the Storyteller's discretion should favour now: the one that's behind."""
        b = game.public_belief(game.forecast())
        gap = b.candidates() - self.target(game)  # more candidates than planned: the town is lost
        return "good" if gap > 0.5 else "evil" if gap < -0.5 else self.rng.choice(("good", "evil"))

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
        base, goal = game.forecast(), self.target(game)
        return min(picks, key=lambda r: abs(game.public_belief(game.forecast(r), base).candidates() - goal))
