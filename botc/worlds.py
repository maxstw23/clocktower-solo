"""Possible-worlds solver.

A world is a complete starting role assignment that agrees with the public record. Good players
are assumed to claim what they believe they are, so a world is fixed by who is evil (and as what)
plus who, if anyone, is the Drunk.

Some records only fit a world with an *excuse*: a poisoning, a Spy/Recluse misregistration, or the
Drunk. Each world carries the excuses it needs, so bounded players can filter worlds by which
excuses they think of and how many they tolerate (see agents.believe).
"""
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, replace
from itertools import combinations, permutations, product

from .public import day_tick, night_tick
from .roles import KIND, MINIONS, OUTSIDERS, SETUP, TOWNSFOLK, is_evil

OK, MISREG, FAIL = 0, 1, 2
SPY_EXTRA = frozenset(TOWNSFOLK + OUTSIDERS)
RECLUSE_EXTRA = frozenset(MINIONS + ("imp",))
PING_ROLES = ("washerwoman", "librarian", "investigator")

# Likelihood that an evil or Drunk reporter would have said exactly this, relative to a sober good
# player whose report was forced. Values below 1 make consistent info claims more trusted, which
# sounds right but backfires: evil players optimise their lies against this very model, so the
# bonus mostly rewards them (good's win rate at 8 players fell from ~43% to ~30%). Neutral for now.
FREE = {"empath": 1, "chef": 1, "fortune_teller": 1, "washerwoman": 1, "librarian": 1,
        "investigator": 1, "undertaker": 1, "ravenkeeper": 1, "monk": 1}
POISON_WEIGHT, MISREG_WEIGHT, DRUNK_WEIGHT = 0.1, 0.2, 0.2  # Occam: consider excuses, but discount them
NIGHT_KILLED_EVIL = 0.1  # the Demon rarely kills its own team


@dataclass(frozen=True)
class World:
    roles: tuple        # starting role by seat
    demon: int          # who is the Demon now
    poison_nights: int  # nights on which a poisoning is needed to explain the record
    misregs: int        # Spy/Recluse misregistrations needed
    weight: float       # relative plausibility (see FREE)

    @property
    def drunk(self):
        return self.roles.index("drunk") if "drunk" in self.roles else None

    @property
    def excuses(self):
        return self.poison_nights + self.misregs + (self.drunk is not None)


def structures(n, claims):
    """All starting role assignments allowed by the claims and the setup counts."""
    tf, out, mn, _ = SETUP[n]
    result = []
    for demon in range(n):
        for mins in combinations([s for s in range(n) if s != demon], mn):
            good = [s for s in range(n) if s != demon and s not in mins]
            gclaims = [claims[s] for s in good]
            if any(is_evil(c) or c == "drunk" for c in gclaims) or len(set(gclaims)) < len(gclaims):
                continue
            n_out = sum(KIND[c] == "outsider" for c in gclaims)
            for mroles in permutations(MINIONS, mn):
                expected = out + 2 * ("baron" in mroles)
                if n_out == expected:
                    drunks = (None,)
                elif n_out == expected - 1:
                    drunks = [s for s in good if KIND[claims[s]] == "townsfolk"]
                else:
                    continue
                for drunk in drunks:
                    roles = list(claims)
                    roles[demon] = "imp"
                    for s, r in zip(mins, mroles):
                        roles[s] = r
                    if drunk is not None:
                        roles[drunk] = "drunk"
                    result.append(tuple(roles))
    return result


def evaluate(roles, pub, allow_poison=True, allow_misreg=True):
    """Check one starting assignment against the record; return a World or None."""
    n = pub.n

    # Who is the Demon over time: the Imp, then possibly the Scarlet Woman.
    current = roles.index("imp")
    sw = roles.index("scarlet_woman") if "scarlet_woman" in roles else None
    promo_seat = promo_tick = None
    dead_tick = {}
    for d in sorted(pub.deaths, key=lambda d: d.tick):
        if d.seat == current:
            if d.cause == "night" or promo_seat is not None:
                return None  # no star-pass in this version; a second Demon death would end the game
            if sw is None or sw in dead_tick or n - len(dead_tick) < 5:
                return None  # the game would have ended
            promo_seat, promo_tick, current = sw, d.tick, sw
        dead_tick[d.seat] = d.tick

    def role_at(s, tick):
        return "imp" if s == promo_seat and tick > promo_tick else roles[s]

    def registers(s, tick):
        r = role_at(s, tick)
        return r, SPY_EXTRA if r == "spy" else RECLUSE_EXTRA if r == "recluse" else ()

    def ping(a, b, role, tick):
        (ra, ea), (rb, eb) = registers(a, tick), registers(b, tick)
        if role in (ra, rb):
            return OK
        return MISREG if role in ea or role in eb else FAIL

    def evil_count(seats, count, tick):
        flex = [s for s in seats if role_at(s, tick) in ("spy", "recluse")]
        truth = {s: is_evil(role_at(s, tick)) for s in seats}
        results = {}
        for flips in product((False, True), repeat=len(flex)):
            evil = dict(truth)
            for s, f in zip(flex, flips):
                evil[s] ^= f
            c = count(evil)
            results[c] = results.get(c, True) and any(flips)
        return results  # count -> needs a misregistration

    def alive_after(tick):
        return [s for s in range(n) if dead_tick.get(s, 10**9) > tick]

    def neighbours(s, tick):
        alive = set(alive_after(tick)) - {s}
        found = []
        for step in (-1, 1):
            x = (s + step) % n
            while x not in alive and x != s:
                x = (x + step) % n
            if x != s:
                found.append(x)
        return found

    def check(r):
        tick = night_tick(r.night)
        d = r.data
        if r.kind in PING_ROLES:
            if d[0] is None:  # Librarian: no Outsiders in play
                worst = OK
                for s in range(n):
                    role = role_at(s, tick)
                    if KIND[role] == "outsider":
                        if role != "recluse":
                            return FAIL
                        worst = MISREG
                return worst
            return ping(d[0], d[1], d[2], tick)
        if r.kind in ("chef", "empath"):
            if r.kind == "chef":
                seats = list(range(n))
                counts = evil_count(seats, lambda e: sum(e[i] and e[(i + 1) % n] for i in seats), tick)
            else:
                seats = neighbours(r.seat, tick)
                counts = evil_count(seats, lambda e: sum(e.values()), tick)
            if d[0] not in counts:
                return FAIL
            return MISREG if counts[d[0]] else OK
        if r.kind == "undertaker":
            ra, ea = registers(d[0], day_tick(r.night - 1))
            return OK if d[1] == ra else MISREG if d[1] in ea else FAIL
        if r.kind == "ravenkeeper":
            ra, ea = registers(d[0], tick)
            return OK if d[1] == ra else MISREG if d[1] in ea else FAIL
        return OK

    req = defaultdict(set)     # night -> seats that must have been poisoned
    forbid = defaultdict(set)  # night -> seats that must not have been poisoned
    misregs = 0

    def excuse(res, s, night):
        nonlocal misregs
        if res == OK:
            return True
        if res == MISREG and allow_misreg:
            misregs += 1
            return True
        if allow_poison:
            req[night].add(s)
            return True
        return False

    def sober(s):
        return not is_evil(roles[s]) and roles[s] != "drunk"

    weight = 1.0
    ft_reports, monk_reports = [], []
    for r in pub.reports:
        if not sober(r.seat) or roles[r.seat] != r.kind:
            weight *= FREE.get(r.kind, 1)
            continue
        if r.kind == "fortune_teller":
            ft_reports.append(r)
        elif r.kind == "monk":
            monk_reports.append(r)
        elif not excuse(check(r), r.seat, r.night):
            return None

    for d in pub.deaths:
        if d.cause == "night":
            if is_evil(roles[d.seat]):
                weight *= NIGHT_KILLED_EVIL
            night = (d.tick + 1) // 2
            if role_at(d.seat, d.tick) == "soldier" and not excuse(FAIL, d.seat, night):
                return None
            for m in monk_reports:
                if m.night == night and m.data[0] == d.seat and not excuse(FAIL, m.seat, night):
                    return None
        elif d.cause == "execution" and role_at(d.seat, d.tick) == "saint":
            if not excuse(FAIL, d.seat, d.tick // 2):
                return None

    for sh in pub.shots:
        target = role_at(sh.target, day_tick(sh.day))
        if sh.killed:
            if roles[sh.shooter] != "slayer":
                return None
            forbid[sh.day].add(sh.shooter)
            if target == "recluse" and allow_misreg:
                misregs += 1
            elif target != "imp":
                return None
        elif roles[sh.shooter] == "slayer" and target == "imp":
            if not excuse(FAIL, sh.shooter, sh.day):
                return None

    for fn in pub.first_noms:
        nominator = role_at(fn.nominator, day_tick(fn.day))
        if fn.triggered:
            if roles[fn.nominee] != "virgin":
                return None
            forbid[fn.day].add(fn.nominee)
            if nominator == "spy" and allow_misreg:
                misregs += 1
            elif KIND[nominator] != "townsfolk":
                return None
        elif roles[fn.nominee] == "virgin" and KIND[nominator] == "townsfolk":
            if not excuse(FAIL, fn.nominee, fn.day):
                return None

    poisoner = roles.index("poisoner") if "poisoner" in roles else None

    def poison_ok(need):
        for night, seats in need.items():
            if len(seats) > 1 or poisoner is None or seats & forbid[night]:
                return False
            if dead_tick.get(poisoner, 10**9) < night_tick(night):
                return False
        return True

    if ft_reports:
        # The red herring is one fixed good player; pick whichever explains the record most cheaply.
        best = None
        for rh in (s for s in range(n) if not is_evil(roles[s])):
            need = defaultdict(set, {k: set(v) for k, v in req.items()})
            extra = 0
            for r in ft_reports:
                a, b, yes = r.data
                tick = night_tick(r.night)
                truth = any(role_at(x, tick) == "imp" or x == rh for x in (a, b))
                if yes == truth:
                    continue
                if yes and allow_misreg and any(role_at(x, tick) == "recluse" for x in (a, b)):
                    extra += 1
                elif allow_poison:
                    need[r.night].add(r.seat)
                else:
                    break
            else:
                if poison_ok(need):
                    cost = len(need) + extra
                    if best is None or cost < best[0]:
                        best = (cost, need, extra)
        if best is None:
            return None
        _, req, extra = best
        misregs += extra
    elif not poison_ok(req):
        return None

    weight *= POISON_WEIGHT ** len(req) * MISREG_WEIGHT ** misregs * (DRUNK_WEIGHT if "drunk" in roles else 1)
    return World(roles, current, len(req), misregs, weight)


def _extends(pub, base):
    """True if `pub` is `base` plus later events (records only ever grow)."""
    return pub.claims == base.claims and all(
        getattr(pub, f)[:len(getattr(base, f))] == getattr(base, f)
        for f in ("reports", "deaths", "shots", "first_noms"))


class Solver:
    """Enumerates worlds, caching by public record."""

    def __init__(self, cache_size=50000):
        self._structs = {}
        self._cache = OrderedDict()
        self._latest = None  # last record solved from scratch or by extension
        self.cache_size = cache_size

    def structures(self, pub):
        key = (pub.n, pub.claims)
        if key not in self._structs:
            self._structs[key] = structures(pub.n, pub.claims)
        return self._structs[key]

    def worlds(self, pub, allow_poison=True, allow_misreg=True, base=None):
        """`base`, if given, must be a record that `pub` only adds to; its worlds seed the search."""
        pub = replace(pub, votes=())  # votes don't constrain roles; don't re-solve on every vote
        base = base and replace(base, votes=())
        key = (pub, allow_poison, allow_misreg)
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit
        if not (allow_poison and allow_misreg):
            candidates = [w.roles for w in self.worlds(pub, base=base)]
        elif base is not None:
            candidates = [w.roles for w in self.worlds(base)]
        elif self._latest is not None and self._latest != pub and _extends(pub, self._latest):
            candidates = [w.roles for w in self.worlds(self._latest)]
        else:
            candidates = self.structures(pub)
        result = [w for w in (evaluate(r, pub, allow_poison, allow_misreg) for r in candidates) if w]
        if allow_poison and allow_misreg and base is None:
            self._latest = pub
        self._cache[key] = result
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return result


@dataclass(frozen=True)
class Belief:
    """Weighted tallies over the worlds a player considers."""
    total: float
    demon: tuple
    evil: tuple
    relaxed: bool = False  # had to widen its assumptions to find any world
    count: int = 0         # number of worlds

    @classmethod
    def empty(cls, n):
        return cls(0.0, (0.0,) * n, (0.0,) * n)

    def demon_pct(self, s):
        return int(100 * self.demon[s] / self.total) if self.total else 0

    def evil_pct(self, s):
        return int(100 * self.evil[s] / self.total) if self.total else 0

    def suspicion(self, s):
        return (2 * self.demon_pct(s) + self.evil_pct(s)) // 3

    def candidates(self):
        """Effective number of Demon candidates (inverse Simpson index)."""
        sq = sum(c * c for c in self.demon)
        return self.total ** 2 / sq if sq else 0.0


def tally(n, worlds, relaxed=False):
    demon, evil = [0.0] * n, [0.0] * n
    for w in worlds:
        demon[w.demon] += w.weight
        for s, r in enumerate(w.roles):
            if is_evil(r):
                evil[s] += w.weight
    return Belief(sum(w.weight for w in worlds), tuple(demon), tuple(evil), relaxed, len(worlds))
