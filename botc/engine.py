"""The game: the Grimoire (truth), the night order and the day procedure.

A day runs: dawn, then a discussion round in which every player speaks once (claims, shares what
their ability told them, says whom they suspect), then nominations, each with a stated reason, a
defence and a vote.

Simplifications in this version: the Imp never star-passes, the Mayor never bounces kills, and the
Spy and Recluse only misregister for information (not for the Slayer or Virgin).
"""
import asyncio
import inspect
import random
from dataclasses import replace
from itertools import combinations, product

from .agents import PROFILES, REFERENCE, EvilAgent, GoodAgent, believe
from .human import HumanAgent, TerminalIO
from .i18n import AbilityText, L, M, R, S, render
from .public import Death, Nomination, Public, Report, Shot, Vote, Whisper, day_tick, night_tick
from .agents import SPENT
from .roles import ALL_ROLES, FIRST_NIGHT_INFO, KIND, MINIONS, OUTSIDERS, SETUP, TOWNSFOLK, WILD, is_evil
from .storyteller import Storyteller
from .worlds import RECLUSE_EXTRA, SPY_EXTRA, Solver

NAMES = ("Ada", "Ben", "Cleo", "Dev", "Eli", "Fay", "Gus", "Hana", "Ivo", "Jun", "Kai", "Lea", "Max", "Nia", "Oto")
NAMES_ZH = ("安娜", "博文", "晨曦", "大伟", "恩泽", "芳芳", "国栋", "海燕", "一鸣", "俊杰", "凯文", "丽娜", "明轩", "妮妮", "欧阳")
PING = {"washerwoman": TOWNSFOLK, "librarian": OUTSIDERS, "investigator": MINIONS}
ZERO = (None, None, None)
BLUFF_ORDER = ("washerwoman", "librarian", "investigator", "chef", "undertaker", "empath", "monk",
               "fortune_teller", "soldier", "mayor", "ravenkeeper", "virgin", "slayer")


class Game:
    def __init__(self, players=10, seed=0, mix=("novice", "regular", "veteran"), out=print, check=False,
                 human=None, io=None, hints=False, name=None, lang="en", pace=None, step=None):
        if players not in SETUP:
            raise ValueError(f"Trouble Brewing supports 5-15 players, not {players}")
        self.n = players
        self.seed = seed
        self.out = out
        self.check = check  # assert the true world is never eliminated (solver soundness)
        self.human = human  # seat played by a person, or None
        self.hints = hints  # show the human a veteran's read of the record each day
        pool = NAMES_ZH if lang == "zh" else NAMES
        self.names = list(pool[:players])
        if human is not None and name:
            self.names = [n for n in pool if n.lower() != name.lower()][:players]
            self.names[human] = name
        self.lang = lang       # language for `out` (the web page renders in the reader's language)
        self.pace = pace       # pace(kind, chars) -> seconds a line stays before the next (web play)
        self.step = step       # step() -> True: wait for the human to tap after each line
        self.speaking = None   # seat currently speaking, while paced
        self.log = []          # every line said, in order: dicts with m, private, chat, speaker
        self.on_block = None   # who is about to be executed while nominations go round
        self.suggest = {}      # evil human's suggestions to AI teammates: "kill"/"poison" -> seat
        self.replied = set()   # (day, seat): already answered an accusation today
        self.countered = set()  # (real holder, false claimer): already called out
        self.virgin_plan = None    # (tester, virgin) agreed for today's first nomination
        self.virgin_planned = set()  # claimed Virgins someone already proposed testing
        self.offers = []           # players who offered today to be executed if there's no better choice
        self.offered_ever = set()  # an AI player makes that offer once per game
        self.votes_left = 0        # during a vote: how many hands are still to come
        self.volunteer = None      # whose offer was taken up
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
        self.human_bluff = None  # a bluff the Demon will hand a human Minion
        self.bluff_given = False
        if self.human in self.team and self.human != self.demon and len(bluffs) > 1:
            self.human_bluff = bluffs.pop(1)
            claims[self.human] = self.human_bluff
        # The evil team settles its bluffs on night one; the Demon picks first.
        for s in sorted(self.team - {self.human} if self.human_bluff else self.team, key=lambda s: s != self.demon):
            claims[s] = bluffs.pop(0) if bluffs else rng.choice([r for r in TOWNSFOLK if r not in claims])
        self.planned_claims = tuple(claims)
        if self.human is not None:
            self._seat_human(io)

    def _seat_human(self, io):
        h = self.human
        io = io or TerminalIO(out=self.out or (lambda msg: None))
        self.agents[h] = HumanAgent(h, self.perceived[h], self, io)

    async def _welcome(self):
        h = self.human
        agent = self.agents[h]
        await self.tell(M("you_are", me=S(h), players=L(S(s) for s in range(self.n))))
        await self.tell(M("your_char", role=R(self.perceived[h]), ability=AbilityText(self.perceived[h])))
        if h not in self.team:
            await self.tell(M("you_good"))
            return
        agent.team, agent.survived = self.team, self.survived
        await self.tell(M("you_evil", team=L(M("seat_role", p=S(s), role=R(self.roles[s])) for s in sorted(self.team))))
        if h == self.demon:
            await self.tell(M("bluffs", roles=L(R(b) for b in self.bluffs)))
        mates = [s for s in self.team if s != h]
        await self.tell(M("mates_claim", list=L(M("as", p=S(s), role=R(self.planned_claims[s])) for s in mates)))

    # --- helpers -----------------------------------------------------------------------------

    @property
    def alive(self):
        return [s for s in range(self.n) if s not in self.dead]

    def name(self, s):
        return self.names[s]

    @staticmethod
    async def ask(answer):
        """A player's decision: an AI answers at once, the human's answer is awaited."""
        return await answer if inspect.isawaitable(answer) else answer

    def play(self, max_days=12):
        """Run the whole game synchronously (simulations, tests, terminal play)."""
        return asyncio.run(self.run(max_days))

    def m(self, key, **args):
        """A message with a phrasing picked by seed (some keys have several ways to say them)."""
        return M(key, v=(self.seed * 7 + len(self.log) * 13) % 97, **args)

    def text(self, m, lang=None):
        return render(m, lang or self.lang, self.names)

    async def say(self, m, private=False, chat=False, speaker=None):
        """`private`: only the human sees it. `chat`: said in a private group the human is in."""
        kind = "speech" if speaker is not None else "private" if private else "event"
        if self.pace and speaker is not None:
            self.speaking = speaker  # a moment of "speaking…" before the words appear
            await asyncio.sleep(self.pace("lead", 0))
        self.log.append({"m": m, "private": private, "chat": chat, "speaker": speaker, "day": self.day})
        if self.out:
            text = self.text(m)
            self.out(f"  (in private) {text}" if chat else f"  (private) {text}" if private else text)
        if self.human is not None and self.step and self.step() and speaker is not None and speaker != self.human:
            await self.agents[self.human].io.next()
        elif self.pace:
            await asyncio.sleep(self.pace(kind, len(self.text(m))))  # time to read it
        self.speaking = None

    async def beat(self, title, body=None):
        """A moment the human must not miss (a phase change, a death): show it as a card."""
        if self.human is not None:
            await self.agents[self.human].io.ack(title, body)

    async def speech(self, s, msg, private=False, chat=False):
        await self.say(M("speech", p=S(s), text=msg), private=private, chat=chat, speaker=s)

    async def tell(self, msg):
        """Private message to the human player."""
        if self.human is not None:
            await self.say(msg, private=True)
            when = (M("when_night", n=self.night) if self.dusk is not None or self.day < self.night
                    else M("when_day", n=self.day)) if self.night else M("when_setup")
            self.private.append(M("nb_private", when=when, msg=msg))

    def note(self, msg):
        self.notes.append(M("note_line", n=self.night, d=self.day, msg=msg))

    @property
    def known(self):
        """The record players can act on: at night, only what was public at dusk."""
        return self.dusk or self.pub

    def record_for(self, seat):
        """What this player has heard: the public record plus their private conversations."""
        view = self.known
        heard = [w for w in self.whispers if seat in w.group]
        if not heard:
            return view
        claims = list(view.claims or (None,) * self.n)
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

    def silent_nights(self, s):
        """Past nights of info that s's public character should have given them, still unshared."""
        claims = self.known.claims
        if not claims or claims[s] is None or s in self.dead:
            return []
        return [n for n in self._info_nights(s, claims[s]) if n < self.night]

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

    async def run(self, max_days=12):
        if self.human is not None:
            await self._welcome()
        await self.say(M("game_start", seed=self.seed, n=self.n))
        await self._night()
        while self.winner is None and self.day < max_days:
            await self._day()
            if self.winner is None:
                await self._night()
        await self._reveal()
        return self.winner

    async def _kill(self, s, cause):
        tick = night_tick(self.night) if cause == "night" else day_tick(self.day)
        alive_before = len(self.alive)
        self.dead.add(s)
        self.pub = replace(self.pub, deaths=self.pub.deaths + (Death(s, tick, cause),))
        if self.roles[s] == "poisoner":
            self.poisoned = None
        if s == self.demon:
            minions = [x for x in self.alive if KIND[self.roles[x]] == "minion"]
            sw = [x for x in minions if self.roles[x] == "scarlet_woman" and self.poisoned != x]
            if cause == "night":
                heirs = sw or minions  # the Imp killed itself: a Minion becomes the Imp
            else:
                heirs = sw if alive_before >= 5 else []
            if not heirs:
                self.winner = "good"
                return
            heir = heirs[0] if len(heirs) == 1 else self.st.pick_heir(self, heirs)
            self.roles[heir] = "imp"
            self.demon = heir
            self.note(M("note_starpass" if cause == "night" else "note_sw", t=S(heir)))
            if heir == self.human:
                await self.tell(M("now_imp"))
        if cause == "execution" and self.roles[s] == "saint" and self.poisoned != s:
            self.winner = "evil"
            await self.say(M("was_saint", p=S(s)))
        elif len(self.alive) <= 2 or set(self.alive) <= self.team:
            self.winner = "evil"

    # --- night -------------------------------------------------------------------------------

    async def _night(self):
        self.night += 1
        self.phase = "night"
        executed, self.executed = self.executed, None
        self.prev_executed = executed
        self.poisoned = None
        self.dusk = self.pub
        await self.say(M("night_falls", n=self.night))
        await self.beat(M("night_title", n=self.night), M("night_body"))

        def acting(role):
            return [s for s in self.alive if self.perceived[s] == role]

        for s in self.alive:
            if self.roles[s] == "poisoner":
                self.poisoned = await self.ask(self.agents[s].poison_pick(self))
                self.note(M("note_poison", t=S(self.poisoned)))
        if self.night == 1:
            order = FIRST_NIGHT_INFO
        else:
            protect = None
            for s in acting("monk"):
                t = await self.ask(self.agents[s].monk_pick(self))
                self.agents[s].inbox.append(Report(s, self.night, "monk", (t,)))
                if self.roles[s] == "monk" and self.poisoned != s:
                    protect = t
            killed = None
            if self.demon in self.alive and self.poisoned != self.demon:
                t = await self.ask(self.agents[self.demon].kill_pick(self))
                if self.roles[t] == "mayor" and self.poisoned != t and t != protect:
                    bounce = self.st.mayor_bounce(self, t, protect)
                    if bounce is not None:
                        self.note(M("note_bounce", t=S(t), x=S(bounce)))
                        t = bounce
                if t == protect or (self.roles[t] == "soldier" and self.poisoned != t):
                    self.note(M("note_survive", t=S(t)))
                    self.survived.add(t)
                else:
                    await self._kill(t, "night")
                    killed = t
            if self.winner:
                return
            if killed is not None and self.perceived[killed] == "ravenkeeper":
                await self._info(killed, "ravenkeeper")
            order = ("empath", "fortune_teller") + (("undertaker",) if executed is not None else ())
        for role in order:
            for s in acting(role):
                await self._info(s, role, executed)
        for s in self.alive:
            if self.roles[s] == "butler":
                self.butler_master = await self.ask(self.agents[s].butler_pick(self))
        if self.human in self.alive and self.roles[self.human] == "spy":
            await self.tell(M("spy_grim", list=L(M("grim_entry", p=S(s), role=R(self.roles[s]), flags=L(
                ([M("flag_poisoned")] if s == self.poisoned else [])
                + ([M("flag_thinks", role=R(self.drunk_as))] if self.roles[s] == "drunk" else []))) for s in range(self.n))))

    async def _info(self, s, kind, executed=None):
        malf = self.roles[s] == "drunk" or self.poisoned == s
        arg = executed
        if kind == "fortune_teller":
            arg = await self.ask(self.agents[s].ft_pick(self))
        elif kind == "ravenkeeper":
            arg = await self.ask(self.agents[s].rk_pick(self))
        options = [Report(s, self.night, kind, d) for d in self._options(s, kind, malf, arg)]
        report = self.st.choose(self, options)
        self.agents[s].inbox.append(report)
        if s == self.human:
            await self.tell(M("learn", info=self._info_text(report)))
            await self.beat(M("learn_title"), M("learn", info=self._info_text(report)))
        if malf:
            why = M("why_drunk") if self.roles[s] == "drunk" else M("why_poisoned")
            self.note(M("note_shown", p=S(s), why=why, info=self.describe(report)))

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
                # The Storyteller never shows a player their own character as someone else's.
                opts = [(a, b, r) for a, b in combinations(others, 2) for r in pool if r != kind]
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
        if malf:
            return [(arg, r) for r in ALL_ROLES if r != kind]
        return [(arg, r) for r in sorted(self._registers_as(arg, ALL_ROLES))]

    # --- day ---------------------------------------------------------------------------------

    async def _day(self):
        self.day += 1
        self.dusk = None
        self.suggest = {}
        self.offers = []
        self.volunteer = None
        self.pub = replace(self.pub, nights=self.night)
        self.phase = "dawn"
        await self.say(M("day_header", d=self.day))
        died = [S(d.seat) for d in self.pub.deaths if d.tick == night_tick(self.night)]
        dawn = M("dawn_deaths", list=L(died, conj=True)) if died else M("dawn_none")
        await self.say(dawn)
        await self.beat(M("day_header", d=self.day), dawn)
        await self._show_hint()
        k = self.day % self.n
        order = [(k + i) % self.n for i in range(self.n)]
        await self._private_chats(order)
        self.phase = "discussion"
        await self.say(M("phase_discussion"))
        await self.beat(M("phase_discussion_title"), M("phase_discussion_body"))
        for s in order:
            await self._speak(s, accuse=self.day > 1)
            if self.winner:
                return
        if self.day == 1:
            # Once everyone has said who they are, a second round for suspicions.
            await self.say(M("phase_react"))
            for s in order:
                await self._react(s)
                if self.winner:
                    return
        self._check()
        await self._show_reads()
        await self._mayor_plea()
        await self._plan_virgin_test()
        self.phase = "nominations"
        await self._nominations()
        self._check()

    # --- speaking ------------------------------------------------------------------------------

    async def _claim(self, s, role):
        before = self.pub.claims[s] if self.pub.claims else None
        if role == before:
            return
        self.pub = self.pub.claim(self.day, s, role)
        self._seq += 1
        self.claim_seq[s] = self._seq
        if before is None:
            await self.speech(s, self.m("claim", role=R(role)))
        else:
            await self.speech(s, self.m("claim_change", old=R(before), new=R(role)))
        await self._counterclaim(s, role)

    async def _counterclaim(self, s, role):
        """Whoever really has `role` (or believes so) calls out a false claim straight away."""
        for x in range(self.n):
            agent = self.agents[x]
            if x in (s, self.human) or x in self.team or x in self.dead or getattr(agent, "role", None) != role:
                continue
            if (x, s) in self.countered:
                continue
            self.countered.add((x, s))
            if self.pub.claims[x] != role:
                await self._claim(x, role)  # come out of hiding to contest it
            if agent.inbox:
                await self._publish(*sorted(agent.inbox, key=lambda r: r.night))
                agent.inbox.clear()
            await self.speech(x, self.m("counter", t=S(s), role=R(role)))

    async def _publish(self, *reports):
        self.pub = self.pub.plus(*reports)
        for r in reports:
            await self.speech(r.seat, self._report_msg(r))

    def _report_msg(self, r):
        if r.kind == "monk":
            return M("report_monk", n=r.night, a=S(r.data[0]))
        return self.m("report", n=r.night, role=R(r.kind), info=self._info_text(r))

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

    async def _private_chats(self, order):
        """Players step aside in small groups. Each player is in at most one group a day."""
        self.phase = "private chats"
        if self.day == 1 and self.human in self.team:
            # The evil team meets first: an AI teammate (the Demon if it can) takes the human aside.
            mates = sorted(self.team - {self.human}, key=lambda s: s != self.demon)
            if mates:
                order = [mates[0]] + [s for s in order if s != mates[0]]
        await self.say(M("phase_chats"))
        await self.beat(M("phase_chats_title"), M("phase_chats_body"))
        busy = set()
        for s in order:
            if s in busy:
                continue
            free = [x for x in self.alive if x != s and x not in busy]
            invited = await self.ask(self.agents[s].invite(self, free)) if free else []
            if not invited:
                continue
            joined = [x for x in invited if await self.ask(self.agents[x].accept(self, s, invited))]
            declined = [x for x in invited if x not in joined]
            if s == self.human and declined:
                await self.tell(M("declined", list=L((S(x) for x in declined), conj=True)))
            if not joined:
                continue
            group = tuple(sorted([s, *joined]))
            busy.update(group)
            await self._chat(group)

    async def _whisper(self, s, group, claim=None, report=None, text=None):
        self._seq += 1
        if claim or report:
            self.whispers.append(Whisper(self.day, group, s, claim, report, self._seq))
        if self.human not in group:
            return
        public = self.pub.claims[s] if self.pub.claims else None
        if claim:
            line = M("w_really" if public and public != claim else "w_claim", role=R(claim))
        elif report:
            line = self._report_msg(report)
        else:
            line = text
        await self.speech(s, line, private=True, chat=True)

    async def _chat(self, group):
        if self.human in group:
            await self.say(M("you_step", list=L((S(x) for x in group if x != self.human), conj=True)), private=True, chat=True)
        else:
            await self.say(M("chats_step", list=L((S(x) for x in group), conj=True)))
        for s in group:
            if s == self.human:
                await self._human_chat(group)
                continue
            agent = self.agents[s]
            mates = [x for x in group if x != s and x in self.team]
            if s in self.team and mates:
                # Among the evil team, a private chat is for making plans.
                public = self.pub.claims[s] if self.pub.claims else None
                await self._whisper(s, group, text=M("e_role", role=R(self.roles[s]), claim=R(public or self.planned_claims[s])))
                if self.roles[s] == "poisoner":
                    await self._whisper(s, group, text=M("e_poison", t=S(agent.poison_pick(self))))
                elif s == self.demon and self.day >= 1:
                    await self._whisper(s, group, text=M("e_kill", t=S(agent.kill_pick(self))))
                if s == self.demon and self.human in mates and self.human_bluff and not self.bluff_given:
                    self.bluff_given = True
                    await self._whisper(s, group, text=M("e_bluff_for_you", role=R(self.human_bluff)))
                continue
            public = self.pub.claims[s] if self.pub.claims else None
            if s in self.team and public is None:
                await self._whisper(s, group, claim=self.planned_claims[s])
            elif s not in self.team and public is None and not agent.cover:
                # Before anyone has spoken in public: compare notes with your character and info.
                await self._whisper(s, group, claim=agent.role)
                for r in sorted(agent.inbox, key=lambda r: r.night):
                    await self._whisper(s, group, report=r)
            elif s not in self.team and public is not None and public != agent.role:
                # A hidden player confides their real character and info to people they trust.
                await self._whisper(s, group, claim=agent.role)
                for r in sorted(agent.inbox, key=lambda r: r.night):
                    await self._whisper(s, group, report=r)
            said = agent.statement(self)
            if said:
                await self._whisper(s, group, text=self.m("suspect", t=S(said[0]), why=said[1]))
            else:
                await self._whisper(s, group, text=self.m("no_read"))

    async def _human_chat(self, group):
        h = self.human
        io = self.agents[h].io
        listener = next(x for x in group if x != h)
        mates = [x for x in group if x != h and x in self.team] if h in self.team else []
        while True:
            told = self.record_for(listener).claims[h] if self.pub.claims else None
            acts = [("claim", M("c_claim"))]
            if told and self._info_nights(h, told, include_reported=True):
                acts.append(("share", M("c_share", role=R(told))))
            acts.append(("accuse", M("c_accuse")))
            if any(x == self.demon for x in mates):
                acts.append(("kill", M("c_kill")))
            if any(self.roles[x] == "poisoner" for x in mates):
                acts.append(("poison", M("c_poison")))
            acts.append(("done", M("c_done")))
            act = acts[await io.choose(M("q_chat"), [a[1] for a in acts], default=len(acts) - 1)][0]
            if act == "done":
                return
            if act == "claim":
                await self._human_claim(group)
            elif act == "share":
                await self._human_share(told, group)
            elif act in ("kill", "poison"):
                targets = [s for s in self.alive if s not in self.team]
                t = await io.seat(M("q_kill_suggest" if act == "kill" else "q_poison_suggest"), targets)
                if t is not None:
                    self.suggest[act] = t
                    helper = next(x for x in mates if (x == self.demon if act == "kill" else self.roles[x] == "poisoner"))
                    await self._whisper(h, group, text=M("s_kill" if act == "kill" else "s_poison", t=S(t)))
                    await self._whisper(helper, group, text=M("e_ok", t=S(t)))
            else:
                t = await io.seat(M("q_whom_suspect"), [s for s in self.alive if s != h])
                if t is not None:
                    await self._whisper(h, group, text=M("suspect_plain", t=S(t)))

    async def _offer(self, s):
        if s != self.human and self._may_offer(s):
            self.offers.append(s)
            self.offered_ever.add(s)
            await self.speech(s, self.m("volunteer"))

    async def _react(self, s):
        if s == self.human:
            return await self._human_turn(react=True)
        agent = self.agents[s]
        if s not in self.team and s not in self.dead:
            role = agent.claim_now(self)  # e.g. someone has just claimed my cover or my character
            if role:
                await self._claim(s, role)
                if agent.inbox:
                    await self._publish(*sorted(agent.inbox, key=lambda r: r.night))
                    agent.inbox.clear()
        await self._offer(s)
        said = self.agents[s].statement(self)
        if said:
            await self.speech(s, self.m("suspect", t=S(said[0]), why=said[1]))
            await self._reply(said[0])

    async def _speak(self, s, accuse=True):
        if s == self.human:
            return await self._human_turn()
        agent = self.agents[s]
        await self._nothing_to_report(s)
        if s in self.team:
            if not self.pub.claims or self.pub.claims[s] is None:
                await self._claim(s, self.planned_claims[s])
            if s not in self.dead:
                for night in self._info_nights(s, self.pub.claims[s]):
                    fake = self._evil_report(s, night)
                    if fake:
                        await self._publish(fake)
        else:
            role = agent.claim_now(self)
            if role:
                await self._claim(s, role)
            elif (not self.pub.claims or self.pub.claims[s] is None) and s not in self.dead:
                await self.speech(s, self.m("stay_quiet"))
            if self.pub.claims and self.pub.claims[s] == agent.role and agent.inbox:
                await self._publish(*sorted(agent.inbox, key=lambda r: r.night))
                agent.inbox.clear()
            if s not in self.dead and self.perceived[s] == "slayer" and not agent.slayer_used:
                t = agent.slayer_pick(self)
                if t is not None:
                    await self._shoot(s, t)
                    if self.winner:
                        return
        if self.day > 1:
            await self._offer(s)
        said = agent.statement(self) if accuse else None
        if said:
            t, why = said
            await self.speech(s, self.m("suspect", t=S(t), why=why))
            await self._reply(t)

    async def _reply(self, t):
        """An accused AI player answers back, once a day."""
        if t == self.human or t in self.dead or (self.day, t) in self.replied:
            return
        self.replied.add((self.day, t))
        claim = self.pub.claims[t] if self.pub.claims else None
        await self.speech(t, self.m("reply", role=R(claim)) if claim else M("reply_silent"))

    async def _nothing_to_report(self, s):
        """A claimed Undertaker says so when nobody was executed yesterday."""
        claims = self.pub.claims
        if claims and claims[s] == "undertaker" and self.day >= 2 and s not in self.dead \
                and self.executed_on(self.day - 1) is None:
            await self.speech(s, M("no_exec_info"))

    async def _shoot(self, s, t):
        self.agents[s].slayer_used = True
        demonish = t == self.demon or (self.roles[t] == "recluse" and self.st.helps(self) == "evil")
        hit = self.roles[s] == "slayer" and self.poisoned != s and demonish
        shot = M("shoot", p=S(s), t=S(t), result=M("shot_dies", t=S(t)) if hit else M("shot_nothing"))
        await self.say(shot, speaker=s)
        await self.beat(M("slayer_title"), shot)
        self.pub = replace(self.pub, shots=self.pub.shots + (Shot(self.day, s, t, hit),))
        if hit:
            await self._kill(t, "slayer")

    def _evil_report(self, s, night):
        """An evil player invents info for their bluff, choosing what they think the town reads best."""
        kind = self.pub.claims[s]
        agent = self.agents[s]
        base = self.pub
        options = [Report(s, night, kind, d) for d in self._fake_options(s, kind, night)]
        options = [r for r in options if not self._implicates_team(r)] or options
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

    async def _human_turn(self, defending=False, react=False):
        h = self.human
        agent, io = self.agents[h], self.agents[h].io
        while True:
            claim = self.pub.claims[h] if self.pub.claims else None
            acts = [("claim", M("a_claim") if claim is None else M("a_change", role=R(claim)))]
            if claim is not None and self._info_nights(h, claim) and not react:
                acts.append(("share", M("a_share", role=R(claim))))
            if h not in self.dead and not defending:
                acts.append(("accuse", M("a_accuse")))
                if not agent.slayer_used and "slayer" in (claim, self.perceived[h]):
                    acts.append(("shoot", M("a_shoot")))
                if h not in self.offers:
                    acts.append(("offer", M("a_volunteer")))
            acts.append(("done", M("a_done")))
            prompt = M("q_defend") if defending else M("q_react") if react else M("q_turn")
            keys = [a[0] for a in acts]
            default = (keys.index("claim") if claim is None and not react else keys.index("share") if "share" in keys
                       else len(acts) - 1)
            act = acts[await io.choose(prompt, [a[1] for a in acts], default=default)][0]
            if act == "done":
                return
            if act == "claim":
                await self._human_claim()
            elif act == "share":
                await self._human_share(claim)
            elif act == "accuse":
                t = await io.seat(M("q_whom_suspect"), [s for s in self.alive if s != h])
                if t is not None:
                    await self.speech(h, M("suspect_plain", t=S(t)))
                    await self._reply(t)
            elif act == "offer":
                self.offers.append(h)
                await self.speech(h, self.m("volunteer"))
            elif act == "shoot":
                t = await io.seat(M("q_shoot"), [s for s in self.alive if s != h])
                if t is not None:
                    await self._claim(h, "slayer")
                    await self._shoot(h, t)
                    if self.winner:
                        return

    async def _human_claim(self, group=None):
        h = self.human
        io = self.agents[h].io
        mine = [self.perceived[h]] if h not in self.team else ([self.roles[h]] if group and any(
            x in self.team and x != h for x in group) else [])
        bluffs = self.bluffs if h == self.demon else [self.human_bluff] if self.bluff_given else []
        first = mine + [b for b in bluffs if b not in mine]
        roles = first + [r for r in ALL_ROLES if r not in first and r != "drunk"]
        bluff_label = "lbl_bluff" if h == self.demon else "lbl_given"
        labels = [M("lbl_yours" if r in mine else bluff_label if r in bluffs else "lbl_evil" if is_evil(r)
                    else "lbl_role", role=R(r)) for r in roles]
        role = roles[await io.choose(M("q_which_char"), labels, default=0)]
        if group:
            await self._whisper(h, group, claim=role)
        else:
            await self._claim(h, role)

    async def _human_share(self, kind, group=None):
        h = self.human
        agent, io = self.agents[h], self.agents[h].io
        nights = self._info_nights(h, kind, include_reported=bool(group))
        night = nights[0] if len(nights) == 1 else nights[await io.choose(
            M("q_which_night"), [M("lbl_night", n=n) for n in nights], default=len(nights) - 1)]
        real = [r for r in agent.inbox if r.kind == kind and r.night == night]
        others = [s for s in range(self.n) if s != h]
        if kind == "fortune_teller":
            default = list(real[0].data[:2]) if real else others[:2]
            a, b = sorted(await io.seats(M("q_ft_pick", n=night), others, 2, default))
            yes = await io.choose(M("q_ft_answer"), [M("no"), M("yes")], default=int(real[0].data[2]) if real else 0)
            report = Report(h, night, kind, (a, b, bool(yes)))
        elif kind == "monk":
            alive = [s for s in self.alive if s != h]
            t = await io.seat(M("q_monk_pick", n=night), alive, real[0].data[0] if real else alive[0])
            report = Report(h, night, kind, (t,))
        else:
            opts = list(real) + [Report(h, night, kind, d) for d in self._fake_options(h, kind, night)
                                 if not real or d != real[0].data]
            labels = [M("lbl_real", info=self._info_text(r)) if r in real else self._info_text(r) for r in opts]
            if kind in PING:
                labels.append(M("lbl_else"))
            i = await io.choose(M("q_info", n=night, role=R(kind)), labels, 0)
            if i < len(opts):
                report = opts[i]
            else:
                a, b = sorted(await io.seats(M("q_two"), others, 2, others[:2]))
                pool = list(PING[kind])
                report = Report(h, night, kind, (a, b, pool[await io.choose(M("q_as_which"), [R(r) for r in pool], 0)]))
        if group:
            await self._whisper(h, group, report=report)
            return
        agent.inbox = [r for r in agent.inbox if not (r.kind == kind and r.night == night)]
        await self._publish(report)

    def _implicates_team(self, r):
        """A lie that would point at the liar's own teammates."""
        d = r.data
        if r.kind in ("investigator", "fortune_teller") and d[0] is not None:
            return (r.kind == "investigator" or d[2]) and any(x in self.team for x in d[:2])
        if r.kind in ("undertaker", "ravenkeeper"):
            return d[0] in self.team and is_evil(d[1])
        return False

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

    async def _show_hint(self):
        if not self.hints or self.human in self.dead or not self.pub.claims:
            return
        agent = self.agents[self.human]
        b = self.public_belief() if self.human in self.team else self.belief_of(agent)
        top = sorted((s for s in self.alive if s != self.human), key=lambda s: -b.suspicion(s))[:4]
        await self.tell(M("hint", k=b.count, list=L(M("seat_pct", p=S(s), pct=b.suspicion(s)) for s in top)))

    async def _show_reads(self):
        if not self.out or self.human is not None:
            return
        b = self.public_belief()
        top = sorted(self.alive, key=lambda s: -b.suspicion(s))[:3]
        await self.say(M("raw", text=f"  [town read: {b.count} worlds, ~{b.candidates():.1f} Demon candidates "
                                f"(Storyteller target {self.st.target(self):.1f}); most suspected: "
                                + ", ".join(f"{self.name(s)} {b.suspicion(s)}" for s in top) + "]"))
        reads = []
        for s in self.alive:
            ag = self.agents[s]
            if s in self.team:
                continue
            pb = self.belief_of(ag)
            t = ag.rank([x for x in self.alive if x != s], lambda x: -pb.suspicion(x))[0]
            reads.append(f"{self.name(s)}({ag.profile.name[0]}{'!' if pb.relaxed else ''})→{self.name(t)} {pb.suspicion(t)}")
        await self.say(M("raw", text="  [reads: " + ", ".join(reads) + "]"))

    async def _nominations(self):
        await self.say(M("phase_noms"))
        await self.beat(M("phase_noms_title"), M("phase_noms_body"))
        await self._show_hint()
        nominated, nominators = set(), set()
        st = {"best": 0, "block": None, "tie": False}
        # A Virgin test the table agreed on goes first.
        plan, self.virgin_plan = self.virgin_plan, None
        if plan:
            tester, virgin = plan
            if tester in self.alive and virgin in self.alive and virgin not in self.ever_nominated:
                nominators.add(tester)
                nominated.add(virgin)
                await self.say(M("nominates_test", a=S(tester), t=S(virgin)), speaker=tester)
                if await self._vote_on(tester, virgin, st):
                    return
                await self._after_failed_test(tester, virgin)
        k = self.day % self.n
        order = list(range(k, self.n)) + list(range(k))
        progress = True
        while progress:
            progress = False
            for s in order:
                if s in self.dead or s in nominators:
                    continue
                self.on_block = None if st["tie"] else st["block"]
                t = await self.ask(self.agents[s].nominate(self, nominated))
                if t is None:
                    continue
                progress = True
                nominators.add(s)
                nominated.add(t)
                agent = self.agents[s]
                if s == self.human:
                    await self.say(M("nominates_plain", a=S(s), t=S(t)), speaker=s)
                else:
                    b = agent.read(self) if s in self.team else self.belief_of(agent)
                    await self.say(self.m("nominates", a=S(s), t=S(t), why=agent.explain(self, t, b)), speaker=s)
                if await self._vote_on(s, t, st):
                    return
        # Nobody about to die: take up an offer made in the discussion.
        offers = [x for x in self.offers if x in self.alive and x not in nominated]
        if st["block"] is None and offers:
            v = offers[0]
            self.volunteer = v
            by = next((x for x in self.alive if x not in nominators and x not in (v, self.human)
                       and x not in self.team), v)
            await self.say(M("nominates_self", a=S(v)) if by == v else M("nominates_offer", a=S(by), t=S(v)),
                           speaker=by)
            if await self._vote_on(by, v, st):
                return
        best, block, tie = st["best"], st["block"], st["tie"]
        if block is not None and not tie:
            await self.say(M("executed", t=S(block)))
            await self.beat(M("result_title"), M("executed", t=S(block)))
            self.executed = block
            await self._kill(block, "execution")
        else:
            await self.say(M("no_execution"))
            await self.beat(M("result_title"), M("no_execution"))
            if len(self.alive) == 3 and any(self.roles[s] == "mayor" and self.poisoned != s for s in self.alive):
                await self.say(M("mayor_win"))
                self.winner = "good"

    async def _vote_on(self, s, t, st):
        """Virgin check, defence and vote for one nomination. True if the day ends at once."""
        if await self._virgin(s, t):
            return True
        if s != t:
            await self._defend(t)
        majority = (len(self.alive) + 1) // 2
        needed = max(majority, st["best"] + 1)
        on_block = None if st["tie"] else st["block"]
        await self.say(M("vote_on_block", t=S(t), needed=needed, b=S(on_block)) if on_block is not None
                       else M("vote_on", t=S(t), needed=needed))
        voters = await self._vote(t, needed, on_block)
        self.pub = replace(self.pub, votes=self.pub.votes + (Vote(self.day, s, t, tuple(voters)),))
        who = L((S(v) for v in voters), paren=True)
        if len(voters) >= majority and len(voters) > st["best"]:
            st.update(best=len(voters), block=t, tie=False)
            await self.say(M("votes_block", k=len(voters), voters=who, t=S(t)))
        elif len(voters) >= majority and len(voters) == st["best"]:
            st["tie"] = True
            await self.say(M("votes_tie", k=len(voters), voters=who))
        else:
            await self.say(M("votes_short", k=len(voters), voters=who))
        return False

    async def _after_failed_test(self, tester, virgin):
        """The Virgin test did nothing: both sides explain what that means."""
        if virgin != self.human and virgin not in self.team and self.perceived[virgin] == "virgin":
            await self.speech(virgin, self.m("virgin_dud", t=S(tester)))  # the tester, or am I drunk/poisoned?
        if tester == self.human:
            return
        if tester in self.team:
            await self.speech(tester, self.m("smear_virgin", vg=S(virgin)))  # dirty the Virgin
        else:
            await self.speech(tester, self.m("virgin_result", vg=S(virgin)))

    def _may_offer(self, x):
        """A good first-night info role, on day 1 or 2, while someone claims Undertaker."""
        claims = self.pub.claims or ()
        agent = self.agents[x]
        return (self.day <= 2 and x in self.alive and x not in self.team and x not in self.offered_ever
                and agent.profile.name != "novice" and bool(claims) and claims[x] == agent.role
                and agent.role in SPENT and any(claims[y] == "undertaker" for y in self.alive if y != x))

    async def _mayor_plea(self):
        """Three or four alive and a Mayor claim: the Mayor asks the table not to execute anyone."""
        claims = self.pub.claims or ()
        if len(self.alive) not in (3, 4) or not claims:
            return
        for x in self.alive:
            if claims[x] == "mayor" and x != self.human:
                await self.speech(x, self.m("mayor_plea" if len(self.alive) == 3 else "mayor_plea4"))

    async def _plan_virgin_test(self):
        """Someone proposes that a first-night info role nominate the claimed Virgin: one
        nomination tests both of them."""
        claims = self.pub.claims or ()
        virgins = [x for x in self.alive if claims and claims[x] == "virgin" and x not in self.ever_nominated
                   and x not in self.virgin_planned]
        if not virgins:
            return
        planners = [x for x in self.alive if x not in self.team and x != self.human
                    and self.agents[x].profile.name != "novice"]
        if not planners:
            return
        # Test the claimed Virgin the proposer doubts most (two may claim it).
        v = max(virgins, key=lambda x: (self.agents[planners[0]].suspicion(self, x), -x))
        planners = [x for x in planners if x != v]
        testers = [x for x in self.alive if x != v and claims[x] in SPENT]
        if not planners or not testers:
            return
        p = planners[0]
        self.virgin_planned.add(v)
        agent = self.agents[p]
        t = min(testers, key=lambda x: (agent.suspicion(self, x) if x != p else 0, agent.bias[x]))
        if t == p:  # the proposer is the best tester: they go themself
            await self.speech(p, M("virgin_plan_self", vg=S(v)))
            self.virgin_plan = (p, v)
            return
        await self.speech(p, M("virgin_plan", vg=S(v), t=S(t)))
        if t == self.human:
            if await self.agents[t].io.yes_no(M("q_virgin_test", vg=S(v))):
                await self.speech(t, M("virgin_ok"))
                self.virgin_plan = (t, v)
            return
        others = [x for x in testers if x != t and x not in self.team]
        if t in self.team and self.agents[t].profile.name != "novice" and others:
            # An evil "Townsfolk" would not trigger the Virgin: steer the test to someone else.
            alt = others[0]
            await self.speech(t, M("virgin_deflect", t=S(alt)))
            if alt == self.human and not await self.agents[alt].io.yes_no(M("q_virgin_test", vg=S(v))):
                return
            await self.speech(alt, M("virgin_ok"))
            self.virgin_plan = (alt, v)
            return
        await self.speech(t, M("virgin_ok"))  # an evil novice goes along, and will smear the Virgin
        self.virgin_plan = (t, v)

    async def _defend(self, t):
        """The nominee speaks before the vote."""
        if t == self.human:
            await self._human_turn(defending=True)
            return
        agent = self.agents[t]
        if t not in self.team:
            role = agent.claim_now(self, pressed=True)
            if role:
                await self._claim(t, role)
            if self.pub.claims and self.pub.claims[t] == agent.role and agent.inbox:
                await self._publish(*sorted(agent.inbox, key=lambda r: r.night))
                agent.inbox.clear()
        claim = self.pub.claims[t] if self.pub.claims else None
        await self.speech(t, self.m("defend", role=R(claim)) if claim else M("defend_silent"))

    async def _virgin(self, s, t):
        if t in self.ever_nominated:
            return False
        self.ever_nominated.add(t)
        townsfolk = KIND[self.roles[s]] == "townsfolk" or (
            self.roles[s] == "spy" and self.roles[t] == "virgin" and self.st.helps(self) == "good")
        triggered = self.roles[t] == "virgin" and self.poisoned != t and townsfolk
        self.pub = replace(self.pub, first_noms=self.pub.first_noms + (Nomination(self.day, s, t, triggered),))
        if triggered:
            await self.say(M("virgin", a=S(s), t=S(t)))
            await self.beat(M("virgin_title"), M("virgin", a=S(s), t=S(t)))
            self.executed = s
            await self._kill(s, "execution")
        return triggered

    async def _vote(self, t, needed, block):
        voters = []
        order = [(t + i) % self.n for i in range(1, self.n + 1)]
        can_vote = [v for v in order if v not in self.dead or v not in self.ghosts_used]
        for v in order:
            ghost = v in self.dead
            if ghost and v in self.ghosts_used:
                continue
            if self.roles[v] == "butler" and not ghost and self.butler_master not in voters:
                continue
            self.votes_left = len(can_vote) - can_vote.index(v) - 1  # hands still to come after this one
            if await self.ask(self.agents[v].vote(self, t, len(voters), needed, block, ghost)):
                voters.append(v)
                if ghost:
                    self.ghosts_used.add(v)
        return voters

    # --- presentation ------------------------------------------------------------------------

    def describe(self, r):
        return M("describe", n=r.night, p=S(r.seat), role=R(r.kind), info=self._info_text(r))

    def _info_text(self, r):
        d = r.data
        if r.kind in PING:
            return M("info_zero") if d == ZERO else M("info_ping", a=S(d[0]), b=S(d[1]), role=R(d[2]))
        if r.kind in ("chef", "empath"):
            return M("info_" + r.kind, c=d[0])
        if r.kind == "fortune_teller":
            return M("info_ft", a=S(d[0]), b=S(d[1]), ans=M("yes" if d[2] else "no"))
        if r.kind == "monk":
            return M("info_monk", a=S(d[0]))
        return M("info_" + r.kind, a=S(d[0]), role=R(d[1]))

    def notebook(self):
        """The whole public record, in order, plus what the Storyteller told the human (messages)."""
        pub = self.pub
        lines = [M("nb_title")]
        if pub.claims:
            lines.append(M("nb_claims", list=L(M("seat_claim", p=S(s), role=R(c) if c else M("silent"))
                                               for s, c in enumerate(pub.claims))))
        for n in range(1, self.night + 1):
            died = [S(d.seat) for d in pub.deaths if d.tick == night_tick(n)]
            lines.append(M("nb_night", n=n, list=L(died, conj=True)) if died else M("nb_night_none", n=n))
            lines += [M("nb_report", line=self.describe(r)) for r in pub.reports if r.night == n]
            if n > self.day:
                continue
            lines.append(M("nb_day", n=n))
            said = {}
            for c in pub.claim_log:
                if c.day == n:
                    old = said.get(c.seat) or next((x.role for x in reversed(pub.claim_log)
                                                    if x.seat == c.seat and x.day < n), None)
                    lines.append(M("nb_claimed_changed", p=S(c.seat), role=R(c.role), old=R(old))
                                 if old and old != c.role else M("nb_claimed", p=S(c.seat), role=R(c.role)))
                    said[c.seat] = c.role
            for sh in pub.shots:
                if sh.day == n:
                    lines.append(M("nb_shot", p=S(sh.shooter), t=S(sh.target),
                                   result=M("nb_shot_died" if sh.killed else "nb_shot_nothing")))
            for fn in pub.first_noms:
                if fn.day == n and fn.triggered:
                    lines.append(M("nb_virgin", a=S(fn.nominator), t=S(fn.nominee)))
            for v in pub.votes:
                if v.day == n:
                    lines.append(M("nb_vote", a=S(v.nominator), t=S(v.nominee), k=len(v.voters),
                                   voters=L((S(x) for x in v.voters), paren=True)))
            ex = self.executed_on(n)
            lines.append(M("nb_exec", p=S(ex)) if ex is not None else M("nb_noexec"))
        dead = sorted(self.dead)
        lines.append(M("nb_dead", list=L(M("dead_entry_used" if s in self.ghosts_used else "dead_entry", p=S(s))
                                         for s in dead) if dead else M("nb_nobody")))
        if self.human is not None:
            chats = [w for w in self.whispers if self.human in w.group]
            if chats:
                lines.append(M("nb_chats"))
            for w in chats:
                with_ = L((S(x) for x in w.group if x != self.human), conj=True)
                lines.append(M("nb_chat_claim", d=w.day, list=with_, p=S(w.speaker), role=R(w.claim)) if w.claim
                             else M("nb_chat_report", d=w.day, list=with_, line=self.describe(w.report)))
        if self.private:
            lines.append(M("nb_told"))
            lines += self.private
        return lines

    def history(self, seat):
        """Everything public about one player, for their player card (messages)."""
        pub, out = self.pub, []
        for c in pub.claim_log:
            if c.seat == seat:
                out.append(M("nb_claimed", p=S(seat), role=R(c.role)))
        out += [M("nb_report", line=self.describe(r)) for r in pub.reports if r.seat == seat]
        for v in pub.votes:
            if seat in (v.nominator, v.nominee) or seat in v.voters:
                out.append(M("nb_vote", a=S(v.nominator), t=S(v.nominee), k=len(v.voters),
                             voters=L((S(x) for x in v.voters), paren=True)))
        return out

    async def _reveal(self):
        self.phase = "over"
        team = {"good": "team_good", "evil": "team_evil"}.get(self.winner, "team_none")
        await self.say(M("winner", team=M(team), d=self.day))
        await self.beat(M("over_title"), M("winner", team=M(team), d=self.day))
        await self.say(M("grimoire"))
        for s, r in enumerate(self.start_roles):
            extra = L(([M("drunk_thought", role=R(self.drunk_as))] if r == "drunk" else [])
                      + ([M("red_herring")] if s == self.red_herring else [])
                      + ([M("dead")] if s in self.dead else []))
            who = M("who_you") if s == self.human else M(self.agents[s].profile.name)
            if s in self.team:
                who = M("who_evil", who=who)
            await self.say(M("grim_line", p=S(s), role=R(r), extra=extra, who=who))
        await self.say(M("bluffs_end", roles=L(R(b) for b in self.bluffs)))
        await self.say(M("st_notes"))
        for line in self.notes:
            await self.say(line)
