"""Play one seat at a table of AI players.

    python play.py                 # opens the game in your browser
    python play.py --terminal      # plays in the terminal instead
"""
import argparse
import random

from botc.engine import Game


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--terminal", action="store_true", help="play in the terminal instead of the browser")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--seed", type=int, help="terminal: replay a specific game")
    p.add_argument("--players", type=int, default=8)
    p.add_argument("--seat", type=int, help="terminal: your seat (default: chosen by the seed)")
    p.add_argument("--name", help="terminal: your name")
    p.add_argument("--hints", action="store_true", help="terminal: show a veteran's read each day")
    args = p.parse_args()
    if not args.terminal:
        from botc.web import serve
        serve(args.port)
        return
    seed = args.seed if args.seed is not None else random.randrange(10**6)
    seat = args.seat if args.seat is not None else random.Random(f"seat-{seed}").randrange(args.players)
    print(f"Blood on the Clocktower, Trouble Brewing: game #{seed}, {args.players} players.")
    print("Type a name (or its first letters) to choose a player; Enter takes the default.")
    print("Type 'notes' (or '?') at any prompt to see everything said and done so far.\n")
    Game(args.players, seed, human=seat, hints=args.hints, name=args.name).play()


if __name__ == "__main__":
    main()
