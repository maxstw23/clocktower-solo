"""Run with: python tests/test_core.py"""
import os
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from botc.engine import Game  # noqa: E402
from botc.human import TerminalIO  # noqa: E402
from botc import notebook, rules  # noqa: E402
from botc.public import Death, Public, Report  # noqa: E402
from botc.worlds import Solver  # noqa: E402


def test_truth_never_eliminated():
    for players in (7, 8, 10):
        for seed in range(10):
            Game(players, seed, out=None, check=True).play()


def test_same_seed_same_game():
    logs = []
    for _ in range(2):
        lines = []
        Game(8, 5, out=lines.append).play()
        logs.append(lines)
    assert logs[0] == logs[1]


def test_same_seed_same_game_across_processes():
    # String hashing is randomised per process; nothing may depend on set order of role names.
    root = os.path.join(os.path.dirname(__file__), "..")
    outs = [subprocess.run([sys.executable, "sim.py", "--seed", "4", "--players", "8"], cwd=root,
                           env={**os.environ, "PYTHONHASHSEED": h}, capture_output=True, text=True).stdout
            for h in ("1", "2", "3")]
    assert outs[0] and outs[0] == outs[1] == outs[2]


def test_human_seat_with_default_answers():
    def no_input(prompt):
        raise EOFError
    for seed in range(4):
        for seat in range(8):
            g = Game(8, seed, out=None, check=True, human=seat, hints=True,
                     io=TerminalIO(inp=no_input, out=lambda msg: None))
            assert g.play() in ("good", "evil", None)


def test_changing_your_claim_costs_trust():
    from botc.agents import REFERENCE, believe
    claims = ("empath", "chef", "monk", "slayer", "soldier", "virgin", "mayor")
    honest = Public(7)
    for s, c in enumerate(claims):
        honest = honest.claim(1, s, c)
    switched = Public(7).claim(1, 0, "mayor")
    for s, c in enumerate(claims[1:], 1):
        switched = switched.claim(1, s, c)
    switched = switched.claim(2, 0, "empath")  # same final claims, but seat 0 lied first
    solver = Solver()
    before = believe(solver, honest, REFERENCE).evil_pct(0)
    after = believe(solver, switched, REFERENCE).evil_pct(0)
    assert after > before


def test_double_claim_allows_a_good_bluffer():
    # Two Empaths: either may be the good bluffer, so neither is forced to be evil.
    claims = ("empath", "chef", "monk", "slayer", "soldier", "virgin", "empath")
    pub = Public(7)
    for s, c in enumerate(claims):
        pub = pub.claim(1, s, c)
    worlds = Solver().worlds(pub)
    assert any(w.bluffs == 1 and w.roles[0] == "?townsfolk" for w in worlds)
    assert any(w.bluffs == 1 and w.roles[6] == "?townsfolk" for w in worlds)


def _keys(m, out):
    from botc.i18n import L, M
    if isinstance(m, M):
        out.add(m.key)
        for a in m.args.values():
            _keys(a, out)
    elif isinstance(m, L):
        for x in m.items:
            _keys(x, out)
    return out


def test_every_message_exists_in_both_languages():
    from botc.i18n import TEXT
    keys = set()

    class Recorder(TerminalIO):
        def _ask(self, prompt, parse, default):
            return default
        def choose(self, prompt, labels, default=0):
            for m in [prompt, *labels]:
                _keys(m, keys)
            return default
        def seat(self, prompt, seats, default=None):
            _keys(prompt, keys)
            return default
        def seats(self, prompt, seats, k, default):
            _keys(prompt, keys)
            return list(default)
        def yes_no(self, prompt, default=False):
            _keys(prompt, keys)
            return default

    for seed in range(6):
        for seat in (0, 3):
            g = Game(8, seed, out=None, human=seat, hints=True, io=Recorder(out=lambda m: None))
            g.play()
            for e in g.log:
                _keys(e["m"], keys)
            for m in g.notebook():
                _keys(m, keys)
    missing = {lang: sorted(k for k in keys if k not in TEXT[lang]) for lang in TEXT}
    assert not any(missing.values()), missing


def test_evil_human_can_steer_the_kill():
    from botc.engine import Game as G
    from botc.public import night_tick
    for seed in range(40):
        probe = G(8, seed, out=None)
        minion = next((s for s in probe.team if s != probe.demon), None)
        if minion is None:
            continue

        class Plotter(TerminalIO):
            target = None
            def choose(self, prompt, labels, default=0):
                if prompt.key == "q_aside":
                    return 1
                if prompt.key == "q_chat":
                    keys = [l.key for l in labels]
                    if "c_kill" in keys and self.target is None:
                        return keys.index("c_kill")
                    return keys.index("c_done")
                return default
            def seat(self, prompt, seats, default=None):
                if prompt.key == "q_invite":
                    return probe.demon
                if prompt.key == "q_kill_suggest":
                    Plotter.target = seats[-1]
                    return seats[-1]
                return default
            def seats(self, prompt, seats, k, default):
                return list(default)
            def yes_no(self, prompt, default=False):
                return default

        io = Plotter(out=lambda m: None)
        g = G(8, seed, out=None, human=minion, io=io)
        g.play()
        if Plotter.target is None or g.day < 1:
            continue
        night2 = [d.seat for d in g.pub.deaths if d.cause == "night" and d.tick == night_tick(2)]
        protected = any(Plotter.target == r.data[0] for r in g.pub.reports if r.kind == "monk" and r.night == 2)
        if night2 or not protected:
            assert night2 == [Plotter.target] or g.roles[Plotter.target] == "soldier" or g.winner
        return
    raise AssertionError("no seed with an evil minion seat")


class _Scripted(TerminalIO):
    """Accept invitations, claim a chosen character, otherwise take defaults; record what is offered."""
    def __init__(self, claim=None):
        super().__init__(out=lambda m: None)
        self.claim, self.offered = claim, []
    def choose(self, prompt, labels, default=0):
        if prompt.key == "q_which_char":
            self.offered = [l.key for l in labels]
            if self.claim:
                return next(i for i, l in enumerate(labels) if l.args["role"].role == self.claim)
        return default
    def seat(self, prompt, seats, default=None):
        return default
    def seats(self, prompt, seats, k, default):
        return list(default)
    def yes_no(self, prompt, default=False):
        return prompt.key == "q_accept"


def test_demon_briefs_a_human_minion_on_day_one():
    for seed in range(30):
        probe = Game(8, seed, out=None)
        minion = next(s for s in probe.team if s != probe.demon)
        io = _Scripted()
        g = Game(8, seed, out=None, human=minion, io=io)
        g.play()
        day1 = [e for e in g.log if e["chat"] and e["m"].key == "speech"
                and e["m"].args["text"].key == "e_bluff_for_you"]
        assert day1, f"seed {seed}: no bluff handed over"
        assert g.human_bluff and g.human_bluff not in [g.planned_claims[s] for s in g.team if s != minion]
    assert "lbl_given" in io.offered


def test_real_holder_calls_out_a_false_claim():
    called = 0
    for seed in range(20):
        probe = Game(8, seed, out=None)
        holders = {probe.perceived[s]: s for s in range(8) if s not in probe.team and probe.roles[s] != "drunk"}
        me = next(s for s in range(8) if s not in probe.team and probe.roles[s] != "drunk")
        stolen = next(r for r, s in holders.items() if s != me)
        g = Game(8, seed, out=None, human=me, io=_Scripted(claim=stolen))
        g.play()
        counters = [e for e in g.log if e["m"].key == "speech" and e["m"].args["text"].key == "counter"
                    and e["m"].args["text"].args["t"].seat == me]
        called += bool(counters)
    assert called >= 15, called


def test_empath_zero_clears_neighbours():
    # 7 players: 5 townsfolk, 0 outsiders, 1 minion, 1 imp
    claims = ("empath", "chef", "monk", "slayer", "soldier", "virgin", "mayor")
    pub = Public(7, claims, reports=(Report(0, 1, "empath", (0,)),))  # claims given directly, no history
    worlds = [w for w in Solver().worlds(pub) if w.excuses == 0 and w.roles[0] == "empath"]
    assert worlds and all(w.demon not in (1, 6) for w in worlds)


def test_night_death_is_not_the_demon():
    claims = ("empath", "chef", "monk", "slayer", "soldier", "virgin", "mayor")
    pub = Public(7, claims, deaths=(Death(3, 3, "night"),))
    assert all(w.demon != 3 for w in Solver().worlds(pub))


def test_dead_soldier_needs_an_excuse():
    claims = ("empath", "chef", "monk", "slayer", "soldier", "virgin", "mayor")
    pub = Public(7, claims, deaths=(Death(4, 3, "night"),))
    for w in Solver().worlds(pub):
        if w.roles[4] == "soldier":
            assert w.poison_nights == 1 and w.roles.count("poisoner") == 1


def test_rulebook_truth_check():
    # 6 players: seat 1 is the Imp, seat 3 the Spy, seat 4 the Recluse.
    roles = ("empath", "imp", "chef", "spy", "recluse", "washerwoman")
    view = SimpleNamespace(n=6, role_at=lambda s, t: roles[s], demon_at=lambda t: 1,
                                 alive_after=lambda t: range(6), could_be=lambda s, r: roles[s] == r,
                                 red_herring=None)

    def truth(seat, kind, data):
        return rules.truth(Report(seat, 1, kind, data), view)
    assert truth(5, "washerwoman", (0, 2, "empath")) == rules.OK
    assert truth(5, "washerwoman", (3, 2, "monk")) == rules.MISREG  # the Spy may show up as a Townsfolk
    assert truth(5, "washerwoman", (2, 4, "monk")) == rules.FAIL
    assert truth(0, "empath", (1,)) == rules.OK       # neighbours: seat 5 (good) and seat 1 (Imp)
    assert truth(0, "fortune_teller", (2, 4, True)) == rules.MISREG  # the Recluse may read as the Demon
    assert truth(0, "fortune_teller", (1, 2, False)) == rules.FAIL
    # Real information is exactly the candidates that are true; a drunk never sees their own character.
    real = [d for d in rules.candidates("washerwoman", 6, 5) if truth(5, "washerwoman", d) != rules.FAIL]
    assert (0, 2, "empath") in real and (2, 4, "monk") not in real
    assert rules.names_own_character("washerwoman", (0, 2, "washerwoman"))
    assert not rules.names_own_character("washerwoman", (0, 2, "empath"))


def test_notebook_evidence_cuts_both_ways():
    # 8 players. Seat 2 (Investigator) says seat 5 or 6 is the Poisoner; seat 5 then dies at night,
    # so seat 5 looks good and the accusation falls back on seat 2.
    claims = ("empath", "chef", "investigator", "monk", "soldier", "slayer", "mayor", "virgin")
    pub = Public(8, claims, reports=(Report(2, 1, "investigator", (5, 6, "poisoner")),))
    before = notebook.suspicions(pub, depth=3)
    after = notebook.suspicions(replace(pub, deaths=(Death(5, 3, "night"),)), depth=3)
    assert before[6] > before[0] and after[5] < before[5] and after[2] > before[2]
    # Empath 0: both neighbours look good.
    pub = Public(8, claims, reports=(Report(0, 1, "empath", (0,)),))
    p = notebook.suspicions(pub, depth=2)
    assert p[1] < p[3] and p[7] < p[3]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
