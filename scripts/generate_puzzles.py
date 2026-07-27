#!/usr/bin/env python3
"""Build the shipped puzzle set.

    python scripts/generate_puzzles.py --per-cell 3 --out puzzles.json

Generates a full size x difficulty matrix: `per_cell` puzzles for every board
size from 5x5 to 15x15 in each of easy/medium/hard.

Every puzzle written out has been checked twice over: the exhaustive solver
found exactly one solution, and the deduction solver reached that solution
without guessing.

Generation cost climbs very steeply with board size, so the run reports how
long each size took, both on stdout and in the "timing" block of the output
file.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from queens.board import Board  # noqa: E402
from queens.generator import (  # noqa: E402
    DIFFICULTY_BANDS,
    MAX_SIZE,
    MIN_SIZE,
    MatrixReport,
    Puzzle,
    generate_matrix,
)
from queens.logic import solve_logically  # noqa: E402
from queens.solver import find_solutions  # noqa: E402

SCHEMA_VERSION = 1


def verify(puzzle: Puzzle) -> None:
    """Re-check a puzzle from scratch before it is allowed into the file."""
    board = Board(puzzle.board.to_list())  # rebuild, so validation runs again
    solutions = find_solutions(board, limit=2)
    if len(solutions) != 1:
        raise AssertionError(
            f"{board.n}x{board.n} puzzle has {len(solutions)} solutions, expected 1"
        )
    if solutions[0] != puzzle.solution:
        raise AssertionError("recorded solution does not match the solver")
    result = solve_logically(board)
    if not result.solved:
        raise AssertionError("puzzle cannot be finished by deduction alone")
    if result.solution() != puzzle.solution:
        raise AssertionError("deduction reached a different solution")


def _describe_bands() -> dict[str, str]:
    """Turn the band cut points into readable score ranges for the file."""
    out: dict[str, str] = {}
    lower = 0
    for name, upper in DIFFICULTY_BANDS:
        out[name] = f"{lower}+" if upper == float("inf") else f"{lower}-{int(upper) - 1}"
        if upper != float("inf"):
            lower = int(upper)
    return out


def build_payload(
    report: MatrixReport, seed: int, elapsed: float, per_cell: int
) -> dict:
    puzzles = report.puzzles
    by_size: Counter[int] = Counter(p.size for p in puzzles)
    by_difficulty: Counter[str] = Counter(p.difficulty for p in puzzles)

    numbering: Counter[int] = Counter()
    entries = []
    for puzzle in puzzles:
        numbering[puzzle.size] += 1
        entries.append(
            puzzle.to_dict(f"q{puzzle.size}-{numbering[puzzle.size]:03d}")
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "rules": {
            "description": (
                "Place one queen in every row, every column and every colour "
                "region. No two queens may be diagonally adjacent."
            ),
            "regions": "regions[r][c] is the colour region id of cell (r, c)",
            "solution": "solution[r] is the column of the queen in row r",
        },
        "difficulty": {
            "metric": (
                "tier-weighted count of the deduction steps needed to solve "
                "the board without guessing"
            ),
            "tier_weights": {"1": 1, "2": 3, "3": 7, "4": 15},
            "bands": _describe_bands(),
        },
        "generator": {
            "seed": seed,
            "per_cell": per_cell,
            "elapsed_seconds": round(elapsed, 1),
            "guaranteed": [
                "exactly one solution",
                "solvable by deduction alone, no guessing",
            ],
            "timing": report.to_dict(),
        },
        "count": len(entries),
        "counts_by_size": {str(k): by_size[k] for k in sorted(by_size)},
        "counts_by_difficulty": {
            name: by_difficulty[name] for name, _ in DIFFICULTY_BANDS
        },
        "puzzles": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--per-cell",
        type=int,
        default=3,
        help="puzzles per (size, difficulty) cell of the matrix",
    )
    parser.add_argument("--out", type=Path, default=Path("puzzles.json"))
    parser.add_argument("--seed", type=int, default=20240517)
    parser.add_argument("--min-size", type=int, default=MIN_SIZE)
    parser.add_argument("--max-size", type=int, default=MAX_SIZE)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    sizes = tuple(range(args.min_size, args.max_size + 1))
    started = time.time()
    report = generate_matrix(
        per_cell=args.per_cell,
        sizes=sizes,
        seed=args.seed,
        progress=not args.quiet,
    )
    elapsed = time.time() - started

    puzzles = report.puzzles
    for puzzle in puzzles:
        verify(puzzle)

    payload = build_payload(report, args.seed, elapsed, args.per_cell)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"\nwrote {len(puzzles)} puzzles to {args.out} in {elapsed:.1f}s")
    print(f"  by difficulty: {payload['counts_by_difficulty']}")
    print()
    print("  generation time by size")
    print(f"    {'size':>5} {'puzzles':>8} {'total':>9} {'each':>8}  {'failed':>6}")
    for size, row in sorted(report.by_size().items()):
        print(
            f"    {size:>3}x{size:<2} {row['produced']:>6} "
            f"{row['seconds']:>8.1f}s {row['seconds_each']:>7.2f}s "
            f"{row['failed']:>7}"
        )
    missing = sum(c.failures for c in report.cells)
    if missing:
        print(f"\n  {missing} requested puzzle(s) could not be generated:")
        for cell in report.cells:
            if cell.failures:
                print(
                    f"    {cell.size}x{cell.size} {cell.difficulty}: "
                    f"{cell.produced}/{cell.requested}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
