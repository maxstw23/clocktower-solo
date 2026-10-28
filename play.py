"""Play one seat at a table of AI players.

    python play.py                 # random seed and seat
    python play.py --seed 7 --seat 3 --players 8 --hints
"""
import argparse
import random

from botc.engine import Game


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, help="replay a specific game")
    p.add_argument("--players", type=int, default=8)
    p.add_argument("--seat", type=int, help="your seat (default: chosen by the seed)")
    p.add_argument("--hints", action="store_true", help="show a veteran's read of the record each day")
    args = p.parse_args()
    seed = args.seed if args.seed is not None else random.randrange(10**6)
    seat = args.seat if args.seat is not None else random.Random(f"seat-{seed}").randrange(args.players)
    print(f"Blood on the Clocktower, Trouble Brewing: seed {seed}, {args.players} players.")
    print("Type a name (or its first letters) to choose a player; Enter takes the default.")
    print("Type 'notes' (or '?') at any prompt to see everything said and done so far.\n")
    Game(args.players, seed, human=seat, hints=args.hints).run()


if __name__ == "__main__":
    main()
