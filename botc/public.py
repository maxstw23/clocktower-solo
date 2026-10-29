"""The public record: everything every player can see.

Time is a single integer tick: night n is 2n - 1 and day n is 2n.
"""
from dataclasses import dataclass, replace


def night_tick(n):
    return 2 * n - 1


def day_tick(d):
    return 2 * d


@dataclass(frozen=True)
class Report:
    """Information a player says their ability gave them on a given night."""
    seat: int
    night: int
    kind: str  # the role whose ability produced it
    data: tuple


@dataclass(frozen=True)
class Death:
    seat: int
    tick: int
    cause: str  # "night" | "execution" | "slayer"


@dataclass(frozen=True)
class Shot:
    day: int
    shooter: int
    target: int
    killed: bool


@dataclass(frozen=True)
class Nomination:
    """The first time a player is nominated (the only nomination that can trigger the Virgin)."""
    day: int
    nominator: int
    nominee: int
    triggered: bool


@dataclass(frozen=True)
class Claim:
    """A player says which character they are. Players may stay silent, lie, and change their claim."""
    day: int
    seat: int
    role: str


@dataclass(frozen=True)
class Whisper:
    """Something said in a private group; only the group hears it."""
    day: int
    group: tuple   # seats present
    speaker: int
    claim: object  # a character claimed to the group, or None
    report: object  # a Report shared with the group, or None
    seq: int       # order relative to public claims (a later private claim overrides an earlier public one)


@dataclass(frozen=True)
class Vote:
    """A nomination that went to a vote, and who raised a hand."""
    day: int
    nominator: int
    nominee: int
    voters: tuple


@dataclass(frozen=True)
class Public:
    """Everything said or done in the open. Every player remembers all of it."""
    n: int
    claims: tuple = ()     # current claim by seat (None: hasn't claimed)
    claim_log: tuple = ()  # every Claim in order, so changed claims are remembered
    reports: tuple = ()
    deaths: tuple = ()
    shots: tuple = ()
    first_noms: tuple = ()
    nights: int = 0    # nights completed (so a night with no death is known to have been peaceful)
    votes: tuple = ()  # not used by the solver, only by social reasoning

    def __hash__(self):
        # Records are dictionary keys everywhere; hash each one once.
        h = self.__dict__.get("_hash")
        if h is None:
            h = hash((self.n, self.claims, self.claim_log, self.reports, self.deaths, self.shots,
                      self.first_noms, self.votes, self.nights))
            object.__setattr__(self, "_hash", h)
        return h

    def plus(self, *reports):
        return replace(self, reports=self.reports + tuple(reports))

    def claim(self, day, seat, role):
        claims = list(self.claims or (None,) * self.n)
        claims[seat] = role
        return replace(self, claims=tuple(claims), claim_log=self.claim_log + (Claim(day, seat, role),))

    def claim_changes(self, seat):
        """How many times this player has changed their claim."""
        roles = [c.role for c in self.claim_log if c.seat == seat]
        return sum(a != b for a, b in zip(roles, roles[1:]))
