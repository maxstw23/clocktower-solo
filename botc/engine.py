"""The game: the Grimoire (truth), the night order and the day procedure.

A day runs: dawn, then a discussion round in which every player speaks once (claims, shares what
their ability told them, says whom they suspect), then nominations, each with a stated reason, a
defence and a vote.

Simplifications in this version: the Imp never star-passes, the Mayor never bounces kills, and the
Spy and Recluse only misregister for information (not for the Slayer or Virgin).
"""
import random
from dataclasses import replace
from itertools import combinations, product

from .agents import PROFILES, REFERENCE, EvilAgent, GoodAgent, believe
from .human import HumanAgent, TerminalIO
from .public import Death, Nomination, Public, Report, Shot, Vote, Whisper, day_tick, night_tick
from .roles import ALL_ROLES, FIRST_NIGHT_INFO, KIND, MINIONS, OUTSIDERS, SETUP, TOWNSFOLK, WILD, is_evil, pretty
from .storyteller import Storyteller
from .worlds import RECLUSE_EXTRA, SPY_EXTRA, Solver

NAMES = ("Ada", "Ben", "Cleo", "Dev", "Eli", "Fay", "Gus", "Hana", "Ivo", "Jun", "Kai", "Lea", "Max", "Nia", "Oto")
PING = {"washerwoman": TOWNSFOLK, "librarian": OUTSIDERS, "investigator": MINIONS}
ZERO = (None, None, None)
BLUFF_ORDER = ("washerwoman", "librarian", "investigator", "chef", "undertaker", "empath", "monk",
               "fortune_teller", "soldier", "mayor", "ravenkeeper", "virgin", "slayer")


class Game:
    def __init__(self, players=10, seed=0, mix=("novice", "regular", "veteran"), out=print, check=False,
                 human=None, io=None, hints=False, name=None):
        if players not in SETUP:
            raise ValueError(f"Trouble Brewing supports 5-15 players, not {players}")
        self.n = players
        self.seed = seed
        self.out = out
        self.check = check  # assert the true world is never eliminated (solver soundness)
        self.human = human  # seat played by a person, or None
        self.hints = hints  # show the human a veteran's read of the record each day
        self.names = list(NAMES[:players])
        if human is not None and name:
            self.names = [n for n in NAMES if n.lower() != name.lower()][:players]
            self.names[human] = name
        self.log = []          # (text, private, chat) for every line said, in order
        self.whispers = []     # everything said in private groups
        self.claim_seq = {}    # seat -> order number of their latest public claim
        self._seq = 0
        self.phase = "setup"
        self.rng = random.Random(f"setup-{seed}")
        self.solver = Solver()
        self.st = Storyteller(self.solver, random.Random(f"st-{seed}"))
        self.pub = Public(players)
        self.day = self.night = 0
        self.winner = None
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
        self._setup(mix, io)

    # --- setup -------------------------------------------------------------------------------

    def _setup(self, mix, io):
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
        # What each player intends to claim on day 1 (also the Storyteller's forecast).
        claims = [a.cover or a.role if s not in self.team else None for s, a in enumerate(self.agents)]
        bluffs = sorted(self.bluffs, key=BLUFF_ORDER.index)
        # The evil team settles its bluffs on night one; the Demon picks first.
        for s in sorted(self.team, key=lambda s: s != self.demon):
            claims[s] = bluffs.pop(0) if bluffs else rng.choice([r for r in TOWNSFOLK if r not in claims])
        self.planned_claims = tuple(claims)
        if self.human is not None:
            self._seat_human(io)

    def _seat_human(self, io):
        h = self.human
        io = io or TerminalIO(out=self.out or (lambda msg: None))
        agent = HumanAgent(h, self.perceived[h], self, io)
        self.agents[h] = agent
        self.tell(f"You are {self.name(h)}. Players clockwise: " + ", ".join(self.name(s) for s in range(self.n)) + ".")
        self.tell(f"Your character: {pretty(self.perceived[h])}.")
        if h not in self.team:
            self.tell("You are good. You may claim your character truthfully, bluff, or keep quiet; "
                      "but if you change your claim later, people will trust you less.")
            return
        agent.team, agent.survived = self.team, self.survived
        self.tell("You are EVIL. Your team: " + ", ".join(
            f"{self.name(s)} ({pretty(self.roles[s])})" for s in sorted(self.team)) + ".")
        if h == self.demon:
            self.tell("Demon bluffs (good characters not in play): " + ", ".join(pretty(b) for b in self.bluffs) + ".")
        mates = [s for s in self.team if s != h]
        self.tell("Your teammates plan to claim: " + ", ".join(
            f"{self.name(s)} as {pretty(self.planned_claims[s])}" for s in mates) + ".")

    # --- helpers -----------------------------------------------------------------------------

    @property
    def alive(self):
        return [s for s in range(self.n) if s not in self.dead]

    def name(self, s):
        return self.names[s]

    def say(self, msg="", private=False, chat=False):
        """`private`: only the human sees it. `chat`: said in a private group the human is in."""
        self.log.append((msg, private, chat))
        if self.out:
            self.out(f"  (in private) {msg}" if chat else f"  (private) {msg}" if private else msg)

    def tell(self, msg):
        """Private message to the human player."""
        if self.human is not None:
            self.say(msg, private=True)
            when = f"Night {self.night}" if self.dusk is not None or self.day < self.night else f"Day {self.day}"
            self.private.append(f"{when if self.night else 'Setup'}: {msg}")

    def note(self, msg):
        self.notes.append(f"N{self.night}/D{self.day}: {msg}")

    @property
    def known(self):
        """The record players can act on: at night, only what was public at dusk."""
        return self.dusk or self.pub

    def record_for(self, seat):
        """What this player has heard: the public record plus their private conversations."""
        view = self.known
        heard = [w for w in self.whispers if seat in w.group]
        if not heard or not view.claims:
            return view
        claims = list(view.claims)
        for w in heard:
            if w.claim and w.seq > self.claim_seq.get(w.speaker, -1):
                claims[w.speaker] = w.claim
        extra = tuple(dict.fromkeys(w.report for w in heard if w.report and w.report not in view.reports))
        return replace(view, claims=tuple(claims), reports=view.reports + extra)

    def view_of(self, agent):
        """What this good player knows: what they've heard, their real character and unshared info."""
        view = self.record_for(agent.seat)
        if not view.claims or not hasattr(agent, "role"):
            return view
        claims = list(view.claims)
        claims[agent.seat] = agent.role
        return replace(view, claims=tuple(claims)).plus(*agent.inbox)

    def belief_of(self, agent):
        view = replace(self.view_of(agent), votes=())  # votes don't change which worlds are possible
        key = (view, agent.seat)
        if key not in self._beliefs:
            self._beliefs[key] = believe(self.solver, view, agent.profile, agent.seat)
        return self._beliefs[key]

    def public_belief(self, pub=None, base=None, profile=REFERENCE):
        pub = replace(pub or self.known, votes=())
        key = (pub, profile.name)
        if key not in self._beliefs:
            self._beliefs[key] = believe(self.solver, pub, profile, base=base)
        return self._beliefs[key]

    def executed_on(self, day):
        return next((d.seat for d in self.pub.deaths if d.cause == "execution" and d.tick == day_tick(day)), None)

    @property
    def pending(self):
        """Info good players hold but haven't shared yet."""
        return [r for a in self.agents for r in a.inbox]

    def forecast(self, *extra):
        """The record as it will look once held info is shared (Storyteller's view)."""
        claims = tuple(c if c is not None else p
                       for c, p in zip(self.pub.claims or self.planned_claims, self.planned_claims))
        return replace(self.pub, claims=claims, reports=self.pub.reports + tuple(self.pending) + extra)

    def _bluffing(self):
        """Good players whose current claim isn't what they believe they are."""
        claims = self.pub.claims or ()
        return [s for s, c in enumerate(claims) if c is not None and s not in self.team and c != self.perceived[s]]

    def _matches_truth(self, world):
        for s, (truth, r) in enumerate(zip(self.start_roles, world.roles)):
            if r == truth or (r in WILD and not is_evil(truth) and KIND[r] == KIND[truth]):
                continue
            if s in self._bluffing() and r == self.pub.claims[s]:
                continue  # a bluff that left no trace is believed
            return False
        return True

    def _check(self):
        # Sound up to the solver's documented limit of one undetected good bluff at a time.
        if self.check and self.winner is None and len(self._bluffing()) <= 1:
            assert any(self._matches_truth(w) for w in self.solver.worlds(self.pub)), \
                f"seed {self.seed}: true world eliminated on day {self.day}"

    # --- main loop ---------------------------------------------------------------------------

    def run(self, max_days=12):
        self.say(f"Game #{self.seed}: {self.n} players.")
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
        self.phase = "night"
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
                self.agents[s].inbox.append(Report(s, self.night, "monk", (t,)))
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
        self.agents[s].inbox.append(report)
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
        self.phase = "dawn"
        self.say(f"\n=== Day {self.day} ===")
        died = [self.name(d.seat) for d in self.pub.deaths if d.tick == night_tick(self.night)]
        self.say("Dawn: " + (", ".join(died) + " died in the night." if died else "nobody died."))
        self._show_hint()
        k = self.day % self.n
        order = [(k + i) % self.n for i in range(self.n)]
        if self.day == 1:
            self.phase = "introductions"
            self.say("Introductions: everyone says who they are.")
            for s in order:
                self._introduce(s)
        self._private_chats(order)
        self.phase = "discussion"
        self.say("Discussion: everyone speaks once, in turn.")
        for s in order:
            self._speak(s)
            if self.winner:
                return
        self._check()
        self._show_reads()
        self.phase = "nominations"
        self._nominations()
        self._check()

    # --- speaking ------------------------------------------------------------------------------

    def _claim(self, s, role):
        before = self.pub.claims[s] if self.pub.claims else None
        if role == before:
            return
        self.pub = self.pub.claim(self.day, s, role)
        self._seq += 1
        self.claim_seq[s] = self._seq
        if before is None:
            self.say(f'{self.name(s)}: "I am the {pretty(role)}."')
        else:
            self.say(f'{self.name(s)}: "I wasn\'t telling the truth. I\'m not the {pretty(before)}, '
                     f'I\'m the {pretty(role)}."')

    def _publish(self, *reports):
        self.pub = self.pub.plus(*reports)
        for r in reports:
            self.say(f'{self.name(r.seat)}: "Night {r.night}, my {pretty(r.kind)} ability: {self._info_text(r)}."')

    def _info_nights(self, s, kind, include_reported=False):
        """Nights on which a `kind` would have had info that this player hasn't reported yet."""
        if kind in ("empath", "fortune_teller"):
            nights = range(1, self.night + 1)
        elif kind in FIRST_NIGHT_INFO:
            nights = [1]
        elif kind == "monk":
            nights = range(2, self.night + 1)
        elif kind == "undertaker":
            nights = [n for n in range(2, self.night + 1) if self.executed_on(n - 1) is not None]
        elif kind == "ravenkeeper":
            nights = [(d.tick + 1) // 2 for d in self.pub.deaths if d.seat == s and d.cause == "night"]
        else:
            return []
        died = next((d.tick for d in self.pub.deaths if d.seat == s), None)
        done = set() if include_reported else {r.night for r in self.pub.reports if r.seat == s and r.kind == kind}
        return [n for n in nights if n <= self.night and n not in done
                and (kind == "ravenkeeper" or died is None or died > night_tick(n))]

    # --- private conversations ------------------------------------------------------------------

    def _private_chats(self, order):
        """Players step aside in small groups. Each player is in at most one group a day."""
        self.phase = "private chats"
        self.say("Private conversations: players may step aside in small groups.")
        busy = set()
        for s in order:
            if s in busy:
                continue
            free = [x for x in self.alive if x != s and x not in busy]
            invited = self.agents[s].invite(self, free) if free else []
            if not invited:
                continue
            joined = [x for x in invited if self.agents[x].accept(self, s, invited)]
            declined = [x for x in invited if x not in joined]
            if s == self.human and declined:
                self.tell(", ".join(self.name(x) for x in declined) + " declined to talk with you.")
            if not joined:
                continue
            group = tuple(sorted([s, *joined]))
            busy.update(group)
            self._chat(group)

    def _whisper(self, s, group, claim=None, report=None, text=None):
        self._seq += 1
        if claim or report:
            self.whispers.append(Whisper(self.day, group, s, claim, report, self._seq))
        if self.human not in group:
            return
        public = self.pub.claims[s] if self.pub.claims else None
        if claim:
            line = f"Between us: I'm really the {pretty(claim)}." if public and public != claim else f"I'm the {pretty(claim)}."
        elif report:
            line = f"Night {report.night}, my {pretty(report.kind)} ability: {self._info_text(report)}."
        else:
            line = text
        self.say(f'{self.name(s)}: "{line}"', private=True, chat=True)

    def _chat(self, group):
        others = lambda s: ", ".join(self.name(x) for x in group if x != s)
        if self.human in group:
            self.say(f"You step aside with {others(self.human)}.", private=True, chat=True)
        else:
            self.say(", ".join(self.name(x) for x in group[:-1]) + f" and {self.name(group[-1])} step aside to talk privately.")
        for s in group:
            if s == self.human:
                self._human_chat(group)
                continue
            agent = self.agents[s]
            if s not in self.team and self.pub.claims[s] != agent.role:
                # A hidden player confides their real character and info to people they trust.
                self._whisper(s, group, claim=agent.role)
                for r in sorted(agent.inbox, key=lambda r: r.night):
                    self._whisper(s, group, report=r)
            said = agent.statement(self)
            if said:
                self._whisper(s, group, text=f"I suspect {self.name(said[0])}: {said[1]}.")
            else:
                self._whisper(s, group, text="I don't have a strong read on anyone yet.")

    def _human_chat(self, group):
        h = self.human
        io = self.agents[h].io
        listener = next(x for x in group if x != h)
        while True:
            told = self.record_for(listener).claims[h] if self.pub.claims else None
            acts = [("claim", "Tell them your character")]
            if told and self._info_nights(h, told, include_reported=True):
                acts.append(("share", f"Tell them what your {pretty(told)} ability showed you"))
            acts += [("accuse", "Tell them whom you suspect"), ("done", "Done talking")]
            act = acts[io.choose("You're talking privately. What do you say?", [a[1] for a in acts],
                                 default=len(acts) - 1)][0]
            if act == "done":
                return
            if act == "claim":
                self._human_claim(group)
            elif act == "share":
                self._human_share(told, group)
            else:
                t = io.seat("Whom do you suspect?", [s for s in self.alive if s != h])
                if t is not None:
                    self._whisper(h, group, text=f"I suspect {self.name(t)}.")

    def _introduce(self, s):
        if s == self.human:
            agent = self.agents[s]
            if agent.io.choose("Introductions: what do you tell the table?",
                               ["Claim a character", "Stay silent for now"], default=0) == 0:
                self._human_claim()
            return
        agent = self.agents[s]
        self._claim(s, self.planned_claims[s] if s in self.team else agent.claim_now(self))

    def _speak(self, s):
        if s == self.human:
            return self._human_turn()
        agent = self.agents[s]
        if s in self.team:
            if not self.pub.claims or self.pub.claims[s] is None:
                self._claim(s, self.planned_claims[s])
            if s not in self.dead:
                for night in self._info_nights(s, self.pub.claims[s]):
                    fake = self._evil_report(s, night)
                    if fake:
                        self._publish(fake)
        else:
            role = agent.claim_now(self)
            if role:
                self._claim(s, role)
            if self.pub.claims[s] == agent.role and agent.inbox:
                self._publish(*sorted(agent.inbox, key=lambda r: r.night))
                agent.inbox.clear()
            if s not in self.dead and self.perceived[s] == "slayer" and not agent.slayer_used:
                t = agent.slayer_pick(self)
                if t is not None:
                    self._shoot(s, t)
                    if self.winner:
                        return
        said = agent.statement(self)
        if said:
            t, why = said
            self.say(f'{self.name(s)}: "I suspect {self.name(t)}: {why}."')

    def _shoot(self, s, t):
        self.agents[s].slayer_used = True
        hit = self.roles[s] == "slayer" and self.poisoned != s and t == self.demon
        self.say(f'{self.name(s)}: "I\'m the Slayer, and I shoot {self.name(t)}." '
                 + (f"{self.name(t)} dies!" if hit else "Nothing happens."))
        self.pub = replace(self.pub, shots=self.pub.shots + (Shot(self.day, s, t, hit),))
        if hit:
            self._kill(t, "slayer")

    def _evil_report(self, s, night):
        """An evil player invents info for their bluff, choosing what they think the town reads best."""
        kind = self.pub.claims[s]
        agent = self.agents[s]
        base = self.pub
        options = [Report(s, night, kind, d) for d in self._fake_options(s, kind, night)]
        random.Random(f"lie-{self.seed}-{night}-{s}").shuffle(options)
        # Keeping a lie straight is a skill: drop lies that would break the liar's story, judged
        # against their own earlier claims (regular) or the whole record (veteran).
        if agent.profile.story_check:
            view = base if agent.profile.story_check >= 2 else replace(
                base, reports=tuple(r for r in base.reports if r.seat == s))
            before = self._story_cost(s, view)
            kept = [r for r in options
                    if before is None or (self._story_cost(s, view.plus(r), view) or 99) <= before]
            options = kept or options
        options = options[:agent.profile.lookahead]
        return min(options, key=lambda r: agent.exposure(self, base.plus(r), base)) if options else None

    # --- the human's turn ----------------------------------------------------------------------

    def _human_turn(self, defending=False):
        h = self.human
        agent, io = self.agents[h], self.agents[h].io
        while True:
            claim = self.pub.claims[h] if self.pub.claims else None
            acts = [("claim", "Claim a character" if claim is None else f"Change your claim (now: {pretty(claim)})")]
            if claim is not None and self._info_nights(h, claim):
                acts.append(("share", f"Tell what your {pretty(claim)} ability showed you"))
            if h not in self.dead and not defending:
                acts.append(("accuse", "Say whom you suspect"))
                if not agent.slayer_used and "slayer" in (claim, self.perceived[h]):
                    acts.append(("shoot", "Use the Slayer's shot"))
            acts.append(("done", "Done speaking"))
            prompt = "You've been nominated. What do you say?" if defending else "Your turn to speak."
            act = acts[io.choose(prompt, [a[1] for a in acts], default=len(acts) - 1)][0]
            if act == "done":
                return
            if act == "claim":
                self._human_claim()
            elif act == "share":
                self._human_share(claim)
            elif act == "accuse":
                t = io.seat("Whom do you suspect?", [s for s in self.alive if s != h])
                if t is not None:
                    self.say(f'{self.name(h)}: "I suspect {self.name(t)}."')
            elif act == "shoot":
                t = io.seat("Shoot whom?", [s for s in self.alive if s != h])
                if t is not None:
                    self._claim(h, "slayer")
                    self._shoot(h, t)
                    if self.winner:
                        return

    def _human_claim(self, group=None):
        h = self.human
        io = self.agents[h].io
        mine = [] if h in self.team else [self.perceived[h]]
        bluffs = self.bluffs if h == self.demon else []
        first = mine + [b for b in bluffs if b not in mine]
        roles = first + [r for r in TOWNSFOLK + OUTSIDERS if r not in first and r != "drunk"]
        labels = [pretty(r) + (" (your character)" if r in mine else " (Demon bluff)" if r in bluffs else "")
                  for r in roles]
        role = roles[io.choose("Which character do you claim to be?", labels, default=0)]
        if group:
            self._whisper(h, group, claim=role)
        else:
            self._claim(h, role)

    def _human_share(self, kind, group=None):
        h = self.human
        agent, io = self.agents[h], self.agents[h].io
        nights = self._info_nights(h, kind, include_reported=bool(group))
        night = nights[0] if len(nights) == 1 else nights[io.choose(
            "Which night?", [f"Night {n}" for n in nights], default=len(nights) - 1)]
        real = [r for r in agent.inbox if r.kind == kind and r.night == night]
        others = [s for s in range(self.n) if s != h]
        if kind == "fortune_teller":
            default = list(real[0].data[:2]) if real else others[:2]
            a, b = sorted(io.seats(f"Night {night}: which two players did you choose?", others, 2, default))
            yes = io.choose("And the answer you got?", ["no", "YES"], default=int(real[0].data[2]) if real else 0)
            report = Report(h, night, kind, (a, b, bool(yes)))
        elif kind == "monk":
            alive = [s for s in self.alive if s != h]
            t = io.seat(f"Night {night}: whom did you protect?", alive, real[0].data[0] if real else alive[0])
            report = Report(h, night, kind, (t,))
        else:
            opts = list(real) + [Report(h, night, kind, d) for d in self._fake_options(h, kind, night)
                                 if not real or d != real[0].data]
            labels = [self._info_text(r) + (" (what you really learned)" if r in real else "") for r in opts]
            if kind in PING:
                labels.append("Something else...")
            i = io.choose(f"Night {night}: what do you say your {pretty(kind)} ability showed you?", labels, 0)
            if i < len(opts):
                report = opts[i]
            else:
                a, b = sorted(io.seats("Which two players?", others, 2, others[:2]))
                pool = list(PING[kind])
                report = Report(h, night, kind, (a, b, pool[io.choose("As which character?", [pretty(r) for r in pool], 0)]))
        if group:
            self._whisper(h, group, report=report)
            return
        agent.inbox = [r for r in agent.inbox if not (r.kind == kind and r.night == night)]
        self._publish(report)

    def _story_cost(self, s, pub, base=None):
        """Fewest excuses under which `s` could be the sober good player they claim to be."""
        return min((w.excuses for w in self.solver.worlds(pub, base=base) if w.roles[s] == pub.claims[s]),
                   default=None)

    def _fake_options(self, s, kind, night):
        rng = random.Random(f"fake-{self.seed}-{night}-{s}")
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
            return list(dict.fromkeys(opts))
        if kind in ("chef", "empath"):
            return [(c,) for c in range(3)]
        if kind == "fortune_teller":
            pairs = rng.sample(list(combinations(others, 2)), 4)
            return [(a, b, y) for a, b in pairs for y in (False, True)]
        if kind == "undertaker":
            x = self.executed_on(night - 1)
            if x is None:
                return []
            return ([(x, claims[x])] if claims[x] else []) + [(x, r) for r in rng.sample(MINIONS, 2)]
        if kind == "monk":
            alive = [x for x in self.alive if x != s]
            return [(x,) for x in rng.sample(alive, min(3, len(alive)))]
        if kind == "ravenkeeper":
            return [(x, rng.choice(MINIONS + ("imp",))) for x in rng.sample(others, 3)]
        return []

    def _show_hint(self):
        if not self.hints or self.human in self.dead or not self.pub.claims:
            return
        agent = self.agents[self.human]
        b = self.public_belief() if self.human in self.team else self.belief_of(agent)
        top = sorted((s for s in self.alive if s != self.human), key=lambda s: -b.suspicion(s))[:4]
        self.tell(f"Hint ({b.count} possible worlds): most suspicious "
                  + ", ".join(f"{self.name(s)} {b.suspicion(s)}" for s in top))

    def _show_reads(self):
        if not self.out or self.human is not None:
            return
        b = self.public_belief()
        top = sorted(self.alive, key=lambda s: -b.suspicion(s))[:3]
        self.say(f"  [town read: {b.count} worlds, ~{b.candidates():.1f} Demon candidates "
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

    def _nominations(self):
        self.say("Nominations are open.")
        self._show_hint()
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
                agent = self.agents[s]
                if s == self.human:
                    self.say(f"{self.name(s)} nominates {self.name(t)}.")
                else:
                    b = agent.read(self) if s in self.team else self.belief_of(agent)
                    self.say(f'{self.name(s)} nominates {self.name(t)}: "{agent.explain(self, t, b)}."')
                if self._virgin(s, t):
                    return
                self._defend(t)
                majority = (len(self.alive) + 1) // 2
                needed = max(majority, best + 1)
                on_block = None if tie else block
                self.say(f"Vote on {self.name(t)}: {needed} votes needed"
                         + (f" to replace {self.name(on_block)} on the block." if on_block is not None else "."))
                voters = self._vote(t, needed, on_block)
                self.pub = replace(self.pub, votes=self.pub.votes + (Vote(self.day, s, t, tuple(voters)),))
                result = f"{len(voters)} vote(s)" + (f" ({', '.join(self.name(v) for v in voters)})" if voters else "")
                if len(voters) >= majority and len(voters) > best:
                    best, block, tie = len(voters), t, False
                    self.say(f"{result}: {self.name(t)} is about to die.")
                elif len(voters) >= majority and len(voters) == best:
                    tie = True
                    self.say(f"{result}: a tie, so nobody is about to die.")
                else:
                    self.say(f"{result}: not enough.")
        if block is not None and not tie:
            self.say(f"{self.name(block)} is executed.")
            self.executed = block
            self._kill(block, "execution")
        else:
            self.say("No execution today.")
            if len(self.alive) == 3 and any(self.roles[s] == "mayor" and self.poisoned != s for s in self.alive):
                self.say("Three players remain with no execution: the Mayor wins it for good!")
                self.winner = "good"

    def _defend(self, t):
        """The nominee speaks before the vote."""
        if t == self.human:
            self._human_turn(defending=True)
            return
        agent = self.agents[t]
        if t not in self.team:
            role = agent.claim_now(self, pressed=True)
            if role:
                self._claim(t, role)
            if self.pub.claims[t] == agent.role and agent.inbox:
                self._publish(*sorted(agent.inbox, key=lambda r: r.night))
                agent.inbox.clear()
        claim = self.pub.claims[t]
        self.say(f'{self.name(t)}: "I\'m good' + (f", I\'m the {pretty(claim)}" if claim else "") + '."')

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
        return f"N{r.night} {self.name(r.seat)} ({pretty(r.kind)}): {self._info_text(r)}"

    def _info_text(self, r):
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
        return text

    def notebook(self):
        """The whole public record, in order, plus what the Storyteller told the human."""
        pub, nm = self.pub, self.name
        lines = ["--- Notebook ---"]
        if pub.claims:
            lines.append("Current claims: " + ", ".join(
                f"{nm(s)} {pretty(c) if c else '(silent)'}" for s, c in enumerate(pub.claims)))
        for n in range(1, self.night + 1):
            died = [nm(d.seat) for d in pub.deaths if d.tick == night_tick(n)]
            lines.append(f"Night {n}: " + (", ".join(died) + " died." if died else "no deaths."))
            lines += ["  " + self.describe(r) for r in pub.reports if r.night == n]
            if n > self.day:
                continue
            lines.append(f"Day {n}:")
            said = {}
            for c in pub.claim_log:
                if c.day == n:
                    old = said.get(c.seat) or next((x.role for x in reversed(pub.claim_log)
                                                    if x.seat == c.seat and x.day < n), None)
                    lines.append(f"  {nm(c.seat)} claimed {pretty(c.role)}"
                                 + (f" (changed from {pretty(old)})" if old and old != c.role else ""))
                    said[c.seat] = c.role
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
        if self.human is not None:
            chats = [w for w in self.whispers if self.human in w.group]
            if chats:
                lines.append("Your private conversations:")
            for w in chats:
                with_ = ", ".join(nm(x) for x in w.group if x != self.human)
                said = f"claimed {pretty(w.claim)}" if w.claim else self.describe(w.report)
                lines.append(f"  Day {w.day} (with {with_}): {nm(w.speaker)} {said}")
        if self.private:
            lines.append("Told to you privately:")
            lines += ["  " + p for p in self.private]
        return lines

    def _reveal(self):
        self.phase = "over"
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
