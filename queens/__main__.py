"""Command line entry point: ``python -m queens ...``

    python -m queens generate 7 --difficulty hard
    python -m queens show q6-004
    python -m queens solve q6-004 --explain
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from .board import Board
from .generator import MAX_SIZE, MIN_SIZE, generate_puzzle
from .logic import explain, solve_logically
from .solver import find_solutions

PUZZLES_PATH = Path(__file__).resolve().parent.parent / "puzzles.json"


def _load_entry(puzzle_id: str) -> dict:
    if not PUZZLES_PATH.exists():
        raise SystemExit(
            f"{PUZZLES_PATH} not found -- run scripts/generate_puzzles.py first"
        )
    data = json.loads(PUZZLES_PATH.read_text())
    for entry in data["puzzles"]:
        if entry["id"] == puzzle_id:
            return entry
    raise SystemExit(f"no puzzle with id {puzzle_id!r} in {PUZZLES_PATH.name}")


def _print(board: Board, solution=None, header: str = "") -> None:
    if header:
        print(header)
    print(board.render())
    if solution is not None:
        print()
        print(board.render(solution))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="queens", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="generate a puzzle")
    gen.add_argument("size", type=int, choices=range(MIN_SIZE, MAX_SIZE + 1))
    gen.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    gen.add_argument("--seed", type=int)
    gen.add_argument("--explain", action="store_true")

    show = sub.add_parser("show", help="print a puzzle from puzzles.json")
    show.add_argument("puzzle_id")
    show.add_argument("--solution", action="store_true")

    solver = sub.add_parser("solve", help="solve a puzzle from puzzles.json")
    solver.add_argument("puzzle_id")
    solver.add_argument("--explain", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "generate":
        rng = random.Random(args.seed)
        puzzle = generate_puzzle(args.size, rng=rng, difficulty=args.difficulty)
        _print(
            puzzle.board,
            puzzle.solution,
            f"{puzzle.size}x{puzzle.size} {puzzle.difficulty} "
            f"(steps {puzzle.steps}, score {puzzle.score}, "
            f"max tier {puzzle.max_tier})\n",
        )
        if args.explain:
            print()
            print(explain(puzzle.board))
        return 0

    entry = _load_entry(args.puzzle_id)
    board = Board(entry["regions"])

    if args.command == "show":
        _print(
            board,
            entry["solution"] if args.solution else None,
            f"{entry['id']}  {entry['size']}x{entry['size']}  {entry['difficulty']}\n",
        )
        return 0

    solutions = find_solutions(board, limit=2)
    print(f"{entry['id']}: {len(solutions)} solution(s)"
          f"{' (unique)' if len(solutions) == 1 else ''}")
    result = solve_logically(board)
    print(
        f"deduction: {'solved' if result.solved else 'stalled'}, "
        f"{result.step_count} steps, score {result.score}, "
        f"max tier {result.max_tier}"
    )
    print()
    print(board.render(result.solution() or entry["solution"]))
    if args.explain:
        print()
        print(explain(board, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
