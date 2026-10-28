"""Run with: python tests/test_core.py"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from botc.engine import Game  # noqa: E402
from botc.public import Death, Public, Report  # noqa: E402
from botc.worlds import Solver  # noqa: E402


def test_truth_never_eliminated():
    for players in (7, 8, 10):
        for seed in range(10):
            Game(players, seed, out=None, check=True).run()


def test_same_seed_same_game():
    logs = []
    for _ in range(2):
        lines = []
        Game(8, 5, out=lines.append).run()
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
            g = Game(8, seed, out=None, check=True, human=seat, inp=no_input, hints=True)
            assert g.run() in ("good", "evil", None)


def test_empath_zero_clears_neighbours():
    # 7 players: 5 townsfolk, 0 outsiders, 1 minion, 1 imp
    claims = ("empath", "chef", "monk", "slayer", "soldier", "virgin", "mayor")
    pub = Public(7, claims, reports=(Report(0, 1, "empath", (0,)),))
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
