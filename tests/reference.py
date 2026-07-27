"""A deliberately naive, independent solver used only by the tests.

:mod:`queens.solver` is heavily pruned, so checking uniqueness with it alone
would only prove it agrees with itself. This module enumerates placements the
dumbest way possible -- every permutation of columns, filtered by the rules
read straight off the puzzle statement -- so it shares no logic with the code
under test.
"""

from __future__ import annotations

from itertools import permutations
from typing import Sequence

Solution = tuple[int, ...]


def brute_force_solutions(regions: Sequence[Sequence[int]]) -> list[Solution]:
    """Every legal queen placement, found by trying all column permutations."""
    n = len(regions)
    out: list[Solution] = []
    for perm in permutations(range(n)):
        # One queen per row and column is guaranteed by using a permutation.
        if len({regions[r][c] for r, c in enumerate(perm)}) != n:
            continue
        if any(abs(perm[r] - perm[r + 1]) == 1 for r in range(n - 1)):
            continue
        out.append(perm)
    return out


def is_legal(regions: Sequence[Sequence[int]], queens: Sequence[int]) -> bool:
    """Independent re-statement of the rules, for checking a single placement."""
    n = len(regions)
    if len(queens) != n or any(not 0 <= c < n for c in queens):
        return False
    if len(set(queens)) != n:  # one per column (one per row is implicit)
        return False
    if len({regions[r][queens[r]] for r in range(n)}) != n:
        return False
    for a in range(n):
        for b in range(a + 1, n):
            if abs(a - b) <= 1 and abs(queens[a] - queens[b]) <= 1:
                return False
    return True
