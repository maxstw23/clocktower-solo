"""Players.

Good players reason through a bounded view of the solver, set by a Profile: which excuses they
think of, how many they tolerate, and fixed social dials for nominating and voting. Each player
also has a seeded personal ordering of the other seats that breaks ties, standing in for gut feel.

Evil players know their team and judge their moves by running the town's reasoning on the result.
"""
from dataclasses import dataclass

from itertools import combinations

from .roles import KIND, is_evil
from .worlds import Belief, tally


@dataclass(frozen=True)
class Profile:
    name: str
    considers_poison: bool = True
    considers_drunk: bool = True
    considers_misregistration: bool = True
    max_excuses: int = 2   # worlds needing more excuses than this are ignored, unless nothing else fits
    nominate_at: int = 35  # suspicion (0-100) needed to nominate
    vote_at: int = 30      # suspicion needed to vote yes
    bandwagon: int = 3     # vote threshold drops this much per yes vote already cast
    ghost_vote_at: int = 60
    urgency: int = 5       # thresholds drop this much per day
    slayer_at: int = 50
    saint_caution: int = 40  # extra suspicion needed to vote for a claimed Saint
    lookahead: int = 3       # evil only: how many candidate lies they test against their read of the town
    ft_split: bool = True    # Fortune Teller picks pairs that split the suspects instead of the top two
    tests_virgin: bool = False  # a townsfolk nominates the claimed Virgin on day 1 to test both
    vote_memory: int = 10    # suspicion added per push (nomination or vote) of an execution that now looks good


PROFILES = {
    "novice": Profile("novice", considers_poison=False, considers_drunk=False,
                      considers_misregistration=False, max_excuses=0,
                      nominate_at=30, vote_at=25, bandwagon=6, saint_caution=10, lookahead=1,
                      ft_split=False, vote_memory=0),
    "regular": Profile("regular", considers_misregistration=False, max_excuses=1),
    "veteran": Profile("veteran", max_excuses=3, nominate_at=40, vote_at=35, bandwagon=1, lookahead=6,
                       tests_virgin=True, vote_memory=20),
}
# How "the town" reads the record; used by the Storyteller.
REFERENCE = Profile("reference")


def believe(solver, pub, profile, seat=None, base=None):
    """Tally the worlds a player with this profile considers. Widens assumptions if none fit."""
    if not pub.claims:
        return Belief.empty(pub.n)
    p, m, dr = profile.considers_poison, profile.considers_misregistration, profile.considers_drunk
    steps = ((p, m, dr, profile.max_excuses), (p, m, dr, 99), (True, True, True, 99))
    for level, (p, m, dr, cap) in enumerate(steps):
        worlds = [w for w in solver.worlds(pub, p, m, base)
                  if w.excuses <= cap and (dr or w.drunk is None)
                  and (seat is None or not is_evil(w.roles[seat]))]
        if worlds:
            return tally(pub.n, worlds, relaxed=level > 0)
    return Belief.empty(pub.n)


# Info roles whose ability is spent after night one: the natural Virgin testers.
SPENT = ("washerwoman", "librarian", "investigator", "chef")

# How much the evil team wants a claimed role silenced, and the town wants it protected.
VALUE = {"fortune_teller": 5, "empath": 5, "undertaker": 4, "monk": 3, "slayer": 3,
         "investigator": 2, "washerwoman": 2, "librarian": 2, "chef": 2, "virgin": 2, "mayor": 2,
         "ravenkeeper": 1}


class Agent:
    """Good and evil players draw from the same profiles: the same blind spots, dials and skill."""

    def __init__(self, seat, profile, n, rng):
        self.seat = seat
        self.profile = profile
        order = list(range(n))
        rng.shuffle(order)
        self.bias = {s: i for i, s in enumerate(order)}

    def rank(self, seats, key):
        return sorted(seats, key=lambda s: (key(s), self.bias[s]))

    @staticmethod
    def value(game, s):
        return VALUE.get(game.pub.claims[s], 0) if game.pub.claims else 0

    def threshold(self, base, game):
        if len(game.alive) <= 4:
            return 0  # endgame: every day without an execution is a day handed to evil
        return base - self.profile.urgency * (game.day - 1)


class GoodAgent(Agent):
    def __init__(self, seat, role, profile, n, rng):
        super().__init__(seat, profile, n, rng)
        self.role = role  # what they believe they are
        self.slayer_used = False

    def ft_pick(self, game):
        b = game.belief_of(self)
        others = [s for s in range(game.n) if s != self.seat]
        if not self.profile.ft_split:
            a, c = self.rank(others, lambda s: -b.demon_pct(s))[:2]
            return min(a, c), max(a, c)
        # The most informative question: a pair whose YES chance is closest to even.
        return min(combinations(others, 2),
                   key=lambda p: (abs(b.demon_pct(p[0]) + b.demon_pct(p[1]) - 50), self.bias[p[0]] + self.bias[p[1]]))

    def monk_pick(self, game):
        b = game.belief_of(self)
        others = [s for s in game.alive if s != self.seat]
        return self.rank(others, lambda s: (b.evil_pct(s), -self.value(game, s)))[0]

    def rk_pick(self, game):
        b = game.belief_of(self)
        return self.rank([s for s in game.alive if s != self.seat], lambda s: -b.demon_pct(s))[0]

    def butler_pick(self, game):
        b = game.belief_of(self)
        return self.rank([s for s in game.alive if s != self.seat], b.evil_pct)[0]

    def slayer_pick(self, game):
        b = game.belief_of(self)
        top = self.rank([s for s in game.alive if s != self.seat], lambda s: -b.demon_pct(s))[0]
        return top if b.demon_pct(top) >= self.threshold(self.profile.slayer_at, game) else None

    def suspicion(self, game, s):
        """The solver's read plus a grudge against players who pushed executions that now look good."""
        b = game.belief_of(self)
        grudge = 0
        if self.profile.vote_memory:
            for day, nominator, nominee, voters in game.vote_log:
                if nominee in game.dead and nominee != s and game.executed_on(day) == nominee \
                        and b.evil_pct(nominee) < 30 and (s == nominator or s in voters):
                    grudge += self.profile.vote_memory
        return min(100, b.suspicion(s) + grudge)

    def nominate(self, game, nominated):
        if self.profile.tests_virgin and game.day == 1 and KIND[self.role] == "townsfolk" and self.role in SPENT:
            virgins = [s for s in game.alive if game.pub.claims[s] == "virgin" and s != self.seat
                       and s not in game.ever_nominated]
            if virgins:
                return virgins[0]
        cands = [s for s in game.alive if s != self.seat and s not in nominated]
        if not cands:
            return None
        top = self.rank(cands, lambda s: -self.suspicion(game, s))[0]
        return top if self.suspicion(game, top) >= self.threshold(self.profile.nominate_at, game) else None

    def vote(self, game, nominee, yes, needed, block, ghost):
        """Yes if suspicious enough and more suspicious than whoever is already on the block."""
        if nominee == self.seat:
            return False
        sus = self.suspicion(game, nominee)
        if block is not None and sus <= self.suspicion(game, block):
            return False
        t = self.threshold(self.profile.vote_at, game) - self.profile.bandwagon * yes
        if game.pub.claims[nominee] == "saint":
            t += self.profile.saint_caution
        if ghost:
            t = max(t, self.profile.ghost_vote_at)
        return sus >= t


class EvilAgent(Agent):
    """Knows the team; reads the town through its own profile, i.e. imagines the town reasoning
    the way it would itself, blind spots included."""

    def __init__(self, seat, team, profile, n, rng):
        super().__init__(seat, profile, n, rng)
        self.team = team
        self.survived = set()  # shared by the team: attacked players who didn't die

    def read(self, game, pub=None, base=None):
        return game.public_belief(pub, base, self.profile)

    def exposure(self, game, pub, base=None):
        """How suspicious the town would find the living evil team, given this record."""
        b = self.read(game, pub, base)
        return sum(2 * b.demon_pct(e) + b.evil_pct(e) for e in self.team if e in game.alive)

    def _targets(self, game):
        return [s for s in game.alive if s not in self.team]

    def nominate(self, game, nominated):
        b = self.read(game)
        cands = [s for s in self._targets(game) if s not in nominated]
        if not cands:
            return None
        top = self.rank(cands, lambda s: -b.suspicion(s))[0]
        return top if b.suspicion(top) >= self.threshold(self.profile.nominate_at, game) else None

    def vote(self, game, nominee, yes, needed, block, ghost):
        """Vote like a townsperson on good players, never for the team or to replace a good player."""
        if nominee in self.team or (block is not None and block not in self.team):
            return False
        if yes + 1 >= needed:
            return True
        if ghost:
            return False
        t = self.threshold(self.profile.vote_at, game) - self.profile.bandwagon * yes
        return self.read(game).suspicion(nominee) >= t

    def poison_pick(self, game):
        b = self.read(game)
        return self.rank(self._targets(game), lambda s: (-self.value(game, s), b.evil_pct(s)))[0]

    def kill_pick(self, game):
        b = self.read(game)
        cands = [s for s in self._targets(game) if s not in self.survived] or self._targets(game)
        safe = [s for s in cands if game.pub.claims[s] not in ("soldier", "ravenkeeper")] or cands
        return self.rank(safe, lambda s: (b.evil_pct(s), -self.value(game, s)))[0]
