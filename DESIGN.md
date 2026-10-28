# Deterministic Blood on the Clocktower (Trouble Brewing)

Goal: a single-player game whose "fuzzy" parts (imperfect players, a balancing Storyteller) are
deterministic given a hidden seed, with no LLM in the game state.

    python play.py --hints            # play one seat (add --seed N --seat K to replay)
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
| Human seat | `human.py` | Same moves as an AI player, asked on the terminal; every prompt has a default |

## Key abstractions

**Worlds and excuses.** A world is a starting role assignment. Records that contradict a sober
good player need an *excuse*: a poisoning (at most one per night, Poisoner alive), a Spy/Recluse
misregistration, or the Drunk. Each world records the excuses it needs.

**Imperfect players = restricted solver.** A `Profile` sets which excuses a player thinks of
(poison / Drunk / misregistration) and how many they tolerate (`max_excuses`). If nothing fits,
they widen their assumptions (`Belief.relaxed`), which is the moment a novice says "oh, someone
must be poisoned". Mistakes come from these blind spots, not dice.

**Integer-ish suspicion.** `suspicion = (2*demon% + evil%) / 3` over the worlds a player
considers. Nominations and votes compare it to thresholds that drop with `urgency` per day, with
`bandwagon` per yes vote, and to zero when four or fewer players are alive. A player votes only
for someone more suspicious than whoever is already on the block.

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

- Everyone hard-claims on day 1; all info is public. Next: private whispers and an
  information-reach dial, so players hold different records.
- No star-pass, Mayor bounce, or Spy/Recluse misregistration for the Slayer/Virgin.
- Evil reports are scored against the reference model only, not each player's profile.
- Human seat: a good human must claim truthfully and their info is reported as received
  (the solver assumes good players don't lie). Evil humans choose their claim and their fake
  info freely. `--hints` shows a veteran's read; NPCs don't talk yet beyond their moves.
- Performance: about 2s per 10-player game, about 10s at 12 players. Most of it is
  Storyteller/evil lookahead re-checking worlds.
