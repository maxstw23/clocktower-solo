"""How a human player reads the table (see DESIGN.md, "reason like a human player").

1. A notebook: the record turned into evidence items (who says what about whom, how strongly) and
   clashes (sets of players of whom at least one is lying, drunk or poisoned). The strengths are
   common sense shared by every player, novice or veteran, like the rules themselves.
2. Trust flows through sources: evidence counts as much as its source is trusted, and a few
   rounds let discredit spread. Suspicion is scaled so the expected number of evil players
   matches the setup ("there are only two of them").
3. A few concrete theories ("the Demon is X, the Minions are Y") built from the top suspects and
   checked against the full rulebook, poisonings, the Drunk and Demon passes included.

Skill is how many rounds of trust a player thinks through (`depth`) and how many suspects their
theories are built from (`breadth`), never which rules they know.
"""
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from math import exp, log
from types import SimpleNamespace

from . import rules
from .public import night_tick
from .roles import KIND, SETUP, is_evil
from .worlds import Belief, evaluate, liar_candidates, structures, tally

# Strengths of evidence, in log-odds of being evil (negative: looks good).
NIGHT_DEATH = -2.5    # the Demon rarely kills its own team
VIRGIN_PROOF = -4.0   # a Virgin trigger: both players are good (barring a Spy nominator)
CONFIRMED = -1.0      # someone's information names your claimed character
NAMED_EVIL = 3.0      # someone's information names you as an evil character
ONE_OF_TWO = 1.2      # "one of these two is the Minion"
FT_YES, FT_NO = 1.2, -0.6
EMPATH_NONE, EMPATH_ONE, EMPATH_BOTH = -1.5, 0.7, 2.0
EVIL_CLAIM = 3.0      # claims an evil character
CHANGED = 0.5         # per claim change
CLASH = 2.0           # blame shared among a clash, by how little each member is trusted
SHOT_MISSED = -0.3    # a Slayer shot that did nothing: not the Demon


@dataclass(frozen=True)
class Note:
    source: object  # the seat it comes from, or None for the game itself
    target: int
    weight: float
    why: str
    back: float = 0.5  # evidence cuts both ways: how much of it falls back on the source when the
                       # target looks the other way (an accuser of a good-looking player, or a
                       # voucher for an evil-looking one, is lying, drunk or poisoned)


@dataclass(frozen=True)
class Clash:
    seats: tuple  # at least one of them is lying, drunk or poisoned
    why: str


def notebook(pub):
    """The record as evidence and clashes."""
    n, claims = pub.n, pub.claims or (None,) * pub.n
    notes, clashes = [], []
    holders = defaultdict(list)
    for s, r in enumerate(claims):
        if r is not None:
            holders[r].append(s)
    for r, seats in holders.items():
        if is_evil(r):
            notes += [Note(s, s, EVIL_CLAIM, "evil_claim") for s in seats]
        elif len(seats) > 1:
            clashes.append(Clash(tuple(seats), "double_claim"))
    outsiders = [s for s, r in enumerate(claims) if r is not None and KIND[r] == "outsider"]
    if len(outsiders) > SETUP[n][1] + 2:
        clashes.append(Clash(tuple(outsiders), "too_many_outsiders"))
    for s in range(n):
        changes = pub.claim_changes(s)
        if changes:
            notes.append(Note(s, s, CHANGED * changes, "changed_claim"))

    dead_at = {d.seat: d.tick for d in pub.deaths}
    alive = SimpleNamespace(n=n, alive_after=lambda tick: [x for x in range(n) if dead_at.get(x, 10**9) > tick])
    for r in pub.reports:
        a, d, src = rules.ability(r.kind), r.data, r.seat
        if a.category == "identity":
            if d == rules.ZERO:
                clashes += [Clash((src, x), "no_outsiders") for x in outsiders if x != src]
                continue
            seats = [x for x in d[:-1] if x != src]
            role = d[-1]
            if is_evil(role):
                w = NAMED_EVIL if len(seats) == 1 else ONE_OF_TWO
                notes += [Note(src, x, w, "named_evil", 0.5 / len(seats)) for x in seats]
                continue
            fits = [x for x in seats if claims[x] == role]
            notes += [Note(src, x, CONFIRMED, "confirmed") for x in fits]
            if not fits:
                rivals = [x for x in holders.get(role, []) if x != src]
                clashes.append(Clash(tuple(sorted({src, *seats, *rivals})), "ping_misses"))
        elif a.category == "count" and a.shape == "neighbours":
            near = rules.neighbours(alive, src, night_tick(r.night))
            k = d[0]
            w = EMPATH_NONE if k == 0 else EMPATH_BOTH if k >= len(near) else EMPATH_ONE
            notes += [Note(src, x, w, "empath") for x in near]
        elif a.category == "demon_test":
            notes += [Note(src, x, FT_YES if d[2] else FT_NO, "fortune_teller", 0.25) for x in d[:2] if x != src]
    for death in pub.deaths:
        if death.cause == "night":
            notes.append(Note(None, death.seat, NIGHT_DEATH, "night_death"))
    for sh in pub.shots:
        if not sh.killed:
            notes.append(Note(None, sh.target, SHOT_MISSED, "shot_missed"))
    for fn in pub.first_noms:
        if fn.triggered:
            notes += [Note(None, x, VIRGIN_PROOF, "virgin") for x in (fn.nominator, fn.nominee)]
        elif claims[fn.nominee] == "virgin" and claims[fn.nominator] is not None \
                and KIND[claims[fn.nominator]] == "townsfolk":
            clashes.append(Clash((fn.nominator, fn.nominee), "virgin_silent"))
    return notes, clashes


def _sigmoid(x):
    return 1 / (1 + exp(-x))


def _scaled(score, seats, expected):
    """Probabilities from log-odds, shifted so they add up to the expected number of evil players."""
    lo, hi = -20.0, 20.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if sum(_sigmoid(score[s] + mid) for s in seats) > expected:
            hi = mid
        else:
            lo = mid
    return {s: _sigmoid(score[s] + lo) for s in seats}


def suspicions(pub, seat=None, depth=2):
    """Each player's chance of being evil, as this player reads the notebook."""
    n = pub.n
    notes, clashes = notebook(pub)
    expected = SETUP[n][2] + 1
    seats = [s for s in range(n) if s != seat]
    base = expected / len(seats)
    p = {s: base for s in seats}
    if seat is not None:
        p[seat] = 0.0
    for _ in range(max(1, depth)):
        score = {s: log(base / (1 - base)) for s in seats}
        for note in notes:
            if note.target not in score:
                continue
            src = note.source
            trust = 1.0 if src is None or src == seat else 1 - p[src]
            score[note.target] += note.weight * trust
            if src in score and src != note.target:
                # Accusing someone who looks good, or vouching for someone who looks evil.
                wrong = 1 - p[note.target] if note.weight > 0 else p[note.target]
                score[src] += abs(note.weight) * note.back * wrong
        for c in clashes:
            blame = {s: p[s] for s in c.seats}
            total = sum(blame.values())
            for s in c.seats:
                if s in score and total > 0:
                    score[s] += CLASH * blame[s] / total
        p = {**_scaled(score, seats, expected), **({seat: 0.0} if seat is not None else {})}
    return p


def believe(pub, seat=None, role=None, depth=2, breadth=4):
    """A Belief (same shape as the world solver's) from a notebook read and a few theories."""
    n = pub.n
    if not pub.claims:
        return Belief.empty(n)
    p = suspicions(pub, seat, depth)
    mn = SETUP[n][2]
    others = sorted((s for s in range(n) if s != seat), key=lambda s: (-p[s], s))
    relaxed = False
    for k in (max(breadth, mn + 1), max(breadth, mn + 1) + 3):
        top = others[:k]
        where = [(d, mins) for d in top for mins in combinations([x for x in top if x != d], mn)]
        worlds = [w for roles in structures(n, pub.claims, liar_candidates(pub), where)
                  for w in evaluate(roles, pub) if seat is None or not is_evil(w.roles[seat])]
        if worlds:
            break
        relaxed = True
    if not worlds:
        total = sum(p.values()) or 1
        return Belief(1.0, tuple(p.get(s, 0) / total for s in range(n)), tuple(p.get(s, 0) for s in range(n)), True)
    # A theory is as plausible as it is consistent with the rules, times how its suspects look.
    weighted = []
    for w in worlds:
        odds = 1.0
        for s, r in enumerate(w.roles):
            if is_evil(r) and s != seat:
                odds *= p[s] / max(1e-6, 1 - p[s])
        weighted.append(SimpleNamespace(roles=w.roles, demon=w.demon, weight=w.weight * odds))
    t = tally(n, weighted, relaxed)
    if not t.total:
        return t
    # Alignment: half the notebook (which covers everyone), half the theories.
    evil = tuple(t.total * (p.get(s, 0) + t.evil[s] / t.total) / 2 for s in range(n))
    return Belief(t.total, t.demon, evil, relaxed, t.count, t.pair)


def clashes_with(seat, pub):
    """How many clashes in the record involve this player."""
    return sum(seat in c.seats for c in notebook(pub)[1])


def fits(pub, seat, breadth=4):
    """Whether some theory has this player as the honest good character they claim."""
    return believe(pub, seat, depth=1, breadth=breadth).count > 0
