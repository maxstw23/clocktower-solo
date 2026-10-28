"""The game: the Grimoire (truth), the night order and the day procedure.

Simplifications in this version: everyone claims on day 1 and never changes claim, all claimed
information is public, the Imp never star-passes, the Mayor never bounces kills, and the Spy and
Recluse only misregister for information (not for the Slayer or Virgin).
"""
import random
from dataclasses import replace
from itertools import combinations, product

from .agents import PROFILES, REFERENCE, EvilAgent, GoodAgent, believe
from .human import HumanAgent
from .public import Death, Nomination, Public, Report, Shot, Vote, day_tick, night_tick
from .roles import ALL_ROLES, FIRST_NIGHT_INFO, KIND, MINIONS, OUTSIDERS, SETUP, TOWNSFOLK, is_evil, pretty
from .storyteller import Storyteller
from .worlds import RECLUSE_EXTRA, SPY_EXTRA, Solver

NAMES = ("Ada", "Ben", "Cleo", "Dev", "Eli", "Fay", "Gus", "Hana", "Ivo", "Jun", "Kai", "Lea", "Max", "Nia", "Oto")
PING = {"washerwoman": TOWNSFOLK, "librarian": OUTSIDERS, "investigator": MINIONS}
ZERO = (None, None, None)
BLUFF_ORDER = ("washerwoman", "librarian", "investigator", "chef", "undertaker", "empath", "monk",
               "fortune_teller", "soldier", "mayor", "ravenkeeper", "virgin", "slayer")


class Game:
    def __init__(self, players=10, seed=0, mix=("novice", "regular", "veteran"), out=print, check=False,
                 human=None, inp=input, hints=False):
        if players not in SETUP:
            raise ValueError(f"Trouble Brewing supports 5-15 players, not {players}")
        self.n = players
        self.seed = seed
        self.out = out
        self.check = check  # assert the true world is never eliminated (solver soundness)
        self.human = human  # seat played by a person, or None
        self.hints = hints  # show the human a veteran's read of the record each day
        self.rng = random.Random(f"setup-{seed}")
        self.solver = Solver()
        self.st = Storyteller(self.solver, random.Random(f"st-{seed}"))
        self.pub = Public(players)
        self.day = self.night = 0
        self.winner = None
        self.pending = []      # good players' reports, made public at dawn
        self.poisoned = None
        self.executed = None   # executed today
        self.dead = set()
        self.ghosts_used = set()
        self.ever_nominated = set()
        self.butler_master = None
        self.notes = []        # Storyteller's private log
        self.survived = set()  # evil team memory of failed attacks
        self._beliefs = {}
        self.dusk = None       # record frozen at dusk while a night is running
        self.private = []      # what the Storyteller told the human, for their notebook
        self._setup(mix, inp)

    # --- setup -------------------------------------------------------------------------------

    def _setup(self, mix, inp):
        rng = self.rng
        tf, out, mn, _ = SETUP[self.n]
        minions = rng.sample(MINIONS, mn)
        if "baron" in minions:
            tf, out = tf - 2, out + 2
        roles = rng.sample(TOWNSFOLK, tf) + rng.sample(OUTSIDERS, out) + minions + ["imp"]
        rng.shuffle(roles)
        self.roles = roles
        self.start_roles = tuple(roles)
        self.demon = roles.index("imp")
        spare = [r for r in TOWNSFOLK if r not in roles]
        self.drunk_as = rng.choice(spare) if "drunk" in roles else None
        self.perceived = [self.drunk_as if r == "drunk" else r for r in roles]
        self.bluffs = rng.sample([r for r in spare if r != self.drunk_as], 3)
        good = [s for s in range(self.n) if not is_evil(roles[s])]
        self.red_herring = rng.choice(good) if "fortune_teller" in roles else None
        self.team = frozenset(s for s in range(self.n) if is_evil(roles[s]))
        self.agents = []
        for s in range(self.n):
            arng = random.Random(f"agent-{self.seed}-{s}")
            if s in self.team:
                self.agents.append(EvilAgent(s, self.team, PROFILES[rng.choice(mix)], self.n, arng))
                self.agents[-1].survived = self.survived
            else:
                self.agents.append(GoodAgent(s, self.perceived[s], PROFILES[rng.choice(mix)], self.n, arng))
        claims = list(self.perceived)
        bluffs = sorted(self.bluffs, key=BLUFF_ORDER.index)
        if self.human is not None:
            self._seat_human(inp, claims, bluffs)
        # The evil team settles its bluffs on night one; the Demon picks first.
        for s in sorted(self.team - {self.human}, key=lambda s: s != self.demon):
            claims[s] = bluffs.pop(0) if bluffs else rng.choice([r for r in TOWNSFOLK if r not in claims])
        self.planned_claims = tuple(claims)

    def _seat_human(self, inp, claims, bluffs):
        h = self.human
        agent = HumanAgent(h, self.perceived[h], self, inp, self.out or (lambda msg: None))
        self.agents[h] = agent
        self.tell(f"You are {self.name(h)}, seat {h}. Players clockwise: "
                  + ", ".join(self.name(s) for s in range(self.n)) + ".")
        self.tell(f"Your character: {pretty(self.perceived[h])}.")
        if h not in self.team:
            self.tell("You are good. You will claim your character truthfully on day 1.")
            return
        agent.team, agent.survived = self.team, self.survived
        self.tell("You are EVIL. Your team: " + ", ".join(
            f"{self.name(s)} ({pretty(self.roles[s])})" for s in sorted(self.team)) + ".")
        if h == self.demon:
            self.tell("Demon bluffs (good characters not in play): " + ", ".join(pretty(b) for b in self.bluffs) + ".")
        options = bluffs + [r for r in TOWNSFOLK + OUTSIDERS if r not in bluffs and r != "drunk"]
        claims[h] = agent.choose_claim(options)
        if claims[h] in bluffs:
            bluffs.remove(claims[h])

    # --- helpers -----------------------------------------------------------------------------

    @property
    def alive(self):
        return [s for s in range(self.n) if s not in self.dead]

    def name(self, s):
        return NAMES[s]

    def say(self, msg=""):
        if self.out:
            self.out(msg)

    def tell(self, msg):
        """Private message to the human player."""
        if self.human is not None:
            self.say(f"  (private) {msg}")
            when = f"Night {self.night}" if self.dusk is not None or self.day < self.night else f"Day {self.day}"
            self.private.append(f"{when if self.night else 'Setup'}: {msg}")

    def note(self, msg):
        self.notes.append(f"N{self.night}/D{self.day}: {msg}")

    @property
    def known(self):
        """The record players can act on: at night, only what was public at dusk."""
        return self.dusk or self.pub

    def belief_of(self, agent):
        key = (self.known, agent.seat)
        if key not in self._beliefs:
            self._beliefs[key] = believe(self.solver, self.known, agent.profile, agent.seat)
        return self._beliefs[key]

    def public_belief(self, pub=None, base=None, profile=REFERENCE):
        pub = pub or self.known
        key = (pub, profile.name)
        if key not in self._beliefs:
            self._beliefs[key] = believe(self.solver, pub, profile, base=base)
        return self._beliefs[key]

    def executed_on(self, day):
        return next((d.seat for d in self.pub.deaths if d.cause == "execution" and d.tick == day_tick(day)), None)

    def forecast(self, *extra):
        """The record as it will look at dawn (Storyteller's view)."""
        claims = self.pub.claims or self.planned_claims
        return replace(self.pub, claims=claims, reports=self.pub.reports + tuple(self.pending) + extra)

    def _check(self):
        if self.check and self.winner is None:
            assert self.start_roles in {w.roles for w in self.solver.worlds(self.pub)}, \
                f"seed {self.seed}: true world eliminated on day {self.day}"

    # --- main loop ---------------------------------------------------------------------------

    def run(self, max_days=12):
        self.say(f"Seed {self.seed}: {self.n} players")
        self._night()
        while self.winner is None and self.day < max_days:
            self._day()
            if self.winner is None:
                self._night()
        self._reveal()
        return self.winner

    def _kill(self, s, cause):
        tick = night_tick(self.night) if cause == "night" else day_tick(self.day)
        alive_before = len(self.alive)
        self.dead.add(s)
        self.pub = replace(self.pub, deaths=self.pub.deaths + (Death(s, tick, cause),))
        if self.roles[s] == "poisoner":
            self.poisoned = None
        if s == self.demon:
            sw = next((x for x in self.alive if self.roles[x] == "scarlet_woman" and self.poisoned != x), None)
            if sw is None or alive_before < 5:
                self.winner = "good"
                return
            self.roles[sw] = "imp"
            self.demon = sw
            self.note(f"Scarlet Woman {self.name(sw)} becomes the Imp")
            if sw == self.human:
                self.tell("The Demon died: you are now the Imp.")
        if cause == "execution" and self.roles[s] == "saint" and self.poisoned != s:
            self.winner = "evil"
            self.say(f"{self.name(s)} was the Saint!")
        elif len(self.alive) <= 2 or set(self.alive) <= self.team:
            self.winner = "evil"

    # --- night -------------------------------------------------------------------------------

    def _night(self):
        self.night += 1
        executed, self.executed = self.executed, None
        self.prev_executed = executed
        self.poisoned = None
        self.dusk = self.pub

        def acting(role):
            return [s for s in self.alive if self.perceived[s] == role]

        for s in self.alive:
            if self.roles[s] == "poisoner":
                self.poisoned = self.agents[s].poison_pick(self)
                self.note(f"Poisoner poisons {self.name(self.poisoned)}")
        if self.night == 1:
            order = FIRST_NIGHT_INFO
        else:
            protect = None
            for s in acting("monk"):
                t = self.agents[s].monk_pick(self)
                self.pending.append(Report(s, self.night, "monk", (t,)))
                if self.roles[s] == "monk" and self.poisoned != s:
                    protect = t
            killed = None
            if self.demon in self.alive and self.poisoned != self.demon:
                t = self.agents[self.demon].kill_pick(self)
                if t == protect or (self.roles[t] == "soldier" and self.poisoned != t):
                    self.note(f"Imp attacks {self.name(t)}, who survives")
                    self.survived.add(t)
                else:
                    self._kill(t, "night")
                    killed = t
            if self.winner:
                return
            if killed is not None and self.perceived[killed] == "ravenkeeper":
                self._info(killed, "ravenkeeper")
            order = ("empath", "fortune_teller") + (("undertaker",) if executed is not None else ())
        for role in order:
            for s in acting(role):
                self._info(s, role, executed)
        for s in self.alive:
            if self.roles[s] == "butler":
                self.butler_master = self.agents[s].butler_pick(self)
        if self.human in self.alive and self.roles[self.human] == "spy":
            self.tell("Spy, the Grimoire: " + ", ".join(
                f"{self.name(s)} {pretty(self.roles[s])}" + (" (poisoned)" if s == self.poisoned else "")
                + (f" (thinks {pretty(self.drunk_as)})" if self.roles[s] == "drunk" else "")
                for s in range(self.n)))

    def _info(self, s, kind, executed=None):
        malf = self.roles[s] == "drunk" or self.poisoned == s
        arg = executed
        if kind == "fortune_teller":
            arg = self.agents[s].ft_pick(self)
        elif kind == "ravenkeeper":
            arg = self.agents[s].rk_pick(self)
        options = [Report(s, self.night, kind, d) for d in self._options(s, kind, malf, arg)]
        report = self.st.choose(self, options)
        self.pending.append(report)
        if s == self.human:
            self.tell("You learn: " + self.describe(report).split(": ", 1)[1])
        if malf:
            why = "drunk" if self.roles[s] == "drunk" else "poisoned"
            self.note(f"{self.name(s)} ({why}) shown: {self.describe(report)}")

    def _registers_as(self, s, pool):
        r = self.roles[s]
        out = {r} & set(pool)
        if r == "spy":
            out |= SPY_EXTRA & set(pool)
        elif r == "recluse":
            out |= RECLUSE_EXTRA & set(pool)
        return out

    def _evil_counts(self, seats, count):
        flex = [s for s in seats if self.roles[s] in ("spy", "recluse")]
        counts = set()
        for flips in product((False, True), repeat=len(flex)):
            evil = {s: is_evil(self.roles[s]) ^ (s in flex and flips[flex.index(s)]) for s in seats}
            counts.add(count(evil))
        return counts

    def _neighbours(self, s):
        alive = set(self.alive) - {s}
        found = []
        for step in (-1, 1):
            x = (s + step) % self.n
            while x not in alive and x != s:
                x = (x + step) % self.n
            if x != s:
                found.append(x)
        return found

    def _options(self, s, kind, malf, arg):
        """Every legal piece of information for this ability right now."""
        n = self.n
        others = [x for x in range(n) if x != s]
        if kind in PING:
            pool = PING[kind]
            if malf:
                opts = [(a, b, r) for a, b in combinations(others, 2) for r in pool]
            else:
                opts = [(min(a, b), max(a, b), r)
                        for a in others for r in sorted(self._registers_as(a, pool)) for b in others if b != a]
            if kind == "librarian" and (malf or not any(
                    KIND[self.roles[x]] == "outsider" and self.roles[x] != "recluse" for x in range(n))):
                opts.append(ZERO)
            return opts
        if kind in ("chef", "empath"):
            if malf:
                return [(c,) for c in range(3 if kind == "empath" else 4)]
            if kind == "chef":
                counts = self._evil_counts(list(range(n)), lambda e: sum(e[i] and e[(i + 1) % n] for i in range(n)))
            else:
                counts = self._evil_counts(self._neighbours(s), lambda e: sum(e.values()))
            return [(c,) for c in sorted(counts)]
        if kind == "fortune_teller":
            a, b = arg
            truth = any(x == self.demon or x == self.red_herring for x in (a, b))
            answers = {truth}
            if malf or any(self.roles[x] == "recluse" for x in (a, b)):
                answers.add(True)
            if malf:
                answers.add(False)
            return [(a, b, y) for y in sorted(answers)]
        # undertaker, ravenkeeper: learn a character
        return [(arg, r) for r in (ALL_ROLES if malf else sorted(self._registers_as(arg, ALL_ROLES)))]

    # --- day ---------------------------------------------------------------------------------

    def _day(self):
        self.day += 1
        self.dusk = None
        self.say(f"\n=== Day {self.day} ===")
        died = [self.name(d.seat) for d in self.pub.deaths if d.tick == night_tick(self.night)]
        self.say("Dawn: " + (", ".join(died) + " died in the night." if died else "nobody died."))
        if self.day == 1:
            self.pub = replace(self.pub, claims=self.planned_claims)
            self.say("Claims: " + ", ".join(f"{self.name(s)} {pretty(c)}" for s, c in enumerate(self.pub.claims)))
        reports = sorted(self.pending + self._evil_reports(), key=lambda r: r.seat)
        self.pending = []
        self.pub = self.pub.plus(*reports)
        for r in reports:
            self.say("  " + self.describe(r))
        self._check()
        self._show_reads()
        self._show_hint()
        self._slayers()
        if self.winner is None:
            self._nominations()
        self._check()

    def _claim_reports(self, kind):
        if self.night == 1:
            return kind in FIRST_NIGHT_INFO
        return kind in ("empath", "fortune_teller", "monk") or (kind == "undertaker" and self.prev_executed is not None)

    def _evil_reports(self):
        """Evil players invent information for their bluffs, choosing what the town will read best."""
        fakes = []
        for s in sorted(self.team):
            kind = self.pub.claims[s]
            if s in self.dead or not self._claim_reports(kind):
                continue
            base = self.pub.plus(*fakes)
            agent = self.agents[s]
            options = [Report(s, self.night, kind, d) for d in self._fake_options(s, kind, agent)]
            if s == self.human:
                if kind == "monk":
                    t = agent.monk_pick(self)
                    options = [Report(s, self.night, kind, (t,))]
                elif kind == "fortune_teller":
                    a, c = agent.ft_pick(self)
                    options = [Report(s, self.night, kind, (a, c, y)) for y in (False, True)]
                if options:
                    fakes.append(options[0] if len(options) == 1 else agent.choose_report(self, options))
                continue
            random.Random(f"lie-{self.seed}-{self.night}-{s}").shuffle(options)
            # Everyone remembers what they said before: drop lies that break their own story.
            before = self._story_cost(s, base)
            kept = [r for r in options if before is None or (self._story_cost(s, base.plus(r), base) or 99) <= before]
            options = (kept or options)[:agent.profile.lookahead]
            if options:
                fakes.append(min(options, key=lambda r: agent.exposure(self, base.plus(r), base)))
        return fakes

    def _story_cost(self, s, pub, base=None):
        """Fewest excuses under which `s` could be the sober good player they claim to be."""
        return min((w.excuses for w in self.solver.worlds(pub, base=base) if w.roles[s] == pub.claims[s]),
                   default=None)

    def _fake_options(self, s, kind, agent):
        rng = random.Random(f"fake-{self.seed}-{self.night}-{s}")
        claims = self.pub.claims
        others = [x for x in range(self.n) if x != s]

        def pair(a):
            b = rng.choice([x for x in others if x != a])
            return min(a, b), max(a, b)

        if kind in PING:
            pool = PING[kind]
            opts = [(*pair(a), claims[a]) for a in others if claims[a] in pool]  # "confirm" someone
            framing = [r for r in pool if r != kind]
            opts += [(*pair(a), rng.choice(framing)) for a in rng.sample(others, 4)]  # or frame someone
            if kind == "librarian":
                opts.append(ZERO)
            return opts
        if kind in ("chef", "empath"):
            return [(c,) for c in range(3)]
        if kind == "fortune_teller":
            pairs = rng.sample(list(combinations(others, 2)), 4)
            return [(a, b, y) for a, b in pairs for y in (False, True)]
        if kind == "undertaker":
            x = self.prev_executed
            return [(x, claims[x])] + [(x, r) for r in rng.sample(MINIONS, 2)]
        if kind == "monk":
            alive = [x for x in self.alive if x != s]
            return [(x,) for x in rng.sample(alive, min(3, len(alive)))]
        return []

    def _show_hint(self):
        if not self.hints or self.human in self.dead:
            return
        agent = self.agents[self.human]
        seat = None if self.human in self.team else self.human
        b = self.public_belief() if seat is None else believe(self.solver, self.pub, agent.profile, seat)
        top = sorted((s for s in self.alive if s != self.human), key=lambda s: -b.suspicion(s))[:4]
        self.tell(f"Hint ({b.count} possible worlds): most suspicious "
                  + ", ".join(f"{self.name(s)} {b.suspicion(s)}" for s in top))

    def _show_reads(self):
        if not self.out or self.human is not None:
            return
        b = self.public_belief()
        top = sorted(self.alive, key=lambda s: -b.suspicion(s))[:3]
        self.say(f"  [town read: {b.total} worlds, ~{b.candidates():.1f} Demon candidates "
                 f"(Storyteller target {self.st.target(self):.1f}); most suspected: "
                 + ", ".join(f"{self.name(s)} {b.suspicion(s)}" for s in top) + "]")
        reads = []
        for s in self.alive:
            ag = self.agents[s]
            if s in self.team:
                continue
            pb = self.belief_of(ag)
            t = ag.rank([x for x in self.alive if x != s], lambda x: -pb.suspicion(x))[0]
            reads.append(f"{self.name(s)}({ag.profile.name[0]}{'!' if pb.relaxed else ''})→{self.name(t)} {pb.suspicion(t)}")
        self.say("  [reads: " + ", ".join(reads) + "]")

    def _slayers(self):
        for s in self.alive:
            ag = self.agents[s]
            if self.perceived[s] != "slayer" or s in self.team or ag.slayer_used or s in self.dead:
                continue
            t = ag.slayer_pick(self)
            if t is None:
                continue
            ag.slayer_used = True
            hit = self.roles[s] == "slayer" and self.poisoned != s and t == self.demon
            self.say(f"{self.name(s)} uses the Slayer shot on {self.name(t)}: " + ("they die!" if hit else "nothing happens."))
            self.pub = replace(self.pub, shots=self.pub.shots + (Shot(self.day, s, t, hit),))
            if hit:
                self._kill(t, "slayer")
            if self.winner:
                return

    def _nominations(self):
        nominated, nominators = set(), set()
        best, block, tie = 0, None, False
        k = self.day % self.n
        order = list(range(k, self.n)) + list(range(k))
        progress = True
        while progress:
            progress = False
            for s in order:
                if s in self.dead or s in nominators:
                    continue
                t = self.agents[s].nominate(self, nominated)
                if t is None:
                    continue
                progress = True
                nominators.add(s)
                nominated.add(t)
                if self._virgin(s, t):
                    return
                self.say(f"{self.name(s)} nominates {self.name(t)}.")
                needed = max((len(self.alive) + 1) // 2, best + 1)
                voters = self._vote(t, needed, None if tie else block)
                self.pub = replace(self.pub, votes=self.pub.votes + (Vote(self.day, s, t, tuple(voters)),))
                self.say(f"  {len(voters)} vote(s)" + (f": {', '.join(self.name(v) for v in voters)}" if voters else ""))
                if len(voters) >= (len(self.alive) + 1) // 2:
                    if len(voters) > best:
                        best, block, tie = len(voters), t, False
                    elif len(voters) == best:
                        tie = True
        if block is not None and not tie:
            self.say(f"{self.name(block)} is executed.")
            self.executed = block
            self._kill(block, "execution")
        else:
            self.say("No execution today.")
            if len(self.alive) == 3 and any(self.roles[s] == "mayor" and self.poisoned != s for s in self.alive):
                self.say("Three players remain with no execution: the Mayor wins it for good!")
                self.winner = "good"

    def _virgin(self, s, t):
        if t in self.ever_nominated:
            return False
        self.ever_nominated.add(t)
        triggered = self.roles[t] == "virgin" and self.poisoned != t and KIND[self.roles[s]] == "townsfolk"
        self.pub = replace(self.pub, first_noms=self.pub.first_noms + (Nomination(self.day, s, t, triggered),))
        if triggered:
            self.say(f"{self.name(s)} nominates {self.name(t)}: the Virgin's power triggers and {self.name(s)} is executed!")
            self.executed = s
            self._kill(s, "execution")
        return triggered

    def _vote(self, t, needed, block):
        voters = []
        for i in range(1, self.n + 1):
            v = (t + i) % self.n
            ghost = v in self.dead
            if ghost and v in self.ghosts_used:
                continue
            if self.roles[v] == "butler" and not ghost and self.butler_master not in voters:
                continue
            if self.agents[v].vote(self, t, len(voters), needed, block, ghost):
                voters.append(v)
                if ghost:
                    self.ghosts_used.add(v)
        return voters

    # --- presentation ------------------------------------------------------------------------

    def describe(self, r):
        nm = self.name
        d = r.data
        if r.kind in PING:
            text = "there are no Outsiders" if d == ZERO else f"one of {nm(d[0])}/{nm(d[1])} is the {pretty(d[2])}"
        elif r.kind == "chef":
            text = f"{d[0]} pair(s) of evil neighbours"
        elif r.kind == "empath":
            text = f"{d[0]} evil neighbour(s)"
        elif r.kind == "fortune_teller":
            text = f"{nm(d[0])} or {nm(d[1])} the Demon? {'YES' if d[2] else 'no'}"
        elif r.kind == "monk":
            text = f"protected {nm(d[0])}"
        else:
            text = f"{nm(d[0])} {'was' if r.kind == 'undertaker' else 'is'} the {pretty(d[1])}"
        return f"N{r.night} {nm(r.seat)} ({pretty(r.kind)}): {text}"

    def notebook(self):
        """The whole public record, in order, plus what the Storyteller told the human."""
        pub, nm = self.pub, self.name
        lines = ["--- Notebook ---"]
        if pub.claims:
            lines.append("Claims: " + ", ".join(f"{nm(s)} {pretty(c)}" for s, c in enumerate(pub.claims)))
        for n in range(1, self.night + 1):
            died = [nm(d.seat) for d in pub.deaths if d.tick == night_tick(n)]
            lines.append(f"Night {n}: " + (", ".join(died) + " died." if died else "no deaths."))
            lines += ["  " + self.describe(r) for r in pub.reports if r.night == n]
            if n > self.day:
                continue
            lines.append(f"Day {n}:")
            for sh in pub.shots:
                if sh.day == n:
                    lines.append(f"  {nm(sh.shooter)} shot {nm(sh.target)}: " + ("died" if sh.killed else "nothing"))
            for fn in pub.first_noms:
                if fn.day == n and fn.triggered:
                    lines.append(f"  {nm(fn.nominator)} nominated {nm(fn.nominee)}: Virgin triggered, {nm(fn.nominator)} executed")
            for v in pub.votes:
                if v.day == n:
                    lines.append(f"  {nm(v.nominator)} -> {nm(v.nominee)}: {len(v.voters)} vote(s)"
                                 + (f" ({', '.join(nm(x) for x in v.voters)})" if v.voters else ""))
            ex = self.executed_on(n)
            lines.append(f"  Executed: {nm(ex)}" if ex is not None else "  No execution.")
        dead = sorted(self.dead)
        lines.append("Dead: " + (", ".join(nm(s) + (" (ghost vote used)" if s in self.ghosts_used else "")
                                           for s in dead) or "nobody"))
        if self.private:
            lines.append("Told to you privately:")
            lines += ["  " + p for p in self.private]
        return lines

    def _reveal(self):
        self.say(f"\n*** {(self.winner or 'nobody (day limit)').upper()} WINS after {self.day} day(s) ***")
        self.say("Grimoire:")
        for s, r in enumerate(self.start_roles):
            extra = f" (thought they were the {pretty(self.drunk_as)})" if r == "drunk" else ""
            extra += " [red herring]" if s == self.red_herring else ""
            prof = self.agents[s].profile
            who = "[you" if s == self.human else f"[{prof.name}"
            who += ", evil]" if s in self.team else "]"
            self.say(f"  {self.name(s):5} {pretty(r)}{extra} {who}{' (dead)' if s in self.dead else ''}")
        self.say("Demon bluffs: " + ", ".join(pretty(b) for b in self.bluffs))
        self.say("Storyteller notes:")
        for line in self.notes:
            self.say("  " + line)
