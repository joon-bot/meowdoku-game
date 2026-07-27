"""Exhaustive solver for Queens-style boards.

The search walks the board one row at a time. Because every row holds exactly
one queen, a partial state is fully described by the set of used columns, the
set of used colour regions and the column chosen in the previous row (the only
row that can be diagonally adjacent to the current one). Both sets fit in a
machine word for the board sizes we care about, so they are kept as bitmasks.
"""

from __future__ import annotations

from typing import Sequence

from .board import Board

Solution = tuple[int, ...]


def find_solutions(board: Board, limit: int | None = None) -> list[Solution]:
    """Return solutions as column-per-row tuples, at most ``limit`` of them.

    Passing ``limit=2`` is the cheap way to answer "is this puzzle unique?" --
    the search stops as soon as a second solution turns up.
    """
    n = board.n
    regions = board.regions
    solutions: list[Solution] = []
    partial: list[int] = []

    # Per row, the cells ordered by how constrained their region is, with the
    # column and region bits precomputed. Trying cells from small regions
    # first prunes the tree noticeably on 8x8 and 9x9.
    region_size = [len(cells) for cells in board.region_cells]
    row_cells: list[tuple[tuple[int, int, int], ...]] = [
        tuple(
            (col, 1 << col, 1 << regions[r][col])
            for col in sorted(range(n), key=lambda c, r=r: region_size[regions[r][c]])
        )
        for r in range(n)
    ]

    # ``alive_from[r]`` holds the regions that still have at least one cell in
    # rows r..n-1. A region outside that set which has not been used yet can
    # never be filled, so the branch is dead. Checking it is a single mask
    # comparison and it cuts the search tree hard on larger boards.
    full = (1 << n) - 1
    # Columns banned in the next row by a queen sitting in column ``c``.
    diag_ban = [0] * n
    for c in range(n):
        if c > 0:
            diag_ban[c] |= 1 << (c - 1)
        if c + 1 < n:
            diag_ban[c] |= 1 << (c + 1)

    alive_from = [0] * (n + 1)
    for r in range(n - 1, -1, -1):
        mask = alive_from[r + 1]
        for c in range(n):
            mask |= 1 << regions[r][c]
        alive_from[r] = mask

    def recurse(row: int, used_cols: int, used_regions: int, prev_col: int) -> None:
        if row == n:
            solutions.append(tuple(partial))
            return
        if used_regions | alive_from[row] != full:
            return
        # Columns still free, minus the two that would touch the previous
        # row's queen diagonally.
        blocked = used_cols if prev_col < 0 else used_cols | diag_ban[prev_col]
        for col, col_bit, region_bit in row_cells[row]:
            if blocked & col_bit or used_regions & region_bit:
                continue
            partial.append(col)
            recurse(row + 1, used_cols | col_bit, used_regions | region_bit, col)
            partial.pop()
            if limit is not None and len(solutions) >= limit:
                return

    recurse(0, 0, 0, -1)
    return solutions


def solve(board: Board) -> Solution | None:
    """Return one solution, or ``None`` if the board has none."""
    found = find_solutions(board, limit=1)
    return found[0] if found else None


def count_solutions(board: Board, cap: int = 2) -> int:
    """Number of solutions, counted up to ``cap``."""
    return len(find_solutions(board, limit=cap))


def has_unique_solution(board: Board) -> bool:
    return count_solutions(board, cap=2) == 1


def solve_with_placements(
    board: Board, placements: Sequence[tuple[int, int]], limit: int | None = None
) -> list[Solution]:
    """Solutions consistent with a set of already-placed queens.

    Used by the tests to confirm that a partially solved position still has
    exactly the solutions we expect.
    """
    n = board.n
    fixed: dict[int, int] = {}
    for r, c in placements:
        if r in fixed and fixed[r] != c:
            return []
        fixed[r] = c

    regions = board.regions
    solutions: list[Solution] = []
    partial: list[int] = []

    def recurse(row: int, used_cols: int, used_regions: int, prev_col: int) -> None:
        if row == n:
            solutions.append(tuple(partial))
            return
        candidates = [fixed[row]] if row in fixed else range(n)
        for col in candidates:
            if used_cols >> col & 1:
                continue
            region = regions[row][col]
            if used_regions >> region & 1:
                continue
            if prev_col >= 0 and abs(prev_col - col) == 1:
                continue
            partial.append(col)
            recurse(row + 1, used_cols | 1 << col, used_regions | 1 << region, col)
            partial.pop()
            if limit is not None and len(solutions) >= limit:
                return

    recurse(0, 0, 0, -1)
    return solutions
