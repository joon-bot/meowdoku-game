#!/usr/bin/env python3
"""Sample generated boards and report the deduction-score distribution.

This is what the difficulty cut points in :data:`queens.generator.DIFFICULTY_BANDS`
were read off. Run it again after changing a deduction rule -- the tier
weights feed straight into the score, so a rule change moves the bands.

    python scripts/calibrate.py --per-size 120
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from queens.generator import (  # noqa: E402
    MAX_SIZE,
    MIN_SIZE,
    _local_search,
    _make_puzzle,
    classify,
)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = min(int(q * len(ordered)), len(ordered) - 1)
    return ordered[idx]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-size", type=int, default=120)
    parser.add_argument(
        "--large-per-size",
        type=int,
        default=20,
        help="sample size above the counting-objective crossover, where each "
        "board costs seconds rather than milliseconds",
    )
    parser.add_argument("--seed", type=int, default=2024)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    all_indices: list[int] = []
    print(f"{'n':>2}  {'kept':>5}  {'p10':>6} {'p33':>6} {'p50':>6} {'p66':>6} {'p90':>6}"
          f"  {'mean':>6}  {'maxtier':>18}")
    for n in range(MIN_SIZE, MAX_SIZE + 1):
        wanted = args.per_size if n <= 10 else args.large_per_size
        indices: list[int] = []
        tiers: Counter[int] = Counter()
        steps: list[int] = []
        while len(indices) < wanted:
            found = _local_search(n, rng)
            if found is None:
                continue
            puzzle = _make_puzzle(*found)
            indices.append(puzzle.score)
            steps.append(puzzle.steps)
            tiers[puzzle.max_tier] += 1
        all_indices.extend(indices)
        tier_summary = " ".join(f"T{t}:{c}" for t, c in sorted(tiers.items()))
        print(
            f"{n:>2}  {len(indices):>5}  "
            f"{percentile(indices, 0.10):>6.1f} {percentile(indices, 0.33):>6.1f} "
            f"{percentile(indices, 0.50):>6.1f} {percentile(indices, 0.66):>6.1f} "
            f"{percentile(indices, 0.90):>6.1f}  "
            f"{statistics.mean(indices):>6.1f}  {tier_summary:>18}"
            f"   steps~{statistics.median(steps):.0f}"
        )

    print()
    print("pooled deduction-score percentiles")
    for q in (0.1, 0.2, 1 / 3, 0.5, 2 / 3, 0.8, 0.9):
        print(f"  p{q * 100:>4.0f}: {percentile(all_indices, q):.1f}")
    print()
    print("classification with the current bands:")
    counts = Counter(classify(score) for score in all_indices)
    print("  ", {k: counts[k] for k in ("easy", "medium", "hard")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
