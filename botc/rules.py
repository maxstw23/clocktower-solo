"""The rulebook every player shares, novices included.

Every ability gives information in one of four categories (see DESIGN.md):

    identity     x's character is in a set        Washerwoman, Librarian, Investigator, Undertaker, Ravenkeeper
    count        evil players in a group = k      Chef, Empath
    demon_test   the Demon (or a decoy) is in G   Fortune Teller
    event        who survived or died, and how    Monk (checked against deaths, not here)

A character is a row in CHARACTERS. Each category has one truth check, `truth`, which says whether
a report fits a grimoire, and one generator, `candidates`, of everything the ability could say.
The engine uses both to give real information (the true candidates) and to give a drunk or
poisoned player something (any candidate); the solver uses the truth check to test worlds.

A grimoire is seen through a View: whatever it is (the real game or a hypothetical world), it
answers role_at(seat, tick), demon_at(tick), alive_after(tick), could_be(seat, role) and red_herring.
"""
from dataclasses import dataclass
from itertools import combinations, product

from .public import day_tick, night_tick
from .roles import ALL_ROLES, MINIONS, OUTSIDERS, SETUP, TOWNSFOLK, WILD, is_evil

OK, MISREG, FAIL = 0, 1, 2  # true; true if a Spy or Recluse registers falsely; false
SPY_EXTRA = frozenset(TOWNSFOLK + OUTSIDERS)   # what the Spy may register as, besides itself
RECLUSE_EXTRA = frozenset(MINIONS + ("imp",))  # likewise the Recluse
ZERO = (None, None, None)  # Librarian: no Outsiders in play


@dataclass(frozen=True)
class Ability:
    category: str = ""  # identity | count | demon_test | event | "" (no information)
    when: str = ""      # first (night 1) | each (every night) | after_execution | on_death | later (from night 2)
    pool: tuple = ()    # identity: the characters it can name
    shape: str = ""     # what the data looks like: pair, executed, chosen, adjacent, neighbours


CHARACTERS = {
    "washerwoman": Ability("identity", "first", TOWNSFOLK, "pair"),
    "librarian": Ability("identity", "first", OUTSIDERS, "pair"),
    "investigator": Ability("identity", "first", MINIONS, "pair"),
    "chef": Ability("count", "first", shape="adjacent"),
    "empath": Ability("count", "each", shape="neighbours"),
    "fortune_teller": Ability("demon_test", "each", shape="pair"),
    "undertaker": Ability("identity", "after_execution", ALL_ROLES, "executed"),
    "ravenkeeper": Ability("identity", "on_death", ALL_ROLES, "chosen"),
    "monk": Ability("event", "later", shape="chosen"),
}


def ability(role):
    return CHARACTERS.get(role, Ability())


def registers(role, as_role):
    """Whether a player of this (concrete) role shows up as `as_role`: OK, MISREG or FAIL."""
    if role == as_role:
        return OK
    if (role == "spy" and as_role in SPY_EXTRA) or (role == "recluse" and as_role in RECLUSE_EXTRA):
        return MISREG
    return FAIL


def registered_as(role, pool):
    """Every character in `pool` this role can show up as."""
    return {r for r in pool if registers(role, r) != FAIL}


def evil_counts(view, seats, count, tick):
    """count -> whether getting that count needs a misregistration, over the ways the Spy and
    Recluse among `seats` may register."""
    flex = [s for s in seats if view.role_at(s, tick) in ("spy", "recluse")]
    truth = {s: is_evil(view.role_at(s, tick)) for s in seats}
    results = {}
    for flips in product((False, True), repeat=len(flex)):
        evil = dict(truth)
        for s, f in zip(flex, flips):
            evil[s] ^= f
        c = count(evil)
        results[c] = results.get(c, True) and any(flips)
    return results


def neighbours(view, s, tick):
    """The nearest living players on each side."""
    n = view.n
    alive = set(view.alive_after(tick)) - {s}
    found = []
    for step in (-1, 1):
        x = (s + step) % n
        while x not in alive and x != s:
            x = (x + step) % n
        if x != s:
            found.append(x)
    return found


def _match(view, s, role, tick):
    r = view.role_at(s, tick)
    if r in WILD:
        return OK if view.could_be(s, role) else FAIL
    return registers(r, role)


def truth(r, view):
    """Does report `r` fit the grimoire seen through `view`? OK, MISREG (only if a Spy or Recluse
    registers falsely) or FAIL."""
    a = ability(r.kind)
    tick = night_tick(r.night)
    d = r.data
    if a.category == "identity":
        if d == ZERO:  # Librarian: no Outsiders
            worst = OK
            for s in range(view.n):
                role = view.role_at(s, tick)
                if role in OUTSIDERS or role == "?outsider":
                    if role != "recluse":
                        return FAIL
                    worst = MISREG
            return worst
        if a.shape == "pair":
            return min(_match(view, d[0], d[2], tick), _match(view, d[1], d[2], tick))
        when = day_tick(r.night - 1) if a.shape == "executed" else tick
        return _match(view, d[0], d[1], when)
    if a.category == "count":
        if a.shape == "adjacent":
            n = view.n
            counts = evil_counts(view, list(range(n)), lambda e: sum(e[i] and e[(i + 1) % n] for i in range(n)), tick)
        else:
            counts = evil_counts(view, neighbours(view, r.seat, tick), lambda e: sum(e.values()), tick)
        if d[0] not in counts:
            return FAIL
        return MISREG if counts[d[0]] else OK
    if a.category == "demon_test":
        x, y, yes = d
        hit = any(view.demon_at(tick) == s or s == view.red_herring for s in (x, y))
        if yes == hit:
            return OK
        if yes and any(view.role_at(s, tick) == "recluse" for s in (x, y)):
            return MISREG
        return FAIL
    return OK


def candidates(kind, n, seat, arg=None):
    """Everything this ability could say in an n-player game (true or not). `arg` is the player(s)
    it chose or learns about: the Fortune Teller's pair, the Ravenkeeper's pick, the executed player."""
    a = ability(kind)
    others = [x for x in range(n) if x != seat]
    if a.category == "identity":
        if a.shape == "pair":
            out = [(x, y, r) for x, y in combinations(others, 2) for r in a.pool]
            return out + [ZERO] if kind == "librarian" else out
        return [(arg, r) for r in a.pool]
    if a.category == "count":
        evil = SETUP[n][2] + 1
        return [(k,) for k in range(3 if a.shape == "neighbours" else evil + 2)]
    if a.category == "demon_test":
        x, y = arg
        return [(x, y, False), (x, y, True)]
    return []


def names_own_character(kind, data):
    """Information that shows a player their own character as someone else's (which the
    Storyteller never gives, even to a drunk or poisoned player)."""
    a = ability(kind)
    return a.category == "identity" and data != ZERO and data[-1] == kind


def frames(r, evil):
    """Whether report `r` points at players for whom `evil(seat, role)` holds."""
    a, d = ability(r.kind), r.data
    if a.category == "identity" and d != ZERO:
        seats = d[:2] if a.shape == "pair" else d[:1]
        return (r.kind == "investigator" or is_evil(d[-1])) and any(evil(s, d[-1]) for s in seats)
    if a.category == "demon_test":
        return d[2] and any(evil(s, None) for s in d[:2])
    return False
