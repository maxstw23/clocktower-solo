# Deterministic Blood on the Clocktower (Trouble Brewing)

Goal: a single-player game whose "fuzzy" parts (imperfect players, a balancing Storyteller) are
deterministic given a hidden seed, with no LLM in the game state.

    python play.py                    # play one seat in your browser (http://127.0.0.1:8765)
    python play.py --terminal         # or in the terminal
    python sim.py --seed 3            # one narrated all-AI game
    python sim.py --games 30 --players 8 --check
    python tests/test_core.py

## Layers

| Layer | File | Role |
|---|---|---|
| Script | `roles.py` | Trouble Brewing roles, setup counts |
| Public record | `public.py` | Claims, reported info, deaths, Slayer shots, first nominations. Immutable and hashable. |
| World solver | `worlds.py` | Every starting role assignment consistent with the record (the omniscient baseline) |
| Agents | `agents.py` | Bounded views of the solver + fixed social dials; evil theory of mind |
| Storyteller | `storyteller.py` | Picks among legal options to steer the game's tension |
| Engine | `engine.py` | Grimoire (truth), night order, day procedure, win conditions |
| Human seat | `human.py` | Same moves as an AI player; questions go to the terminal or the browser |
| Browser UI | `web.py`, `static/index.html` | Local server (standard library) and a one-page table view |

## Key abstractions

**The day.** Dawn; on day 1 an introduction round (everyone states a character or stays silent);
then a discussion round where each player speaks once (claims or changes their claim, shares what
their ability showed them, says whom they suspect and why); then nominations, each with the
nominator's reason, the nominee's defence, and a vote. Reasons are generated from the solver:
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
for drunk/poisoned players and Spy/Recluse registrations. For each such decision it samples up to
6 legal options and picks the one that keeps the town's effective number of Demon candidates
(inverse Simpson index over the reference model's worlds) closest to `1 + (alive - 2) / 2`, so
certainty should arrive around the final day.

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

## Simplifications (next steps)

- Private groups only share claims, info and suspicions; there is no persuasion or deal-making.
- No star-pass, Mayor bounce, or Spy/Recluse misregistration for the Slayer/Virgin.
- At most one undetected good bluff at a time is representable; soundness tests skip states
  with more.
- Performance: an 8-player game takes ~0.3s of AI thinking, 10 players ~9s. Most of it is
  re-solving after each new claim or report, plus Storyteller and evil lookahead.
