"""Players.

Good players reason through a bounded view of the solver, set by a Profile: which excuses they
think of, how many they tolerate, and fixed social dials for nominating and voting. Each player
also has a seeded personal ordering of the other seats that breaks ties, standing in for gut feel.

Evil players know their team and judge their moves by running the town's reasoning on the result.

Good players may bluff too: a fragile info role can hide behind a cover claim and reveal later.
They don't have to, and it costs them: a changed claim lowers everyone's trust in them.
"""
from dataclasses import dataclass

from itertools import combinations

from .i18n import M, R, S
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
    story_check: int = 1     # evil only: before lying, check the lie fits 0 = nothing, 1 = their own
                             # earlier claims, 2 = the whole record
    ft_split: bool = True    # Fortune Teller picks pairs that split the suspects instead of the top two
    tests_virgin: bool = False  # a townsfolk nominates the claimed Virgin on day 1 to test both
    vote_memory: int = 10    # how much a remembered push of a now-good-looking execution counts against
                             # the pusher (everyone remembers votes; this is how much they read into them)
    considers_bluffs: bool = True  # thinks a good player might be bluffing about their character
    hide_rate: float = 0.15  # good only: chance a fragile info role hides behind a cover claim on day 1
    reveal_day: int = 2      # good only: a hidden player comes out by this day (or earlier if pressed)
    speak_at: int = 25       # suspicion needed to say out loud whom they suspect
    confide_at: int = 30     # good only: talk privately with (and confide in) players below this suspicion


PROFILES = {
    "novice": Profile("novice", considers_poison=False, considers_drunk=False,
                      considers_misregistration=False, max_excuses=0,
                      nominate_at=30, vote_at=25, bandwagon=6, saint_caution=10, lookahead=1,
                      ft_split=False, vote_memory=5, story_check=0, considers_bluffs=False, hide_rate=0,
                      confide_at=40),
    "regular": Profile("regular", considers_misregistration=False, max_excuses=1),
    "veteran": Profile("veteran", max_excuses=3, nominate_at=40, vote_at=35, bandwagon=1, lookahead=6,
                       tests_virgin=True, vote_memory=20, story_check=2, hide_rate=0.3, reveal_day=3,
                       confide_at=20),
}
# How "the town" reads the record; used by the Storyteller.
REFERENCE = Profile("reference")


def believe(solver, pub, profile, seat=None, base=None):
    """Tally the worlds a player with this profile considers. Widens assumptions if none fit."""
    if not pub.claims:
        return Belief.empty(pub.n)
    p, m, dr, bl = (profile.considers_poison, profile.considers_misregistration, profile.considers_drunk,
                    profile.considers_bluffs)
    steps = ((p, m, dr, bl, profile.max_excuses), (p, m, dr, bl, 99), (True, True, True, True, 99))
    for level, (p, m, dr, bl, cap) in enumerate(steps):
        worlds = [w for w in solver.worlds(pub, p, m, base)
                  if w.excuses <= cap and (dr or w.drunk is None) and (bl or not w.bluffs)
                  and (seat is None or not is_evil(w.roles[seat]))]
        if worlds:
            return tally(pub.n, worlds, relaxed=level > 0)
    return Belief.empty(pub.n)


# Info roles whose ability is spent after night one: the natural Virgin testers.
SPENT = ("washerwoman", "librarian", "investigator", "chef")

# Info roles worth hiding on day 1, and the quiet roles they hide behind.
FRAGILE = ("fortune_teller", "empath", "undertaker", "monk")
COVERS = ("soldier", "mayor", "virgin")

# How much the evil team wants a claimed role silenced, and the town wants it protected.
VALUE = {"fortune_teller": 5, "empath": 5, "undertaker": 4, "monk": 3, "slayer": 3,
         "investigator": 2, "washerwoman": 2, "librarian": 2, "chef": 2, "virgin": 2, "mayor": 2,
         "ravenkeeper": 1}


class Agent:
    """Good and evil players draw from the same profiles: the same blind spots, dials and skill."""

    def __init__(self, seat, profile, n, rng):
        self.seat = seat
        self.profile = profile
        self.inbox = []  # info received but not yet shared
        order = list(range(n))
        rng.shuffle(order)
        self.bias = {s: i for i, s in enumerate(order)}

    def rank(self, seats, key):
        return sorted(seats, key=lambda s: (key(s), self.bias[s]))

    def value(self, game, s):
        """How valuable s's character is, as far as this player has heard (in public or in private)."""
        claims = game.record_for(self.seat).claims
        return VALUE.get(claims[s], 0) if claims else 0

    def threshold(self, base, game):
        if len(game.alive) <= 4:
            return 0  # endgame: every day without an execution is a day handed to evil
        return base - self.profile.urgency * (game.day - 1)

    def explain(self, game, target, b):
        """A reason for suspecting `target` (a message), from the record as this player reads it."""
        pub = game.record_for(self.seat)
        claim = pub.claims[target] if pub.claims else None
        if claim is None:
            return M("r_silent")
        if is_evil(claim):
            return M("r_evilclaim", role=R(claim))
        twins = [s for s, c in enumerate(pub.claims) if s != target and c == claim]
        if twins:
            return M("r_twin", x=S(twins[0]), role=R(claim))
        if pub.claim_changes(target):
            first = next(c.role for c in pub.claim_log if c.seat == target)
            return M("r_changed", old=R(first), new=R(claim))
        for v in reversed(pub.votes):
            if game.executed_on(v.day) == v.nominee and b.evil_pct(v.nominee) < 30 \
                    and target in (v.nominator, *v.voters):
                return M("r_pushed", x=S(v.nominee))
        for r in reversed(pub.reports):
            if r.seat == target or b.evil_pct(r.seat) >= 30:
                continue
            mine = r.seat == self.seat
            if r.kind == "fortune_teller" and r.data[2] and target in r.data[:2]:
                return M("r_ft_mine") if mine else M("r_ft", x=S(r.seat))
            if r.kind == "investigator" and r.data[0] is not None and target in r.data[:2]:
                return M("r_inv_mine", role=R(r.data[2])) if mine else M("r_inv", x=S(r.seat), role=R(r.data[2]))
        # Whose info, if true, most implicates them?
        best = max(((b.evil_if_good(target, r), r) for r in {x.seat for x in pub.reports}
                    if r != target and b.evil_pct(r) < 40), default=None)
        if best and best[0] >= 0.6:
            whose = M("my") if best[1] == self.seat else M("whose", x=S(best[1]))
            return M("r_ifinfo", whose=whose, pct=int(100 * best[0]))
        if b.demon_pct(target) >= 40:
            return M("r_demon_pct", pct=b.demon_pct(target))
        return M("r_nothing")


class GoodAgent(Agent):
    def __init__(self, seat, role, profile, n, rng):
        super().__init__(seat, profile, n, rng)
        self.role = role  # what they believe they are
        self.slayer_used = False
        self.cover = None
        if role in FRAGILE and rng.random() < profile.hide_rate:
            self.cover = rng.choice([c for c in COVERS if c != role])

    def claim_now(self, game, pressed=False):
        """The claim to make now, or None to leave it as it is."""
        current = game.pub.claims[self.seat] if game.pub.claims else None
        if current is None:
            return self.cover or self.role
        if current != self.role and self.should_reveal(game, pressed):
            return self.role
        return None

    def should_reveal(self, game, pressed=False):
        if pressed or game.day >= self.profile.reveal_day or len(game.alive) <= 5:
            return True
        # Someone else claims my real role (or my cover): time to come out.
        return any(c in (self.role, self.cover) for s, c in enumerate(game.pub.claims) if s != self.seat)

    def invite(self, game, free):
        """Whom to talk to privately: the players they trust most (two if they are hiding something)."""
        trusted = [s for s in self.rank(free, lambda s: self.suspicion(game, s))
                   if self.suspicion(game, s) < self.profile.confide_at]
        hiding = bool(game.pub.claims) and game.pub.claims[self.seat] != self.role
        return trusted[:2 if hiding else 1]

    def accept(self, game, inviter, invited):
        return self.suspicion(game, inviter) < self.profile.confide_at + 10

    def statement(self, game):
        """Whom they say they suspect, and why; None to stay quiet."""
        cands = [s for s in game.alive if s != self.seat]
        if self.seat in game.dead or not cands or not game.pub.claims:
            return None
        top = self.rank(cands, lambda s: -self.suspicion(game, s))[0]
        if self.suspicion(game, top) < self.profile.speak_at:
            return None
        return top, self.explain(game, top, game.belief_of(self))

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
        for v in game.known.votes:
            if v.nominee != s and game.executed_on(v.day) == v.nominee and b.evil_pct(v.nominee) < 30 \
                    and (s == v.nominator or s in v.voters):
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
        if game.pub.claims and game.pub.claims[nominee] == "saint":
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

    def value(self, game, s):
        """The evil team pools what its members heard in private: a confided role is a known target."""
        claims = [game.record_for(t).claims for t in sorted(self.team)]
        public = game.known.claims
        if not public:
            return 0
        heard = next((c[s] for c in claims if c and c[s] != public[s]), public[s])
        return VALUE.get(heard, 0)

    def exposure(self, game, pub, base=None):
        """How suspicious the town would find the living evil team, given this record."""
        b = self.read(game, pub, base)
        return sum(2 * b.demon_pct(e) + b.evil_pct(e) for e in self.team if e in game.alive)

    def _targets(self, game):
        return [s for s in game.alive if s not in self.team]

    def invite(self, game, free):
        """Plan with a human teammate if there is one; otherwise fish for secrets from the good
        player whose claim they'd most like to know about."""
        if game.human in self.team and game.human in free and game.day <= 2:
            return [game.human]
        targets = [s for s in free if s not in self.team]
        if not targets:
            return []
        return self.rank(targets, lambda s: -self.value(game, s))[:1]

    def accept(self, game, inviter, invited):
        return True  # every private conversation is a chance to learn something

    def statement(self, game):
        """Evil players accuse like anyone else, pointing at the good player the town already doubts."""
        cands = self._targets(game)
        if self.seat in game.dead or not cands or not game.pub.claims:
            return None
        b = self.read(game)
        top = self.rank(cands, lambda s: -b.suspicion(s))[0]
        if b.suspicion(top) < self.profile.speak_at:
            return None
        return top, self.explain(game, top, b)

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
        wish = game.suggest.get("poison")
        if wish in game.alive and wish not in self.team:
            return wish  # a teammate asked for this
        b = self.read(game)
        return self.rank(self._targets(game), lambda s: (-self.value(game, s), b.evil_pct(s)))[0]

    def kill_pick(self, game):
        wish = game.suggest.get("kill")
        if wish in game.alive and wish not in self.team:
            return wish
        b = self.read(game)
        cands = [s for s in self._targets(game) if s not in self.survived] or self._targets(game)
        claims = game.pub.claims or (None,) * game.n
        safe = [s for s in cands if claims[s] not in ("soldier", "ravenkeeper")] or cands
        # Kill whoever is most dangerous: a valuable character the town trusts.
        return self.rank(safe, lambda s: b.evil_pct(s) - 10 * self.value(game, s))[0]
