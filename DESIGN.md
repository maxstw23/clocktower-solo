# Deterministic Blood on the Clocktower (Trouble Brewing)

Goal: a single-player game whose "fuzzy" parts (imperfect players, a balancing Storyteller) are
deterministic given a hidden seed, with no LLM in the game state.

    python play.py                    # play one seat in your browser (http://127.0.0.1:8765)
    python play.py --terminal         # or in the terminal
    python build_web.py               # standalone build in dist/: the game runs in the browser (phones too)
    python sim.py --seed 3            # one narrated all-AI game
    python sim.py --games 30 --players 8 --check
    python tests/test_core.py

## Layers

| Layer | File | Role |
|---|---|---|
| Script | `roles.py` | Trouble Brewing roles, setup counts |
| Notebook reasoner | `notebook.py` | How a person reads the table: evidence, trust, clashes, a few theories (replacing the solver in play, in progress) |
| Rulebook | `rules.py` | Characters as data; the truth check and possible outputs for each information category (shared by engine, solver and, later, every player) |
| Public record | `public.py` | Claims, reported info, deaths, Slayer shots, first nominations. Immutable and hashable. |
| World solver | `worlds.py` | Every starting role assignment consistent with the record (the omniscient baseline) |
| Agents | `agents.py` | Bounded views of the solver + fixed social dials; evil theory of mind |
| Storyteller | `storyteller.py` | Picks among legal options to steer the game's tension |
| Engine | `engine.py` | Grimoire (truth), night order, day procedure, win conditions |
| Human seat | `human.py` | Same moves as an AI player; questions go to the terminal or the browser |
| Browser UI | `web.py`, `static/index.html` | Local server (standard library) and a one-page table view |
| Languages | `i18n.py` | Every message, character name and ability in English and Chinese |

## Key abstractions

**The day.** Dawn; private conversations; then a public round where each player speaks once
(claims or changes their claim, shares what their ability showed them, and from day 2 says whom
they suspect and why); on day 1 a second round for suspicions once everyone has claimed; then
nominations, each with the nominator's reason, the nominee's defence, and a vote. In the browser,
phase changes and big moments (night, dawn and deaths, night info, executions, Slayer, Virgin, the
result) are shown as cards (`Game.beat`); each line stays up for a reading time based on its
length, and a step-by-step speed waits for a tap after every line. Reasons are generated from the solver:
a double claim, a changed claim, a pushed execution of a now-good-looking player, a direct ping or
YES, or "if X's info is right, they're evil in N% of the setups that fit".

**Private conversations.** After introductions, players may step aside in small groups (at most
one group per player per day). Everyone sees who talked; only the group hears what was said
(`Whisper`). Each player reasons from their own record (`Game.record_for`): the public record
plus what they heard in private, where a private claim overrides an earlier public one without
costing trust (confiding is not lying to the listener; only public claim changes cost trust). AI
policy: good players invite those they trust most (`confide_at`) and accept invitations from
players they trust; a hidden info role confides its real character and info instead of coming out
publicly. Evil players accept everything and invite valuable-looking good players, pool what the
team overheard, and kill the most dangerous trusted character, so confiding in the wrong person
gets you killed. The human can invite one or two players (who accept by trust) and accept or
decline invitations.

**Standalone (phones).** `build_web.py` writes a static site where the same Python engine runs in
the browser with Pyodide, in a Web Worker (`web/worker.js`, `botc/browser.py`). The engine is
async: a question to the human and the pause before each line are awaits, so the worker keeps
answering the page while a game is waiting. The page talks to the local server or the worker
through the same small API. `.github/workflows/pages.yml` publishes it with GitHub Pages; the
layout adapts to phone screens (compact table, question pinned to the bottom).

**Messages, not sentences.** The engine records each line as a message key plus arguments
(players, characters, nested reasons); `i18n.render` turns it into English or Chinese when it is
shown, so the page can switch language mid-game. Common lines have several phrasings, picked by
seed. In the browser the game paces itself (a pause before each line, adjustable speed) so players
speak one at a time; accused players answer back once a day.

**Table talk that resists bluffs.** Some good info roles stay quiet in public on day 1 and only
confide in private (`quiet_rate`); they come out when nominated, when someone claims their
character, or by `reveal_day`. Whoever really holds a character calls out a false claim at once
(coming out of hiding if needed), then pushes to nominate the impostor. A claimed info role that
hasn't shared past nights' info costs suspicion (`silence_cost`); an Undertaker says so when nobody
was executed. In AI-only 8-player games this moved good's win rate from about 55% to 63-67%.

**Evil coordination.** Anyone may claim an evil character, publicly or privately (as a good player
it reads as a costly bluff). In a private chat among the evil team, AI teammates state their real
character and plan ("I'll poison X tonight"); an evil human can suggest tonight's kill or poison
target and the AI follows it. A human Minion gets one of the Demon's bluffs, handed over by the
Demon in a private chat that the evil team holds first on day 1. The start screen can pick a side.

**Worlds and excuses.** A world is a starting role assignment. Records that contradict a sober
good player need an *excuse*: a poisoning (at most one per night, Poisoner alive), a Spy/Recluse
misregistration, the Drunk, or a good player's bluff. Each world records the excuses it needs.

**Good players may lie.** Claims are a timeline (`Public.claim_log`); a player can stay silent,
bluff, and change their claim. The solver takes a good player's *latest* claim as true, treats
silent players as unknown good roles, and allows at most one still-hidden good bluffer, but only
where the record gives a reason to suspect one (a double claim, an evil or Drunk claim, more
Outsider claims than even a Baron allows, or a claimed ability that visibly failed). A bluff
that leaves no trace is simply believed, as at a real table. Every claim change by a good player
halves that world's weight, so lying costs trust whatever your alignment. AI good players with
a fragile info role may hide behind a quiet cover (`hide_rate`: novice 0, regular 0.15, veteran
0.3) and come out when nominated, double-claimed, or by `reveal_day`.

**Imperfect players = restricted solver.** A `Profile` sets which excuses a player thinks of
(poison / Drunk / misregistration) and how many they tolerate (`max_excuses`). If nothing fits,
they widen their assumptions (`Belief.relaxed`), which is the moment a novice says "oh, someone
must be poisoned". Mistakes come from these blind spots, not dice.

**Integer-ish suspicion.** `suspicion = (2*demon% + evil%) / 3` over the worlds a player
considers. Nominations and votes compare it to thresholds that drop with `urgency` per day, with
`bandwagon` per yes vote, and to zero when four or fewer players are alive. A player votes only
for someone more suspicious than whoever is already on the block.

**Perfect memory.** Every player remembers everything said or done in the open (claims, info,
deaths, shots, Virgin results, every nomination and vote) plus what the Storyteller told them;
it is all one public record, `Public`. Skill decides how well players *interpret* it, never what
they remember: `vote_memory` is how much a remembered push of a now-good-looking execution counts
against the pusher. Remembering a lie is not the same as keeping it
straight: before lying, evil players check that the lie still fits (`story_check`): novices
don't check, regulars check against their own earlier claims, veterans against the whole record.
Over 100 games at 8 players, novice liars broke their own story in 26% of lies, regulars 6%,
veterans 3% (only when no candidate lie fit); good wins 70 / 61 / 52 on novice / regular /
veteran tables. The human gets the same record as a notebook
(`notes` or `?` at any prompt).

**Personal bias.** Each player has a seeded ordering of the other seats that breaks ties. That
is the only randomness in their behaviour.

**Evil theory of mind, at the same skill as good.** Evil players get profiles from the same pool
as good players. They imagine the town reasoning the way *they* would (own blind spots included),
test `lookahead` candidate lies against that read (novice 1, regular 3, veteran 6), and use the
same nomination/vote dials. Their only extra knowledge is the real game's: the team and bluffs.

**Night order and information timing.** Players act on the record as it stood at dusk
(`Game.known`); deaths become known at dawn. Official TB order: night 1 Poisoner → Washerwoman →
Librarian → Investigator → Chef → Empath → Fortune Teller → Butler; other nights Poisoner → Monk →
Imp → Ravenkeeper → Empath → Fortune Teller → Undertaker → Butler. The solver mirrors the
consequences: poison applies to the same night's info, the Empath counts neighbours after the
kill, and a Poisoner executed by day can't explain later info. The Storyteller also decides
in wake order, so later info is chosen knowing what earlier info will say.

**Storyteller as controller.** Its only freedom is what it already has in the real game: info
for drunk/poisoned players, Spy/Recluse registrations, the Mayor's bounce and the Demon's heir.
It knows the grimoire, so it steers by how much the town suspects the *real* Demon (a town that is
sure of the wrong player is losing, however narrow its read): the plan is a fair guess among the
living (`1 / (alive - 1)`). For each decision it samples up to 6 legal options and picks the one
that keeps the town closest to the plan; for the Mayor, heir and registrations it helps whichever
side is behind.

## Findings so far

- Weighting worlds by "an evil reporter's lie was a free choice" (Bayesian-style) made the town
  *worse*: evil optimises its lies against that same model, so the bonus for consistent info
  rewards evil. Plain world counting won ~43% for good at 8 players vs ~30%. `FREE` is kept,
  neutral, as a dial.
- "The Demon rarely kills its own team" (night-killed players weigh x0.1 as evil) is the
  strongest cheap signal.
- Determinism creates lock-ins: Monk and Imp both targeted "the most trusted player", so the Imp
  hit the protected player forever. Fix: evil remembers failed attacks. Expect more of these;
  seeded biases and memory are the tools against them.
- Bug fixed: night deaths entered the record immediately, so the Fortune Teller and Butler (who
  wake after the Imp) chose using deaths they could not know. Players now act on the dusk record.
- Symmetric skill moved balance to good wins 63% at 7 players, 60% at 8, 50% at 10 (30 seeds).
- Skill still is not symmetric in *effect*: all-novice tables favour good (65%), all-veteran
  favour evil (60%), at 8 players. Evil skill = better lies; good "skill" = considering more
  excuses, which widens the world set and makes players less decisive. Good veterans need real
  tools: informative Fortune Teller pairs, Virgin tests, tracking who pushed failed executions.
- Added those three tools as profile dials (`ft_split`, `tests_virgin`, `vote_memory`). Ablation
  over 100 all-veteran games at 8 players: each is within noise (+-5). What mattered was Occam:
  a veteran who *considers* more excuses but weighs them like everything else drowns in exotic
  worlds (max_excuses 3 -> 1 alone raised good 42 -> 50). Discounting excuses harder (poison x0.1,
  misregistration and Drunk x0.2) gets the same gain without blinding them.
- Good wins per 100 games at 8 players: novice tables 63, regular 61, veteran 50, mixed 57.
  Evil lookahead (lies tested: 6 vs 3) is worth ~8 points by itself.
- Bug fixed: Python randomises string hashing per process, and option lists were built by
  iterating a set of role names, so "same seed, same game" only held within one process.
  Now sorted, with a cross-process test.
- The public read is gamed by evil's lookahead: lies tested against the town's exact solver
  leave the town's top suspect evil no more often than chance (8 players, day 1: 22% vs 25%
  baseline; with lookahead 1 for everyone, 33%). Kept as is for now (owner's choice); the
  redesign below removes the cause.
- At 10 players good wins only ~30% and executions hit evil below chance; neither FREE nor
  lookahead explains it fully. 12-15 player games take minutes of solver time.

## Next architecture: reason like a human player

The world solver enumerates every possible grimoire. That is not how anyone plays, it does not
scale past 10 players, and it hands evil an exact model of the town to optimise against. The
plan replaces it with the reasoning a real player does at the table. The current solver stays as
an offline referee for the arena (to measure what the AI misses), not as anyone's brain.

### Principles

1. **Everyone knows every rule.** Novices included: Baron Outsiders, Recluse and Spy
   registration, star-pass, Scarlet Woman, poison and Drunk, peaceful nights needing a Monk or
   Soldier. One shared rulebook drives every player. Skill is how well you *think* with the
   rules, never which rules you know.
2. **Perfect memory of the public record** (unchanged). Skill is interpretation.
3. **Same skill dials for both teams.** A veteran Demon thinks exactly as well as a veteran
   Fortune Teller; they just want different outcomes. Evil never reads the town's minds.
4. **Characters are data.** A new script adds rows and, rarely, a rule; the reasoning, speech,
   Storyteller and UI carry over.
5. **Cost grows with the record, not with possible grimoires.** 15 players should cost about
   what 5 do, including on a phone.

### Information categories

Every ability output, claim and game event is a statement about the grimoire, in one of four
categories. Each category has a truth check (used for theories) and standard human inferences
(used for the notebook).

| Category | Form | Trouble Brewing | Typical inferences |
|---|---|---|---|
| Identity | x's character is in set S | Washerwoman, Librarian, Investigator, Undertaker, Ravenkeeper, every claim | a ping on someone who claims that character supports both; a ping nobody fits is a clash |
| Count | evil players in group G = k | Chef, Empath | Empath 0 clears both neighbours; 1 splits suspicion |
| Demon test | the Demon (or a decoy) is in G | Fortune Teller, Slayer shot, Virgin trigger | "yes" taints both; "no" clears both a bit; a Virgin trigger confirms two players |
| Event | who died, survived, or was protected, and how | night deaths, executions, Monk, Soldier, Mayor | a night death is probably good; a survived attack backs a Monk or Soldier |

Later scripts mostly reuse these: Clockmaker, Oracle and Mathematician are Count; Dreamer is
Identity; Seamstress is a Demon/alignment test. New status effects (madness, droisoning) are
tokens the truth check respects, like poison and misregistration today.

### Speech acts

Everything a player says or does is one record: (speaker, audience, time, act). Private chats
are the same acts with a smaller audience.

- **Claim**: "I am character R."
- **Testimony**: "My ability showed statement P on night n."
- **Opinion**: "I suspect x because of evidence e" (e points at an earlier act or event, so every
  reason is a real notebook line).
- **Move**: nominate, vote, shoot, volunteer, propose a plan (Virgin test, holding off at four).

Translations are one template per act and category, not per character.

### How a player reasons

**Notebook.** Each act or event becomes evidence items: (source, target, direction, strength).
The strength comes from the shared rulebook, the same for everyone. Game events (deaths, Virgin
triggers, Undertaker reveals of the executed) have the game as source and are fully trusted.

**Trust flows through sources.** A player's suspicion of x is a prior plus the evidence about x,
each item weighted by how much the player trusts its source. Repeat a few rounds so discredit
spreads: if Ben clashes with Eli, Ben's accusation of Dev counts less, which in turn changes how
much Dev's info counts.

**Clashes.** The main engine of deduction. A clash is a small set of players of whom at least
one is lying, drunk or poisoned: a double claim; a ping nobody fits; a Virgin who didn't trigger
for a claimed Townsfolk; an Empath 0 next to a claimed evil. Clashes are tracked and resolved as
deaths, reveals and tests come in, and they are the best material for table talk ("either Ben or
Eli is lying, and Eli's info has held up twice").

**Theories.** A player builds a few concrete theories ("Imp is X, Minions are Y"), from their
top suspects, and checks each against the notebook with the category truth checks and the full
rulebook (setup counts, Baron, registrations, star-pass, needed poisonings). A theory needing an
excuse (a poisoning, the Drunk) costs plausibility but is allowed. This is bounded: a handful to a
few dozen theories, never millions.

**Decisions.** Nominations, votes, Slayer shots, Monk and Fortune Teller picks, and what to say
all read from suspicion, open clashes and the surviving theories, through the existing dials
(thresholds, urgency, final-four and Mayor logic).

### Skill dials (both teams)

| Dial | Novice | Veteran |
|---|---|---|
| Breadth: theories held at once | 1-2, usually "my top suspect is the Demon" | 5-10, including ones that need a poisoning or the Drunk |
| Depth: rounds of trust propagation | 1 (info taken at face value) | 3+ (discredit spreads through sources) |
| Anchoring: how fast first impressions update | slow | fully on new evidence |
| Herding: weight on the crowd's opinion | follows the loudest accusation, bandwagons votes | mostly their own read |
| Personal bias | suspects whoever accused them, trusts chat partners | mostly immune |
| Foresight: how far ahead they plan | today only | Virgin tests, saving votes for a better nominee, holding off at four, Mayor play |
| Lie craft (evil, or good bluffing) | lies on the spot, can contradict their own story | keeps the story straight and checks it against the public record |

A novice who holds one or two theories rarely gets to "maybe she's poisoned". That is a reasoning
limit, not missing knowledge, which is how real beginners play.

### Evil

Evil players keep the same notebook and read how the town sees them through it, at their own
skill. They lie with human patterns per category: confirm a harmless good player, frame someone
already doubted, or stay vague; they never frame teammates (bussing aside). Lie craft decides
whether they check a lie for clashes with what is already public. There is no search over the
town's reasoning.

### Storyteller

The Storyteller knows the grimoire, so it needs no solver. It balances by how much the town's
notebooks suspect the real Demon against a planned trajectory (low early, near certain around the
final day), and uses its existing freedoms (drunk and poisoned info, registrations, Mayor bounce,
star-pass heir) to help the side that is behind.

### Migration

1. Shared rulebook and the four category truth checks, data-driven per character; the current
   solver's checks are the reference. **Done** (`rules.py`): the engine's real and malfunctioning
   information, the solver's checks and the "frames the team" test now all come from it; 100
   arena games at 8 players match the previous batch (good 49, executions 29% evil) and the
   truth stayed among the solver's worlds in every game.
2. Notebook, trust propagation and clashes for good players, behind the existing tests; compare
   in the arena against the solver referee. **Done; the notebook is now the default reasoner**
   (`agents.REASONER`; `arena.py --reasoner solver` for the old one). Findings:
   - Evidence must cut both ways: an accuser of someone who looks good, or a voucher for someone
     who looks evil, takes part of the blame. That alone raised day-1 reads from chance to about
     double it.
   - Theories: counting every way a line-up can be explained (Drunk seats, a hidden Outsider)
     measured better than scoring a line-up by its best explanation, and choosing suspects from
     the overall ranking beat "Demon among the living, Minions anywhere".
   - Attention is limited: line-ups are thought through likeliest first until a budget of role
     assignments (`BUDGET` x breadth) is spent. At 8 players the budget never binds.
   - Speed per AI-only game: 10 players 5s (solver ~25s), 12 players 6s (~160s), 15 players 21s.
   - Accusations cite the notebook line that weighs most: a Fortune Teller YES, an Empath's
     neighbours, a clash ("their story and mine can't both be true"), accusing a good-looking
     player. A near-unanimous vote no longer counts as anyone "pushing" an execution.
   - Good wins (30 games each, 8 players 100): 5p 13, 6p 15, 7p 17, 8p 60-70%, 9p 20, 10p 14,
     11p 18, 12p 15, 13p 14, 15p 11. Executions hit evil 25-45%.
   - Evil lies are chosen by their direct effect (the notebook lines they add: clear the team,
     point at doubted good players; a little bonus for what is actually true). Before that, a
     Demon bluffing Chef or Empath said a random number and won 2 of 21 games; after, 9 of 23,
     and 8-player good wins fell to 52-60%.
   - Table talk: a player who would repeat an earlier reason agrees with its first speaker
     instead; the owner of cited info stands by it; evidence heard in private is cited as private
     so a hidden info role isn't outed.
3. Theories and decisions; then evil on the same notebook; then the Storyteller. Partly done:
   evil liars check lies like people (no new clash with what's public; veterans: some theory
   still has them honest) and pick lies by pattern (frame whoever the town already doubts, else a
   harmless confirmation); the Storyteller balances on the town's belief in the real Demon.
   Still on the solver: nothing in play; the arena's soundness check.
4. Remove the solver from play; keep it for the arena.
5. Add one character from another script to prove the design extends.

## Simplifications

- Private groups only share claims, info and suspicions; there is no persuasion or deal-making.
- At most one undetected good bluff at a time is representable; soundness tests skip states
  with more.
