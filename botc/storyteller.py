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

    def choose(self, game, options):
        options = list(dict.fromkeys(options))
        if len(options) == 1:
            return options[0]
        picks = self.rng.sample(options, min(self.sample, len(options)))
        base, goal = game.forecast(), self.target(game)
        return min(picks, key=lambda r: abs(game.public_belief(game.forecast(r), base).candidates() - goal))
