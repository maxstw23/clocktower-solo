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
class Public:
    n: int
    claims: tuple = ()  # claimed role by seat, set once on day 1
    reports: tuple = ()
    deaths: tuple = ()
    shots: tuple = ()
    first_noms: tuple = ()

    def plus(self, *reports):
        return replace(self, reports=self.reports + tuple(reports))
