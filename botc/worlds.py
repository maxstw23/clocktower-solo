"""Possible-worlds solver.

A world is a complete starting role assignment that agrees with the public record. A good player's
*latest* claim is taken as what they believe they are, so a world is fixed by who is evil (and as
what), who if anyone is the Drunk, and which good players' roles are unknown: those who haven't
claimed, and at most one good player who is still bluffing.

Some records only fit a world with an *excuse*: a poisoning, a Spy/Recluse misregistration, the
Drunk, or a good player's bluff. Each world carries the excuses it needs, so bounded players can
filter worlds by which excuses they think of and how many they tolerate (see agents.believe).

A bluff is only considered where the record gives a reason to (`liar_candidates`): a double claim,
an Outsider or evil claim, or a claimed ability that visibly failed. Allowing it everywhere would
multiply the worlds by the number of players. A lie that leaves no such trace is believed, which
is also how a real table works.
"""
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import combinations, permutations, product

from .public import day_tick, night_tick
from .roles import KIND, MINIONS, OUTSIDERS, SETUP, TOWNSFOLK, WILD, is_evil

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
BLUFF_WEIGHT = 0.2       # a good player is still bluffing
CHANGE_WEIGHT = 0.7      # per claim change by a good player: having lied costs trust
OF_KIND = {"townsfolk": TOWNSFOLK, "outsider": OUTSIDERS}


@dataclass(frozen=True)
class World:
    roles: tuple        # starting role by seat
    demon: int          # who is the Demon now
    poison_nights: int  # nights on which a poisoning is needed to explain the record
    misregs: int        # Spy/Recluse misregistrations needed
    weight: float       # relative plausibility (see FREE)
    bluffs: int = 0     # good players whose current claim is a bluff

    @property
    def drunk(self):
        return self.roles.index("drunk") if "drunk" in self.roles else None

    @property
    def excuses(self):
        return self.poison_nights + self.misregs + (self.drunk is not None) + self.bluffs


@lru_cache(maxsize=4096)
def liar_candidates(pub):
    """Players the record gives a reason to suspect of a good bluff."""
    claims = pub.claims
    found, by_role = set(), defaultdict(list)
    outsiders = [s for s, r in enumerate(claims) if r is not None and KIND[r] == "outsider"]
    if len(outsiders) > SETUP[pub.n][1] + 2:  # more than even a Baron allows
        found.update(outsiders)
    for s, r in enumerate(claims):
        if r is None:
            continue
        by_role[r].append(s)
        if is_evil(r) or r == "drunk":
            found.add(s)
    for seats in by_role.values():
        if len(seats) > 1:
            found.update(seats)
    for d in pub.deaths:
        if (d.cause == "night" and claims[d.seat] == "soldier") or (d.cause == "execution" and claims[d.seat] == "saint"):
            found.add(d.seat)
    for fn in pub.first_noms:
        if not fn.triggered and claims[fn.nominee] == "virgin":
            found.add(fn.nominee)
    for r in pub.reports:
        if r.kind == "monk" and claims[r.seat] == "monk" and any(
                d.seat == r.data[0] and d.cause == "night" and d.tick == night_tick(r.night) for d in pub.deaths):
            found.add(r.seat)
        # Info naming a good character for someone who claims something else: one of them may be hiding.
        if r.kind in ("washerwoman", "librarian") and r.data[0] is not None \
                and r.data[2] not in (claims[r.data[0]], claims[r.data[1]]):
            found.update(x for x in r.data[:2] if claims[x] is not None)
        if r.kind in ("undertaker", "ravenkeeper") and not is_evil(r.data[1]) and claims[r.data[0]] not in (None, r.data[1]):
            found.add(r.data[0])
    return tuple(sorted(found))


def structures(n, claims, liars=()):
    """All starting role assignments allowed by the claims and the setup counts."""
    tf, out, mn, _ = SETUP[n]
    result = []
    for demon in range(n):
        for mins in combinations([s for s in range(n) if s != demon], mn):
            good = [s for s in range(n) if s != demon and s not in mins]
            for bluffer in [None] + [s for s in liars if s in good]:
                honest = [s for s in good if claims[s] is not None and s != bluffer]
                wild = [s for s in good if claims[s] is None or s == bluffer]
                hclaims = [claims[s] for s in honest]
                if any(is_evil(c) or c == "drunk" for c in hclaims) or len(set(hclaims)) < len(hclaims):
                    continue
                n_out = sum(KIND[c] == "outsider" for c in hclaims)
                for mroles in permutations(MINIONS, mn):
                    expected = out + 2 * ("baron" in mroles)
                    for drunk in [None] + [s for s in honest if KIND[claims[s]] == "townsfolk"]:
                        need = expected - n_out - (drunk is not None)  # Outsiders among unknown roles
                        if not 0 <= need <= len(wild):
                            continue
                        for outs in combinations(wild, need):
                            roles = list(claims)
                            roles[demon] = "imp"
                            for s, r in zip(mins, mroles):
                                roles[s] = r
                            for s in wild:
                                roles[s] = "?outsider" if s in outs else "?townsfolk"
                            if drunk is not None:
                                roles[drunk] = "drunk"
                            result.append(tuple(roles))
    return result


def timelines(roles, pub):
    """Every way the Demon could have passed from player to player given the deaths: a Demon
    executed (or shot) passes to the Scarlet Woman when 5+ are alive; a Demon dead at night has
    star-passed to a Minion (the Scarlet Woman if she's alive, else any living Minion).
    Each timeline is a list of (tick, new Demon)."""
    n = pub.n
    out = []

    def walk(deaths, current, promos, dead):
        if not deaths:
            out.append(promos)
            return
        d, rest = deaths[0], deaths[1:]
        if d.seat != current:
            walk(rest, current, promos, dead | {d.seat})
            return
        alive_minions = [s for s in range(n) if KIND[roles[s]] == "minion" and s not in dead and s != d.seat
                         and all(p[1] != s for p in promos)]
        sw = [s for s in alive_minions if roles[s] == "scarlet_woman"]
        if d.cause == "night":
            heirs = sw or alive_minions  # a star-pass
        else:
            heirs = sw if n - len(dead) >= 5 else []  # only the Scarlet Woman catches an executed Demon
        for h in heirs:
            walk(rest, h, promos + [(d.tick, h)], dead | {d.seat})
        # no heir: the game would have ended, so this world can't be ours

    walk(sorted(pub.deaths, key=lambda d: d.tick), roles.index("imp"), [], frozenset())
    return out


def evaluate(roles, pub, allow_poison=True, allow_misreg=True):
    """Check one starting assignment against the record; return the Worlds that fit (one per way
    the Demon may have passed on)."""
    return [w for w in (_evaluate(roles, pub, allow_poison, allow_misreg, t) for t in timelines(roles, pub)) if w]


def _evaluate(roles, pub, allow_poison, allow_misreg, promos):
    n = pub.n
    dead_tick = {d.seat: d.tick for d in pub.deaths}
    current = promos[-1][1] if promos else roles.index("imp")

    def demon_at(tick):
        demon = roles.index("imp")
        for t, s in promos:
            # A star-pass (at night) is in effect for whoever wakes later that same night.
            if tick > t or (tick == t and t % 2 == 1):
                demon = s
        return demon

    def role_at(s, tick):
        return "imp" if s == demon_at(tick) else roles[s]

    concrete = {r for r in roles if r not in WILD}

    def could_be(s, role):
        """An unknown good role could be any role of its kind not otherwise in play."""
        return roles[s] == role or (roles[s] in WILD and role in OF_KIND[KIND[roles[s]]] and role not in concrete)

    def match(s, role, tick):
        r = role_at(s, tick)
        if r == role or (r in WILD and could_be(s, role)):
            return OK
        if (r == "spy" and role in SPY_EXTRA) or (r == "recluse" and role in RECLUSE_EXTRA):
            return MISREG
        return FAIL

    def ping(a, b, role, tick):
        return min(match(a, role, tick), match(b, role, tick))

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
            return match(d[0], d[1], day_tick(r.night - 1))
        if r.kind == "ravenkeeper":
            return match(d[0], d[1], tick)
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

    # A peaceful night needs a reason: the Demon hit someone the Monk protected, or the Soldier,
    # or the Demon was poisoned. (The Demon always attacks in this version.)
    killed_on = {(d.tick + 1) // 2 for d in pub.deaths if d.cause == "night"}
    imp = roles.index("imp")
    for night in range(2, pub.nights + 1):
        tick = night_tick(night)
        demon = demon_at(tick)
        if night in killed_on or dead_tick.get(demon, 10**9) < tick:
            continue
        guards = [s for s in range(n) if dead_tick.get(s, 10**9) >= tick
                  and (could_be(s, "monk") or could_be(s, "soldier")) and roles[s] != "drunk"]
        if not guards and not excuse(FAIL, demon, night):
            return None

    for sh in pub.shots:
        target = "imp" if demon_at(day_tick(sh.day)) == sh.target else role_at(sh.target, day_tick(sh.day))
        if target == "imp" and demon_at(day_tick(sh.day)) != sh.target:
            target = "dead imp"
        if sh.killed:
            if not could_be(sh.shooter, "slayer"):
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
            if not could_be(fn.nominee, "virgin"):
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
                truth = any(demon_at(tick) == x or x == rh for x in (a, b))  # the Demon now, not a dead one
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

    bluffs = sum(1 for s in range(n) if roles[s] in WILD and pub.claims[s] is not None)
    for s, changes in enumerate(_claim_changes(pub)):
        if changes and not is_evil(roles[s]):
            weight *= CHANGE_WEIGHT ** changes
    weight *= POISON_WEIGHT ** len(req) * MISREG_WEIGHT ** misregs * (DRUNK_WEIGHT if "drunk" in roles else 1)
    weight *= BLUFF_WEIGHT ** bluffs
    return World(roles, current, len(req), misregs, weight, bluffs)


@lru_cache(maxsize=4096)
def _claim_changes(pub):
    return tuple(pub.claim_changes(s) for s in range(pub.n))


def _extends(pub, base):
    """True if `pub` is `base` plus later events (records only ever grow)."""
    return pub.claims == base.claims and liar_candidates(pub) == liar_candidates(base) and all(
        getattr(pub, f)[:len(getattr(base, f))] == getattr(base, f)
        for f in ("reports", "deaths", "shots", "first_noms", "claim_log"))


class Solver:
    """Enumerates worlds, caching by public record."""

    def __init__(self, cache_size=50000):
        self._structs = {}
        self._cache = OrderedDict()
        self._latest = None  # last record solved from scratch or by extension
        self.cache_size = cache_size

    def structures(self, pub):
        key = (pub.n, pub.claims, liar_candidates(pub))
        if key not in self._structs:
            self._structs[key] = structures(*key)
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
        elif base is not None and _extends(pub, base):
            candidates = [w.roles for w in self.worlds(base)]
        elif self._latest is not None and self._latest != pub and _extends(pub, self._latest):
            candidates = [w.roles for w in self.worlds(self._latest)]
        else:
            candidates = self.structures(pub)
        result = [w for r in dict.fromkeys(candidates) for w in evaluate(r, pub, allow_poison, allow_misreg)]
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
    pair: tuple = ()       # pair[r][t]: weight of worlds where r is good and t is evil

    @classmethod
    def empty(cls, n):
        return cls(0.0, (0.0,) * n, (0.0,) * n)

    def evil_if_good(self, t, r):
        """How likely t is evil if r is good."""
        good_r = self.total - self.evil[r]
        return self.pair[r][t] / good_r if self.pair and good_r > 0 else 0.0

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
    pair = [[0.0] * n for _ in range(n)]
    for w in worlds:
        demon[w.demon] += w.weight
        bad = [s for s, r in enumerate(w.roles) if is_evil(r)]
        for s in bad:
            evil[s] += w.weight
        for r in range(n):
            if r not in bad:
                row = pair[r]
                for t in bad:
                    row[t] += w.weight
    return Belief(sum(w.weight for w in worlds), tuple(demon), tuple(evil), relaxed, len(worlds),
                  tuple(map(tuple, pair)))
