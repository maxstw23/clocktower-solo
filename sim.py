"""Run one narrated game, or a batch of silent games for statistics.

    python sim.py --seed 3
    python sim.py --games 50 --players 8
"""
import argparse
import time
from collections import Counter

from botc.engine import Game


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--players", type=int, default=10)
    p.add_argument("--games", type=int, default=0, help="run this many silent games and report stats")
    p.add_argument("--check", action="store_true", help="assert the solver never eliminates the truth")
    args = p.parse_args()

    if not args.games:
        Game(args.players, args.seed, check=args.check).run()
        return

    wins, days = Counter(), []
    start = time.time()
    for seed in range(args.seed, args.seed + args.games):
        g = Game(args.players, seed, out=None, check=args.check)
        wins[g.run() or "none"] += 1
        days.append(g.day)
    print(f"{args.games} games, {args.players} players: {dict(wins)}; "
          f"mean length {sum(days) / len(days):.1f} days; {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
