"""Players.

Good players reason through a bounded view of the solver, set by a Profile: which excuses they
think of, how many they tolerate, and fixed social dials for nominating and voting. Each player
also has a seeded personal ordering of the other seats that breaks ties, standing in for gut feel.

Evil players know their team and judge their moves by running the town's reasoning on the result.

Good players may bluff too: a fragile info role can hide behind a cover claim and reveal later.
They don't have to, and it costs them: a changed claim lowers everyone's trust in them.
"""
import random
from dataclasses import dataclass

from itertools import combinations

from . import notebook
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
    quiet_rate: float = 0.25  # good only: chance an info role keeps their character to private chats on day 1
    silence_cost: int = 15   # suspicion per night of info a claimed info role should have shared but didn't
    confide_at: int = 30     # good only: talk privately with (and confide in) players below this suspicion
    depth: int = 2           # notebook reasoner: rounds of trust propagation (1 = info at face value)
    breadth: int = 4         # notebook reasoner: suspects their theories are built from


PROFILES = {
    "novice": Profile("novice", considers_poison=False, considers_drunk=False,
                      considers_misregistration=False, max_excuses=0,
                      nominate_at=30, vote_at=25, bandwagon=6, saint_caution=10, lookahead=1,
                      ft_split=False, vote_memory=5, story_check=0, considers_bluffs=False, hide_rate=0,
                      confide_at=40, quiet_rate=0, silence_cost=8, depth=1, breadth=3),
    "regular": Profile("regular", considers_misregistration=False, max_excuses=1, nominate_at=30),
    "veteran": Profile("veteran", max_excuses=3, nominate_at=35, vote_at=35, bandwagon=1, lookahead=6,
                       tests_virgin=True, vote_memory=20, story_check=2, hide_rate=0.3, reveal_day=3,
                       confide_at=20, quiet_rate=0.35, silence_cost=20, depth=3, breadth=6),
}
# How "the town" reads the record; used by the Storyteller.
REFERENCE = Profile("reference")


REASONER = "solver"  # or "notebook" (see notebook.py); switching over is in progress


def believe(solver, pub, profile, seat=None, base=None):
    """Tally the worlds a player with this profile considers. Widens assumptions if none fit."""
    if not pub.claims:
        return Belief.empty(pub.n)
    if REASONER == "notebook":
        return notebook.believe(pub, seat, depth=profile.depth, breadth=profile.breadth)
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
        if claim == getattr(self, "role", None) and target != self.seat:
            return M("r_counter", role=R(claim))
        if game.silent_nights(target):
            return M("r_noinfo", role=R(claim))
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
        return M("r_nothing", v=self.seat * 3 + target)


class GoodAgent(Agent):
    def __init__(self, seat, role, profile, n, rng):
        super().__init__(seat, profile, n, rng)
        self.role = role  # what they believe they are
        self.slayer_used = False
        self.cover = None
        if role in FRAGILE and rng.random() < profile.hide_rate:
            self.cover = rng.choice([c for c in COVERS if c != role])
        # Some info roles keep their character to private chats at first, rather than bluff.
        self.quiet = self.cover is None and VALUE.get(role, 0) >= 2 and rng.random() < profile.quiet_rate

    def claim_now(self, game, pressed=False):
        """The claim to make now, or None to leave it as it is (or to stay silent)."""
        current = game.pub.claims[self.seat] if game.pub.claims else None
        if current is None:
            if self.quiet and not self.should_reveal(game, pressed):
                return None
            return self.cover or self.role
        if current != self.role and self.should_reveal(game, pressed):
            return self.role
        return None

    def should_reveal(self, game, pressed=False):
        if pressed or game.day >= self.profile.reveal_day or len(game.alive) <= 5:
            return True
        # Someone else claims my real role (or my cover): time to come out.
        return any(c in (self.role, self.cover) for s, c in enumerate(game.pub.claims or ()) if s != self.seat)

    def impostors(self, game):
        """Players publicly claiming my own character: I know they're lying (unless I'm the Drunk)."""
        claims = game.pub.claims or ()
        return [s for s, c in enumerate(claims) if c == self.role and s != self.seat and s in game.alive]

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
        if self.impostors(game) and game.pub.claims[self.seat] == self.role:
            top = self.impostors(game)[0]
            return top, M("r_counter", role=R(self.role))
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
        if s in self.impostors(game):
            grudge += 60  # they claim my character
        grudge += self.profile.silence_cost * len(game.silent_nights(s))
        return min(100, b.suspicion(s) + grudge)

    def hard_case(self, game, s):
        """Evidence alone (no grudges about votes) makes `s` very likely evil."""
        return game.belief_of(self).suspicion(s) >= 70

    def trusts_mayor(self, game):
        """Three alive and a Mayor claim I believe: no execution today wins the game for good."""
        claims = game.pub.claims or ()
        if len(game.alive) != 3:
            return False
        mayors = [s for s in game.alive if claims[s] == "mayor"]
        return any(s == self.seat and self.role == "mayor" or self.suspicion(game, s) < 40 for s in mayors)

    def waits(self, game):
        """Four alive: a wrong execution now loses, while no execution leaves the Imp one kill and
        the town a better guess at three (or a Mayor win). So hold off unless someone is clearly evil,
        when a Mayor I trust is alive or the Minions look dead."""
        if len(game.alive) != 4:
            return False
        b = game.belief_of(self)
        others = [s for s in game.alive if s != self.seat]
        if max(self.suspicion(game, s) for s in others) >= 70:
            return False
        claims = game.pub.claims or ()
        mayor = any(claims and claims[s] == "mayor" and (s == self.seat and self.role == "mayor" or
                                                         self.suspicion(game, s) < 40) for s in game.alive)
        minions_dead = self.profile.name != "novice" and sum(b.evil_pct(s) for s in others) < 125
        return mayor or minions_dead

    def nominate(self, game, nominated):
        if self.trusts_mayor(game) or self.waits(game):
            return None
        cands = [s for s in game.alive if s != self.seat and s not in nominated]
        if KIND[self.role] == "townsfolk":
            # Nominating a claimed Virgin as a Townsfolk gets you executed if they're real.
            cands = [s for s in cands if not (game.pub.claims and game.pub.claims[s] == "virgin"
                                              and s not in game.ever_nominated)]
        if not cands:
            return None
        fakes = [s for s in self.impostors(game) if s in cands]
        if fakes and game.pub.claims[self.seat] == self.role:
            return fakes[0]  # call out whoever claims my character
        if len(game.alive) <= 4:  # executing the real Saint now loses: only on hard evidence
            cands = [s for s in cands if game.pub.claims[s] != "saint" or self.hard_case(game, s)] \
                if game.pub.claims else cands
            if not cands:
                return None
        top = self.rank(cands, lambda s: -self.suspicion(game, s))[0]
        sus = self.suspicion(game, top)
        block = game.on_block
        if block is not None and sus <= self.suspicion(game, block) + (20 if len(game.alive) <= 4 else 5):
            return None  # I wouldn't vote to replace who's on the block
        # Someone who stands out from the rest is worth nominating even when nobody looks very bad.
        others = [self.suspicion(game, s) for s in game.alive if s not in (self.seat, top)]
        stands_out = bool(others) and sus >= 20 and sus >= sum(others) / len(others) + 15
        return top if sus >= self.threshold(self.profile.nominate_at, game) or stands_out else None

    def vote(self, game, nominee, yes, needed, block, ghost):
        """Yes if suspicious enough and clearly more suspicious than whoever is already on the block."""
        if nominee == self.seat or self.trusts_mayor(game) or self.waits(game):
            return False
        endgame = len(game.alive) <= 4
        sus = self.suspicion(game, nominee)
        # In the endgame a tie means nobody dies, which hands the game to evil: only switch for a clear reason.
        if nominee == game.volunteer and block is None:
            # Nobody better to execute: take the offer, unless someone else looks clearly worse.
            others = [self.suspicion(game, s) for s in game.alive if s not in (self.seat, nominee)]
            return not others or max(others) < self.threshold(self.profile.nominate_at, game)
        if block is not None and sus <= self.suspicion(game, block) + (20 if endgame else 5):
            return False
        if block is not None and yes + 1 + game.votes_left < needed \
                and self.suspicion(game, block) >= self.threshold(self.profile.vote_at, game):
            return False  # this vote can at best tie, which would save the player on the block
        t = self.threshold(self.profile.vote_at, game) - self.profile.bandwagon * yes
        if game.pub.claims and game.pub.claims[nominee] == "saint":
            t = max(t + self.profile.saint_caution, 70 if endgame else 0)
            if endgame and not self.hard_case(game, nominee):
                return False
        if ghost:
            # Dead players keep their one vote for the decisive days, unless they are nearly sure.
            t = max(t, self.profile.ghost_vote_at if endgame else 85)
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
        doomed = [s for s in self.team if s in game.alive and self.busses(game, s) and b.evil_pct(s) >= 60
                  and random.Random(f"bus-{game.seed}-{game.day}-{s}").random() < 0.5]
        if doomed:  # lead the charge against a Minion who is lost anyway
            return doomed[0], self.explain(game, doomed[0], b)
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

    def busses(self, game, minion):
        """A veteran Demon may sell out a Minion the town has already settled on, to look good."""
        return (self.seat == game.demon and self.profile.name == "veteran" and minion in self.team
                and minion != self.seat and self.read(game).evil_pct(minion) >= 55)

    def wants_starpass(self, game):
        """Kill yourself so a Minion becomes the Imp: when only moderately suspected (high suspicion
        would make the suicide look like what it is), and best when your own claimed info would then
        be believed and point at good players."""
        if game.night < 2 or self.seat != game.demon or self.profile.name == "novice" or len(game.alive) < 5:
            return False
        if not [s for s in game.alive if s in self.team and s != self.seat]:
            return False
        sus = self.read(game).suspicion(self.seat)
        framed = any(r.seat == self.seat and r.kind in ("empath", "chef", "investigator", "fortune_teller",
                                                       "washerwoman", "librarian") for r in game.known.reports)
        roll = random.Random(f"starpass-{game.seed}-{game.night}-{self.seat}").random()
        return 25 <= sus <= 55 and roll < (0.5 if framed else 0.15)

    def vote(self, game, nominee, yes, needed, block, ghost):
        """Vote like a townsperson on good players, never for the team or to replace a good player."""
        if self.busses(game, nominee) and yes + 2 >= needed and block is None:
            return True  # the Minion is going anyway: be seen voting for it
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
        if self.wants_starpass(game):
            return self.seat
        wish = game.suggest.get("kill")
        if wish in game.alive and wish not in self.team:
            return wish
        b = self.read(game)
        cands = [s for s in self._targets(game) if s not in self.survived] or self._targets(game)
        claims = game.pub.claims or (None,) * game.n
        safe = [s for s in cands if claims[s] not in ("soldier", "ravenkeeper")] or cands
        # Kill whoever is most dangerous: a valuable character the town trusts.
        return self.rank(safe, lambda s: b.evil_pct(s) - 10 * self.value(game, s))[0]
