"""Board representation for Queens-style logic puzzles.

Rules implemented throughout this package:

* The board is an ``n x n`` grid partitioned into exactly ``n`` colour regions.
* Exactly one queen goes in every row, every column and every colour region.
* No two queens may be diagonally adjacent.

Two queens can never be orthogonally adjacent either, because that would put
them in the same row or column, so the diagonal rule is the only adjacency
constraint that needs to be checked explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator, Sequence

Cell = tuple[int, int]

# All eight king-move offsets. Only the four diagonals matter for the
# adjacency rule, but the full neighbourhood is handy when computing the set of
# cells a queen attacks.
DIAGONALS: tuple[Cell, ...] = ((-1, -1), (-1, 1), (1, -1), (1, 1))
ORTHOGONALS: tuple[Cell, ...] = ((-1, 0), (1, 0), (0, -1), (0, 1))


class InvalidBoardError(ValueError):
    """Raised when a region map does not describe a legal puzzle board."""


@dataclass(frozen=True)
class Board:
    """An ``n x n`` grid whose cells are labelled with a region id in ``0..n-1``."""

    regions: tuple[tuple[int, ...], ...]

    # Derived, cached at construction time.
    n: int = field(init=False)
    region_cells: tuple[tuple[Cell, ...], ...] = field(init=False)

    def __init__(self, regions: Sequence[Sequence[int]]) -> None:
        grid = tuple(tuple(int(v) for v in row) for row in regions)
        object.__setattr__(self, "regions", grid)
        object.__setattr__(self, "n", len(grid))
        self.validate()
        buckets: list[list[Cell]] = [[] for _ in range(self.n)]
        for r, row in enumerate(grid):
            for c, region in enumerate(row):
                buckets[region].append((r, c))
        object.__setattr__(
            self, "region_cells", tuple(tuple(cells) for cells in buckets)
        )

    # ------------------------------------------------------------------
    # Construction / serialisation
    # ------------------------------------------------------------------
    @classmethod
    def from_rows(cls, rows: Sequence[str]) -> "Board":
        """Build a board from ASCII rows such as ``["AAB", "ACB", "CCB"]``."""
        labels: dict[str, int] = {}
        grid: list[list[int]] = []
        for row in rows:
            out: list[int] = []
            for ch in row.strip():
                out.append(labels.setdefault(ch, len(labels)))
            grid.append(out)
        return cls(grid)

    def to_rows(self) -> list[str]:
        """Render the region map as ASCII rows (inverse of :meth:`from_rows`)."""
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return ["".join(alphabet[v] for v in row) for row in self.regions]

    def to_list(self) -> list[list[int]]:
        return [list(row) for row in self.regions]

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate(self) -> None:
        n = self.n
        if n == 0:
            raise InvalidBoardError("board must have at least one row")
        for r, row in enumerate(self.regions):
            if len(row) != n:
                raise InvalidBoardError(
                    f"row {r} has {len(row)} cells, expected {n} (board must be square)"
                )
        seen: set[int] = set()
        for row in self.regions:
            for value in row:
                if not 0 <= value < n:
                    raise InvalidBoardError(
                        f"region id {value} out of range 0..{n - 1}"
                    )
                seen.add(value)
        if len(seen) != n:
            missing = sorted(set(range(n)) - seen)
            raise InvalidBoardError(
                f"board must use exactly {n} regions, missing {missing}"
            )
        for region, cells in enumerate(self._raw_region_cells()):
            if not _is_connected(cells):
                raise InvalidBoardError(f"region {region} is not contiguous")

    def _raw_region_cells(self) -> list[list[Cell]]:
        buckets: list[list[Cell]] = [[] for _ in range(self.n)]
        for r, row in enumerate(self.regions):
            for c, region in enumerate(row):
                buckets[region].append((r, c))
        return buckets

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def region_at(self, cell: Cell) -> int:
        r, c = cell
        return self.regions[r][c]

    def cells(self) -> Iterator[Cell]:
        for r in range(self.n):
            for c in range(self.n):
                yield (r, c)

    def neighbours(self, cell: Cell) -> Iterator[Cell]:
        """Yield the diagonally adjacent in-bounds cells of ``cell``."""
        r, c = cell
        for dr, dc in DIAGONALS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < self.n and 0 <= nc < self.n:
                yield (nr, nc)

    def attacked_by(self, cell: Cell) -> set[Cell]:
        """Cells that cannot hold a queen once a queen sits on ``cell``.

        That is the cell's row, its column, its colour region and its four
        diagonal neighbours -- everything except ``cell`` itself.
        """
        r, c = cell
        out: set[Cell] = set()
        for i in range(self.n):
            out.add((r, i))
            out.add((i, c))
        out.update(self.region_cells[self.regions[r][c]])
        out.update(self.neighbours(cell))
        out.discard(cell)
        return out

    # ------------------------------------------------------------------
    # Solution checking
    # ------------------------------------------------------------------
    def is_valid_solution(self, queens: Sequence[int]) -> bool:
        """``queens[r]`` is the column of the queen in row ``r``."""
        n = self.n
        if len(queens) != n:
            return False
        if any(not 0 <= c < n for c in queens):
            return False
        if len(set(queens)) != n:  # one per column
            return False
        if len({self.regions[r][c] for r, c in enumerate(queens)}) != n:
            return False
        for r in range(n - 1):  # only adjacent rows can be diagonally adjacent
            if abs(queens[r] - queens[r + 1]) == 1:
                return False
        return True

    def render(self, queens: Sequence[int] | None = None) -> str:
        """Pretty-print the board, optionally with queens marked as ``Q``."""
        rows = self.to_rows()
        if queens is None:
            return "\n".join(" ".join(row) for row in rows)
        out = []
        for r, row in enumerate(rows):
            marked = ["Q" if c == queens[r] else ch for c, ch in enumerate(row)]
            out.append(" ".join(marked))
        return "\n".join(out)


def _is_connected(cells: Iterable[Cell]) -> bool:
    """Orthogonal 4-connectivity check over a set of cells."""
    remaining = set(cells)
    if not remaining:
        return False
    start = next(iter(remaining))
    stack = [start]
    remaining.discard(start)
    while stack:
        r, c = stack.pop()
        for dr, dc in ORTHOGONALS:
            nxt = (r + dr, c + dc)
            if nxt in remaining:
                remaining.discard(nxt)
                stack.append(nxt)
    return not remaining
