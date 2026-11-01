"""Arguments told the way people tell them: who did or said what, but then what happened, so what
follows ("Guodong checked Chenxi and Dawei on night 2 and got a YES. Then on night 3 he was killed:
the Demon was afraid of him. So I suspect Dawei.").

Every story is built from the record and the speaker's notebook (notebook.py), so it says nothing
the speaker doesn't actually believe (or, for an evil speaker, what the public record supports).
A few shapes cover most table talk:

    fulfilled   someone's information pointed at X, and then the Demon killed them
    targeted    X nominated or accused someone who turned out good
    clash       X's claim can't be true together with someone else's
    no_vote     X said they suspected someone, then didn't vote for them
    outsiders   more Outsider claims than the setup allows

and a defence for the accused: a confirmation, "not just me", an excuse for missing information,
a promise of information to come, a counter-accusation, or standing by an offer to be executed.
How many steps a player strings together is a skill dial (Profile.story).
"""
from types import SimpleNamespace

from . import notebook
from .i18n import Chain, L, M, R, S
from .public import night_tick
from .roles import KIND, SETUP, is_evil
from .rules import ability, neighbours


def _view(game, agent):
    return game.view_of(agent) if hasattr(agent, "role") else game.record_for(agent.seat)


def _night_death(pub, x, after_night):
    """The night x was killed, if after `after_night`."""
    return next(((d.tick + 1) // 2 for d in pub.deaths
                 if d.seat == x and d.cause == "night" and d.tick > night_tick(after_night)), None)


def _points_at(r, target, pub):
    """The clause for report r if it points at `target`, else None."""
    a, d = ability(r.kind), r.data
    if a.category == "demon_test" and d[2] and target in d[:2]:
        return "ft"
    if a.category == "identity" and d[0] is not None and target in d[:-1] and is_evil(d[-1]):
        return "ping" if len(d) == 3 else "named"
    if a.category == "count" and a.shape == "neighbours" and d[0] > 0:
        dead_at = {dd.seat: dd.tick for dd in pub.deaths}
        alive = SimpleNamespace(n=pub.n, alive_after=lambda tick: [x for x in range(pub.n)
                                                                   if dead_at.get(x, 10**9) > tick])
        if target in neighbours(alive, r.seat, night_tick(r.night)):
            return "empath"
    return None


class Teller:
    """Builds stories from one player's point of view."""

    def __init__(self, game, agent):
        self.game, self.agent, self.me = game, agent, agent.seat
        self.pub = _view(game, agent)
        mine = hasattr(agent, "role")
        self.p = notebook.suspicions(self.pub, self.me if mine else None, agent.profile.depth)
        self.notes, self.clashes = notebook.notebook(self.pub)

    def who(self, x):
        return M("i") if x == self.me else S(x)

    def info_clause(self, r, how, target):
        x, d, n = self.who(r.seat), r.data, r.night
        if how == "ft":
            return M("st_ft", x=x, a=S(d[0]), b=S(d[1]), n=n)
        if how == "ping":
            return M("st_ping", x=x, a=S(d[0]), b=S(d[1]), role=R(d[2]), n=n)
        if how == "named":
            return M("st_named", x=x, a=S(d[0]), role=R(d[1]), n=n)
        return M("st_empath", x=x, k=d[0], t=S(target), n=n)

    def why_not_other(self, o, target):
        """Why, of a pair, it's `target` and not `o`."""
        if o == self.me:
            return M("st_not_me")
        if any(d.seat == o and d.cause == "night" for d in self.pub.deaths):
            return M("st_other_dead", o=S(o))
        for note in self.notes:
            if note.target == o and note.why == "confirmed" and note.source not in (None, o) \
                    and self.p.get(note.source, 0) < 0.4:
                return M("st_other_confirmed", o=S(o), y=self.who(note.source))
        backed = self.cleared(o)
        if backed is not None:
            return backed
        if self.p.get(o, 0) + 0.1 < self.p.get(target, 0):
            return M("st_other_trusted", o=S(o))
        return None

    # --- accusations ---------------------------------------------------------------------------

    def fulfilled(self, target):
        out = []
        for r in self.game.pub.reports:  # only what has been said in public: never out a hidden role
            if r.seat == target or self.p.get(r.seat, 1) > 0.5:
                continue
            how = _points_at(r, target, self.pub)
            if not how:
                continue
            steps = [(None, self.info_clause(r, how, target))]
            weight = 2.0 * (1 - self.p.get(r.seat, 0)) if r.seat != self.me else 2.5
            killed = _night_death(self.pub, r.seat, r.night)
            if killed:
                steps += [("then", M("st_killed", x=self.who(r.seat), n=killed)), (None, M("st_feared"))]
                weight += 1.5
            if how in ("ft", "ping"):
                other = next((x for x in r.data[:2] if x != target), None)
                why = self.why_not_other(other, target) if other is not None else None
                if why is not None:
                    steps.append(("and", why))
                    weight += 0.5
                elif other is not None and other != self.me:
                    steps.append((None, M("st_one_of", a=S(target), b=S(other))))
                    weight -= 0.5
            out.append((weight, steps))
        return out

    def targeted(self, target):
        out = []
        pushed = [(v.day, v.nominee, "st_nominated") for v in self.pub.votes if v.nominator == target]
        pushed += [(d, x, "st_accused") for d, s, x in self.game.accusations if s == target]
        seen = set()
        for day, x, key in sorted(pushed):
            if x in seen or x == target:
                continue
            seen.add(x)
            killed = _night_death(self.pub, x, day)
            if killed and killed > day:
                steps = [(None, M(key, d=day, t=S(target), x=self.who(x))),
                         ("then", M("st_killed", x=self.who(x), n=killed)), (None, M("st_good_now", x=self.who(x)))]
                out.append((2.0, steps))
        return out

    def clashing(self, target):
        out = []
        claims = self.pub.claims or ()
        for c in self.clashes:
            if target not in c.seats:
                continue
            others = [x for x in c.seats if x != target]
            role = claims[target] if claims else None
            if c.why == "double_claim" and role:
                x = others[0]
                steps = [(None, M("st_claims", t=S(target), role=R(role)))]
                steps.append(("but", M("st_clash_me") if x == self.me else M("st_clash_double", x=S(x), role=R(role))))
                if x != self.me and self.p.get(x, 1) + 0.1 < self.p.get(target, 0):
                    steps.append(("and", M("st_trust_x", x=S(x))))
                out.append((2.2 if x == self.me else 1.6, steps))
            elif c.why == "virgin_silent":
                fn = next((f for f in self.pub.first_noms if {f.nominator, f.nominee} == set(c.seats)), None)
                if fn is None:
                    continue
                steps = [(None, M("st_virgin", d=fn.day, a=self.who(fn.nominator), t=self.who(fn.nominee))),
                         (None, M("st_clash_me") if self.me in c.seats else M("st_one_lies"))]
                out.append((2.4 if self.me in c.seats else 1.4, steps))
            elif role and others:
                x = min(others, key=lambda y: self.p.get(y, 1))
                steps = [(None, M("st_claims", t=S(target), role=R(role))),
                         ("but", M("st_clash_me") if self.me in c.seats else M("st_clash", x=S(x)))]
                if self.me not in c.seats and self.p.get(x, 1) + 0.1 < self.p.get(target, 0):
                    steps.append(("and", M("st_trust_x", x=S(x))))
                out.append((1.8 if self.me in c.seats else 1.2, steps))
        return out

    def no_vote(self, target):
        out = []
        for d, s, x in self.game.accusations:
            if s != target:
                continue
            for v in self.pub.votes:
                if v.day == d and v.nominee == x and target not in v.voters and v.nominator != target \
                        and all(not (dd.seat == target and dd.tick < 2 * d) for dd in self.pub.deaths):
                    out.append((1.3, [(None, M("st_no_vote", d=d, t=S(target), x=self.who(x)))]))
                    break
        return out[:1]

    def outsiders(self, target):
        claims = self.pub.claims or ()
        outs = [s for s, r in enumerate(claims) if r is not None and KIND[r] == "outsider"]
        if target not in outs or len(outs) <= SETUP[self.pub.n][1]:
            return []
        if SETUP[self.pub.n][1] == 0:
            first = M("st_no_outsiders", t=S(target), role=R(claims[target]))
        else:
            first = M("st_outsiders", k=len(outs))
        return [(1.0 + 0.3 * (len(outs) - SETUP[self.pub.n][1]),
                 [(None, first), (None, M("st_outsiders_why")),
                  ("and", M("st_claims", t=S(target), role=R(claims[target])))][:2 if SETUP[self.pub.n][1] == 0 else 3])]

    def cleared(self, x):
        """Why x looks good (from public information), as a clause, or None."""
        public = set(self.game.pub.reports)
        for note in self.notes:
            src = note.source
            if note.target != x or note.weight >= 0 or src == x:
                continue
            if src is None:
                if note.why == "virgin":
                    return M("st_cleared_virgin", x=S(x))
                continue
            if self.p.get(src, 1) > 0.5 or not any(r.seat == src for r in public):
                continue
            key = {"confirmed": "st_cleared_by", "empath": "st_cleared_empath",
                   "fortune_teller": "st_cleared_ft"}.get(note.why)
            if key:
                return M(key, x=S(x), y=self.who(src))
        return None

    def elimination(self, target):
        """Everyone else is vouched for by someone; only the target (and maybe a couple more) isn't."""
        others = [x for x in self.game.alive if x not in (target, self.me)]
        why = {x: self.cleared(x) for x in others}
        left = [x for x in others if why[x] is None]
        if len(left) > 2 or len(others) - len(left) < 2:
            return []
        # Group "A and B were cleared by my Empath reading".
        groups = {}
        for x in others:
            m = why[x]
            if m is not None:
                y = m.args.get("y")
                key = (m.key, getattr(y, "seat", None), getattr(y, "key", None))
                groups.setdefault(key, (m, []))[1].append(S(x))
        clauses = [M(m.key, x=L(xs, conj=True), y=m.args.get("y")) for m, xs in groups.values()][:3]
        steps = [(None, L(clauses))]
        if not left:
            steps.append((None, M("st_only", t=S(target))))
            return [(2.2, steps)]
        steps.append((None, M("st_only_some", list=L([S(target)] + [S(x) for x in left], conj=True))))
        # And why the target, of those left.
        helped = [x for x in left if any(n.source == x and n.why == "confirmed" for n in self.notes)]
        claims = self.pub.claims or ()
        role = claims[target] if claims else None
        if helped and not any(n.source == target and n.why == "confirmed" for n in self.notes):
            steps.append((None, M("st_helped", list=L([S(x) for x in helped], conj=True), t=S(target))))
        elif role and not any(r.seat == target for r in self.game.pub.reports):
            steps.append((None, M("st_unverified", t=S(target), role=R(role))))
        return [(1.8 - 0.3 * len(left), steps)]

    def accuse(self, target, max_steps):
        """The best story against `target`, or None (then a one-line reason is used instead)."""
        if max_steps < 2:
            return None
        found = [(w, steps, kind) for kind, shape in (
            ("fulfilled", self.fulfilled), ("targeted", self.targeted), ("clash", self.clashing),
            ("no_vote", self.no_vote), ("outsiders", self.outsiders), ("elimination", self.elimination))
            for w, steps in shape(target)]
        if not found:
            return None
        found.sort(key=lambda x: -x[0])
        weight, steps, _ = found[0]
        # A second, different line of evidence, in a sentence, makes it a real case.
        used = {repr(m) for _, m in steps}
        for _, more, kind in found[1:]:
            if len(steps) >= max_steps:
                break
            short = self.summary(kind, more, target)
            if short is not None and repr(short) not in used:
                steps = steps + [("and", short)]
                break
        steps = steps[:max_steps]
        return Chain(steps) if len(steps) >= 2 else None

    def summary(self, kind, steps, target):
        """One clause standing for a whole story, to add as supporting evidence."""
        if kind == "outsiders":
            return M("st_outsider_short", t=S(target))
        if kind == "targeted":
            first = steps[0][1]
            return M("st_targeted_short", t=S(target), x=first.args["x"])
        if kind == "clash" and len(steps) > 1 and steps[1][0] == "but":
            m = steps[1][1]
            if m.key == "st_clash_me":
                return M("st_clash_short_me", t=S(target))
            if "x" in m.args:
                return M("st_clash_short", t=S(target), x=m.args["x"])
        if kind in ("fulfilled", "no_vote") or kind == "clash":
            return steps[0][1]
        return None

    # --- defence -------------------------------------------------------------------------------

    def defend(self, accuser=None, max_steps=3):
        """What the accused says for themselves, or None."""
        me, g = self.me, self.game
        claims = self.pub.claims or ()
        claim = claims[me] if claims else None
        steps = [(None, M("d_claim", role=R(claim)) if claim else M("d_good"))]
        # An offer to be executed stands.
        if me in g.offered_ever and me in g.nominated_today:
            better = [x for x in g.alive if x != me and self.p.get(x, 0) > self.p.get(me, 0) + 0.1]
            steps = [(None, M("d_offer"))]
            if better:
                steps.append((None, M("d_better", x=S(max(better, key=lambda x: self.p[x])))))
            return Chain(steps)
        if max_steps < 2:
            return None
        for note in self.notes:
            if note.target == me and note.why == "confirmed" and note.source not in (None, me):
                r = next((r for r in self.pub.reports if r.seat == note.source and me in r.data[:-1]), None)
                if r is not None:
                    steps.append(("and", M("d_confirmed", x=S(note.source), n=r.night, role=R(claim))))
                    break
        # The case against me, as the town sees it.
        against = [r for r in g.pub.reports if r.seat != me and _points_at(r, me, g.pub) in ("ft", "ping")]
        pair_other = None
        if against:
            r = against[-1]
            pair_other = next((x for x in r.data[:2] if x != me), None)
            key = "d_split" if r.kind == "fortune_teller" else "d_split_ping"
            steps.append((None, M(key, a=self.who(r.data[0]), b=self.who(r.data[1]), x=S(r.seat))))
            if r.kind == "fortune_teller" and self.agent.profile.story >= 4:
                steps.append((None, M("d_red_herring")))
        outs = [x for x, r in enumerate(claims) if r is not None and KIND[r] == "outsider"]
        if claim and KIND[claim] == "outsider" and len(outs) > SETUP[self.pub.n][1]:
            steps.append((None, M("d_baron")))
        if claim == "undertaker" and not any(d.cause == "execution" for d in g.pub.deaths) and g.day > 1:
            steps.append((None, M("d_no_exec")))
        if claim == "undertaker":
            if pair_other is not None and pair_other in g.alive:
                steps.append((None, M("d_promise_ut", o=S(pair_other))))
            else:
                steps.append((None, M("d_promise_ut_any")))
        elif claim in ("empath", "fortune_teller") and ability(claim).when == "each":
            steps.append((None, M("d_promise")))
        if accuser is not None and accuser != me and len(steps) < max_steps:
            why = self.agent.notebook_reason(g, accuser) if hasattr(self.agent, "notebook_reason") else None
            if why is not None:
                steps.append((None, M("d_counter", x=S(accuser), why=why)))
        steps = steps[:max_steps]
        return Chain(steps) if len(steps) >= 2 else None
