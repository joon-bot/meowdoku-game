"""A no-guessing solver that mimics how a person reasons about the puzzle.

The point of this module is not speed -- :mod:`queens.solver` already solves
boards instantly. It exists to answer two questions the generator needs:

1. Can this board be solved by pure deduction, without ever assuming a
   placement and seeing what happens?
2. How hard is that deduction?

Every rule is a *sound* inference: it only ever removes candidates that cannot
appear in any solution of the current position. Nothing here branches or
backtracks, so a board that this solver finishes is guaranteed to be solvable
without guessing.

Rules are grouped into tiers, from the most obvious to the most demanding, and
the solver always applies the cheapest tier that fires. The number of
deductions and the tiers they came from are what the generator turns into a
difficulty rating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable, Iterable

from .board import Board, Cell

# How much a single deduction of each tier contributes to the difficulty score.
# The gaps are deliberately wide: needing one tier-4 insight makes a board
# harder than a long run of trivial tier-1 steps.
TIER_WEIGHTS: dict[int, int] = {1: 1, 2: 3, 3: 7, 4: 15}

TIER_NAMES: dict[int, str] = {
    1: "forced-single",
    2: "confinement",
    3: "shared-attack",
    4: "hall-set",
}

UNIT_KINDS = ("row", "col", "region")


@dataclass(frozen=True)
class Deduction:
    """One inference step made by the solver."""

    tier: int
    rule: str
    detail: str
    placed: Cell | None = None
    eliminated: tuple[Cell, ...] = ()

    @property
    def weight(self) -> int:
        return TIER_WEIGHTS[self.tier]


@dataclass
class LogicResult:
    """Outcome of a full deduction run."""

    solved: bool
    contradiction: bool
    placements: dict[int, int] = field(default_factory=dict)
    steps: list[Deduction] = field(default_factory=list)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def score(self) -> int:
        return sum(step.weight for step in self.steps)

    @property
    def max_tier(self) -> int:
        return max((step.tier for step in self.steps), default=0)

    @property
    def tier_counts(self) -> dict[int, int]:
        counts = {tier: 0 for tier in TIER_WEIGHTS}
        for step in self.steps:
            counts[step.tier] += 1
        return counts

    def solution(self) -> tuple[int, ...] | None:
        if not self.solved:
            return None
        return tuple(self.placements[r] for r in sorted(self.placements))


class _Unit:
    """A row, a column or a colour region -- something that holds one queen."""

    __slots__ = ("kind", "index", "cells", "label")

    def __init__(self, kind: str, index: int, cells: frozenset[Cell]) -> None:
        self.kind = kind
        self.index = index
        self.cells = cells
        self.label = f"{kind} {index}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.label}>"


_ATTACK_BASE: dict[int, dict[Cell, frozenset[Cell]]] = {}


def _attack_base(n: int) -> dict[Cell, frozenset[Cell]]:
    """The region-independent part of each cell's attack set, cached by size.

    A cell attacks its row, its column, its four diagonal neighbours and its
    colour region. Only the last of those depends on the region map, so the
    rest can be built once per board size and shared. The generator solves
    thousands of one-cell variations of the same board, and rebuilding this
    every time was about a third of the solver's runtime.
    """
    cached = _ATTACK_BASE.get(n)
    if cached is not None:
        return cached

    base: dict[Cell, frozenset[Cell]] = {}
    for r in range(n):
        for c in range(n):
            cells = {(r, i) for i in range(n)} | {(i, c) for i in range(n)}
            for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < n and 0 <= nc < n:
                    cells.add((nr, nc))
            cells.discard((r, c))
            base[(r, c)] = frozenset(cells)
    _ATTACK_BASE[n] = base
    return base


class LogicSolver:
    """Applies deduction rules to a board until it stalls, solves or breaks."""

    def __init__(self, board: Board, max_set_size: int = 4) -> None:
        self.board = board
        self.n = board.n
        self.max_set_size = max_set_size
        base = _attack_base(self.n)
        region_sets = [frozenset(cells) for cells in board.region_cells]
        self.attacked: dict[Cell, frozenset[Cell]] = {
            cell: (base[cell] | region_sets[board.regions[cell[0]][cell[1]]])
            - {cell}
            for cell in board.cells()
        }
        self.units: list[_Unit] = []
        for r in range(self.n):
            self.units.append(
                _Unit("row", r, frozenset((r, c) for c in range(self.n)))
            )
        for c in range(self.n):
            self.units.append(
                _Unit("col", c, frozenset((r, c) for r in range(self.n)))
            )
        for g, cells in enumerate(board.region_cells):
            self.units.append(_Unit("region", g, frozenset(cells)))

        # Per-cell lookup of the three units it belongs to, keyed by kind.
        self.unit_of: dict[str, dict[Cell, int]] = {kind: {} for kind in UNIT_KINDS}
        for cell in board.cells():
            r, c = cell
            self.unit_of["row"][cell] = r
            self.unit_of["col"][cell] = c
            self.unit_of["region"][cell] = board.regions[r][c]

        self.candidates: set[Cell] = set(board.cells())
        self.placed: dict[int, int] = {}
        self.satisfied: set[int] = set()  # indices into self.units
        self.steps: list[Deduction] = []
        self.contradiction = False

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------
    def unit_candidates(self, unit: _Unit) -> set[Cell]:
        return unit.cells & self.candidates

    def open_units(self) -> list[tuple[int, _Unit]]:
        return [
            (i, unit)
            for i, unit in enumerate(self.units)
            if i not in self.satisfied
        ]

    def _place(self, cell: Cell, rule: str, tier: int, detail: str) -> None:
        r, c = cell
        self.placed[r] = c
        removed = self.attacked[cell] & self.candidates
        self.candidates -= removed
        self.candidates.discard(cell)
        for i, unit in enumerate(self.units):
            if cell in unit.cells:
                self.satisfied.add(i)
        self.steps.append(
            Deduction(
                tier=tier,
                rule=rule,
                detail=detail,
                placed=cell,
                eliminated=tuple(sorted(removed)),
            )
        )

    def _eliminate(
        self, cells: Iterable[Cell], rule: str, tier: int, detail: str
    ) -> bool:
        removed = {cell for cell in cells if cell in self.candidates}
        if not removed:
            return False
        self.candidates -= removed
        self.steps.append(
            Deduction(
                tier=tier,
                rule=rule,
                detail=detail,
                eliminated=tuple(sorted(removed)),
            )
        )
        return True

    def _detect_contradiction(self) -> bool:
        for _, unit in self.open_units():
            if not self.unit_candidates(unit):
                self.contradiction = True
                return True
        return False

    # ------------------------------------------------------------------
    # Tier 1 -- a unit with a single remaining candidate
    # ------------------------------------------------------------------
    def _tier1(self) -> bool:
        for _, unit in self.open_units():
            cands = self.unit_candidates(unit)
            if len(cands) == 1:
                cell = next(iter(cands))
                self._place(
                    cell,
                    rule=TIER_NAMES[1],
                    tier=1,
                    detail=f"{unit.label} has only {cell} left",
                )
                return True
        return False

    # ------------------------------------------------------------------
    # Tier 2 -- one unit's candidates all sit inside another unit
    # ------------------------------------------------------------------
    def _tier2(self) -> bool:
        open_units = self.open_units()
        cand_cache = {i: self.unit_candidates(unit) for i, unit in open_units}
        for i, unit in open_units:
            cands = cand_cache[i]
            if len(cands) < 2:
                continue
            for j, other in open_units:
                if i == j or other.kind == unit.kind:
                    continue
                if not cands <= other.cells:
                    continue
                surplus = cand_cache[j] - cands
                if self._eliminate(
                    surplus,
                    rule=TIER_NAMES[2],
                    tier=2,
                    detail=(
                        f"every candidate of {unit.label} lies in {other.label}, "
                        f"so the rest of {other.label} is out"
                    ),
                ):
                    return True
        return False

    # ------------------------------------------------------------------
    # Tier 3 -- cells attacked by every candidate of some unit
    # ------------------------------------------------------------------
    def _tier3(self) -> bool:
        for _, unit in self.open_units():
            cands = self.unit_candidates(unit)
            if len(cands) < 2:
                continue
            shared: set[Cell] | None = None
            for cell in cands:
                hit = self.attacked[cell] & self.candidates
                shared = hit if shared is None else shared & hit
                if not shared:
                    break
            if not shared:
                continue
            if self._eliminate(
                shared,
                rule=TIER_NAMES[3],
                tier=3,
                detail=(
                    f"wherever the queen of {unit.label} goes it attacks these cells"
                ),
            ):
                return True
        return False

    # ------------------------------------------------------------------
    # Tier 4 -- Hall sets across two unit families
    # ------------------------------------------------------------------
    def _tier4(self) -> bool:
        for source_kind in UNIT_KINDS:
            for label_kind in UNIT_KINDS:
                if source_kind == label_kind:
                    continue
                if self._hall_sets(source_kind, label_kind):
                    return True
        return False

    def _hall_sets(self, source_kind: str, label_kind: str) -> bool:
        """If ``k`` source units only reach ``k`` label units, they own them.

        With rows as the source and columns as the labels this is the classic
        naked set. With regions as the source and rows as the labels it says
        "these 3 regions must use these 3 rows", which clears every other
        region out of those rows.
        """
        # Everything here is keyed by the unit's index *within its family* --
        # the row number, column number or region id -- because that is what
        # self.unit_of maps a cell to.
        source_index = self.unit_of[source_kind]
        label_index = self.unit_of[label_kind]
        open_units = self.open_units()

        reach: dict[int, frozenset[int]] = {
            unit.index: frozenset(
                label_index[cell] for cell in self.unit_candidates(unit)
            )
            for _, unit in open_units
            if unit.kind == source_kind
        }
        by_label: dict[int, _Unit] = {
            unit.index: unit for _, unit in open_units if unit.kind == label_kind
        }

        upper = min(self.max_set_size, max(len(reach) - 1, 0))
        for size in range(2, upper + 1):
            pool = [idx for idx, labels in reach.items() if 0 < len(labels) <= size]
            for combo in combinations(pool, size):
                labels: frozenset[int] = frozenset().union(
                    *(reach[idx] for idx in combo)
                )
                if len(labels) != size:
                    continue
                chosen = set(combo)
                victims: set[Cell] = set()
                for label in labels:
                    label_unit = by_label.get(label)
                    if label_unit is None:
                        continue
                    for cell in self.unit_candidates(label_unit):
                        if source_index[cell] not in chosen:
                            victims.add(cell)
                if not victims:
                    continue
                names = ", ".join(f"{source_kind} {idx}" for idx in combo)
                targets = ", ".join(f"{label_kind} {v}" for v in sorted(labels))
                if self._eliminate(
                    victims,
                    rule=TIER_NAMES[4],
                    tier=4,
                    detail=(
                        f"{names} together can only use {targets}, "
                        "so nothing else may"
                    ),
                ):
                    return True
        return False

    # ------------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------------
    def run(self, tier_cap: int = 4) -> LogicResult:
        rules: list[Callable[[], bool]] = [
            self._tier1,
            self._tier2,
            self._tier3,
            self._tier4,
        ][:tier_cap]

        while True:
            if self._detect_contradiction():
                return LogicResult(
                    solved=False,
                    contradiction=True,
                    placements=dict(self.placed),
                    steps=list(self.steps),
                )
            if len(self.placed) == self.n:
                break
            if not any(rule() for rule in rules):
                break

        solved = len(self.placed) == self.n and self.board.is_valid_solution(
            [self.placed[r] for r in range(self.n)]
        )
        return LogicResult(
            solved=solved,
            contradiction=self.contradiction,
            placements=dict(self.placed),
            steps=list(self.steps),
        )


def solve_logically(
    board: Board, tier_cap: int = 4, max_set_size: int = 4
) -> LogicResult:
    """Solve ``board`` by deduction alone and report how much work it took."""
    return LogicSolver(board, max_set_size=max_set_size).run(tier_cap=tier_cap)


def is_logically_solvable(board: Board) -> bool:
    """True when the board never requires a guess."""
    return solve_logically(board).solved


def explain(board: Board, result: LogicResult | None = None) -> str:
    """Human-readable walkthrough of a deduction run (useful as a hint feed)."""
    result = result or solve_logically(board)
    lines = []
    for i, step in enumerate(result.steps, start=1):
        head = f"{i:3d}. [T{step.tier} {step.rule}] {step.detail}"
        if step.placed is not None:
            head += f" -> queen at r{step.placed[0]}c{step.placed[1]}"
        elif step.eliminated:
            shown = ", ".join(f"r{r}c{c}" for r, c in step.eliminated[:6])
            more = "" if len(step.eliminated) <= 6 else f" (+{len(step.eliminated) - 6})"
            head += f" -> rule out {shown}{more}"
        lines.append(head)
    verdict = "solved" if result.solved else (
        "contradiction" if result.contradiction else "stalled"
    )
    lines.append(
        f"--- {verdict}: {result.step_count} steps, score {result.score}, "
        f"max tier {result.max_tier}"
    )
    return "\n".join(lines)
