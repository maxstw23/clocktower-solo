"""Self-play arena: play many games and report how the table behaves, to spot what looks wrong.

    python arena.py --games 100              # statistics over 100 games (8 players, mixed skill)
    python arena.py --games 60 --show 3      # ... and print game 3 of the batch in Chinese
"""
import argparse
import time
from collections import Counter

from botc import agents
from botc.engine import Game

INFO = ("washerwoman", "librarian", "investigator", "chef", "empath", "fortune_teller", "undertaker", "ravenkeeper")


def said(g, key):
    """Lines spoken (or announced) with this message key."""
    out = []
    for e in g.log:
        m = e["m"]
        inner = m.args.get("text") if m.key == "speech" else None
        if m.key == key or getattr(inner, "key", None) == key:
            out.append(e)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--games", type=int, default=100)
    p.add_argument("--players", type=int, default=8)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--show", type=int, help="print this game of the batch in Chinese")
    p.add_argument("--reasoner", choices=("solver", "notebook"), default=agents.REASONER)
    args = p.parse_args()
    agents.REASONER = args.reasoner

    c = Counter()
    start = time.time()
    for i, seed in enumerate(range(args.seed, args.seed + args.games)):
        g = Game(args.players, seed, out=None, check=True)
        c["win_" + str(g.play())] += 1
        c["days"] += g.day
        execs = [d for d in g.pub.deaths if d.cause == "execution"]
        c["executions"] += len(execs)
        c["exec_evil"] += sum(d.seat in g.team for d in execs)
        c["exec_honest_info"] += sum(d.seat not in g.team and g.roles[d.seat] in INFO for d in execs)
        exec_days = {d.tick // 2 for d in execs}
        c["days_without_execution"] += sum(1 for d in range(1, g.day + 1) if d not in exec_days and
                                           not (d == g.day and g.winner))
        c["endgame_ties"] += sum(1 for e in said(g, "votes_tie")
                                 if g.n - sum(d.tick < 2 * e["day"] for d in g.pub.deaths) <= 4)
        c["virgin_plans"] += len(said(g, "virgin_plan")) + len(said(g, "virgin_plan_self"))
        c["virgin_tests"] += len(said(g, "nominates_test"))
        c["virgin_triggered"] += sum(fn.triggered for fn in g.pub.first_noms)
        c["virgin_deflected"] += len(said(g, "virgin_deflect"))
        c["virgin_smeared"] += len(said(g, "smear_virgin"))
        c["offers"] += len(said(g, "volunteer"))
        c["offers_taken"] += len(said(g, "nominates_self")) + len(said(g, "nominates_offer"))
        c["counterclaims"] += len(said(g, "counter"))
        c["quiet"] += len(said(g, "stay_quiet"))
        c["mayor_wins"] += len(said(g, "mayor_win"))
        if args.show == i:
            for e in g.log:
                tag = "【私聊】" if e["chat"] else "【仅我】" if e["private"] else ""
                print(tag + g.text(e["m"], "zh").strip())
            print()
    n = args.games
    print(f"{n} games, {args.players} players, {time.time() - start:.0f}s")
    print(f"  good wins {c['win_good']}/{n}, mean length {c['days'] / n:.1f} days")
    print(f"  executions {c['executions']}: {c['exec_evil']} evil ({100 * c['exec_evil'] // max(1, c['executions'])}%), "
          f"{c['exec_honest_info']} good info roles; days without an execution {c['days_without_execution']}")
    print(f"  endgame ties {c['endgame_ties']}; counterclaims {c['counterclaims']}; quiet claims {c['quiet']}")
    print(f"  Virgin: proposed {c['virgin_plans']}, tested {c['virgin_tests']}, triggered {c['virgin_triggered']}, "
          f"deflected by evil {c['virgin_deflected']}, smeared {c['virgin_smeared']}")
    print(f"  offers to be executed {c['offers']}, taken up {c['offers_taken']}; Mayor wins {c['mayor_wins']}")


if __name__ == "__main__":
    main()
