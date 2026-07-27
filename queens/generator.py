"""Puzzle generation.

The generator works backwards from an answer:

1. Draw a random legal queen placement (one per row and column, no diagonal
   touching). This is the puzzle's solution.
2. Seed one colour region on each queen and grow the regions outwards at
   random until they tile the board. Growing from the queens guarantees the
   placement satisfies the one-queen-per-region rule, and growing by flood
   fill keeps every region contiguous.
3. Reject the board unless the exhaustive solver finds exactly one solution.
4. Reject it again unless the deduction solver finishes it without guessing.

Step 2 is where all the character comes from, so a failed board is not thrown
away immediately -- moving single cells across region borders usually turns a
near miss into a keeper much faster than starting over.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Iterator, Sequence

from .board import Board, Cell, InvalidBoardError, ORTHOGONALS
from .logic import LogicResult, LogicSolver, solve_logically
from .solver import find_solutions

MIN_SIZE = 5
MAX_SIZE = 15

# Difficulty bands over the deduction score -- the tier-weighted sum of the
# inference steps needed to solve the board without guessing.
#
# The score is used raw, not divided by board area, and the bands are the same
# at every size. That is a deliberate choice: a "hard" puzzle should mean the
# same amount of reasoning whether it is 5x5 or 15x15.
#
# Normalising by area would be much worse. Sampled mean scores by size run
# 32 / 29 / 32 / 36 / 37 / 43 for 5x5..10x10 and 22 / 21 / 33 / 25 / 22 for
# 11x11..15x15; divided by area those fall from 1.28 to 0.10, so an area-based
# rule would call essentially every large board easy.
#
# The dip at 11x11 is real and worth knowing about: above the counting
# crossover the generator grows deliberately lopsided regions (see
# balance_range), and small regions pin their queen immediately, so those
# boards need less reasoning on average. It costs nothing in output balance --
# generate_matrix asks for each band explicitly and _retune walks a board into
# it -- but it does mean the hard cells at large sizes take longer to fill.
#
# The cut points are the tertiles of the pooled sample (p33 = 18, p67 = 38),
# rounded to the round numbers below, which split it 411 / 265 / 324. Rerun
# scripts/calibrate.py if the deduction rules or tier weights change.
DIFFICULTY_BANDS: tuple[tuple[str, float], ...] = (
    ("easy", 22),
    ("medium", 40),
    ("hard", float("inf")),
)


class GenerationError(RuntimeError):
    """Raised when the generator cannot meet the request in the attempts given."""


@dataclass
class Puzzle:
    """A generated board plus everything we measured about it."""

    board: Board
    solution: tuple[int, ...]
    difficulty: str
    steps: int
    score: int
    max_tier: int
    tier_counts: dict[int, int] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return self.board.n

    def to_dict(self, puzzle_id: str | None = None) -> dict:
        data = {
            "size": self.size,
            "regions": self.board.to_list(),
            "solution": list(self.solution),
            "difficulty": self.difficulty,
            "metrics": {
                "steps": self.steps,
                "score": self.score,
                "max_tier": self.max_tier,
                "tier_counts": {str(k): v for k, v in sorted(self.tier_counts.items())},
            },
        }
        if puzzle_id is not None:
            return {"id": puzzle_id, **data}
        return data

    def key(self) -> tuple:
        """Canonical identity, used to keep the output set duplicate-free."""
        return (self.size, self.board.regions)


# ----------------------------------------------------------------------
# Step 1 -- a random legal placement
# ----------------------------------------------------------------------
def random_solution(n: int, rng: random.Random) -> tuple[int, ...]:
    """Random queen placement: one per row and column, no diagonal contact."""
    placement: list[int] = []

    def recurse(row: int, used: int, prev: int) -> bool:
        if row == n:
            return True
        cols = list(range(n))
        rng.shuffle(cols)
        for col in cols:
            if used >> col & 1:
                continue
            if prev >= 0 and abs(prev - col) == 1:
                continue
            placement.append(col)
            if recurse(row + 1, used | 1 << col, col):
                return True
            placement.pop()
        return False

    if not recurse(0, 0, -1):
        raise GenerationError(f"no legal placement exists for n={n}")
    return tuple(placement)


# ----------------------------------------------------------------------
# Step 2 -- grow colour regions out of the queens
# ----------------------------------------------------------------------
def balance_range(n: int) -> tuple[float, float]:
    """The ``balance`` window to sample from for a board of size ``n``.

    Region size *variance* is the single biggest lever on how constrained a
    board is, and how much of it you need grows sharply with ``n``. Regions
    hold ``n`` cells on average, so as the board grows each region pins its
    queen less and less and the solution count explodes: even-sized regions at
    15x15 leave hundreds of thousands of solutions, which no amount of local
    search will walk down to one.

    Uneven regions fix that -- a small region pins its queen immediately and a
    large one gets squeezed out by elimination. Measured medians for the raw
    solution count at 15x15 were 200000+ at ``balance >= 0`` against about 300
    at ``balance = -2``. So the window slides negative as the board grows.
    """
    if n <= COUNT_OBJECTIVE_MAX_SIZE:
        # Small boards tolerate a wide window: even fairly even regions leave
        # few enough solutions for the search to walk down.
        return 1.4 - 0.30 * (n - MIN_SIZE) - 0.7, 1.4 - 0.30 * (n - MIN_SIZE) + 0.7
    # Above the crossover the useful window is narrow and has to be aimed
    # carefully. Measured sweet spots for the raw solution count were about
    # -1.75 at 12x12 (median 18, against 1988 at balance -1) and about -2.0 at
    # 15x15. Three orders of magnitude separate the ends, so there is no room
    # to wander.
    centre = -1.75 - 0.10 * (n - 12)
    return centre - 0.35, centre + 0.35


def size_cap_range(n: int) -> tuple[float, float]:
    """Multiples of ``n`` to sample the per-region size cap from.

    Measured at 15x15: a cap of 2n left a median of 5400 solutions, 3n left
    310 and 4n left 22. Small boards do not need the room, so the lower bound
    only climbs once the board is big enough for it to matter.
    """
    if n <= COUNT_OBJECTIVE_MAX_SIZE:
        return 2.0, 4.5
    return 3.0, 4.5


def grow_regions(
    n: int,
    solution: Sequence[int],
    rng: random.Random,
    balance: float | None = None,
    size_cap: int | None = None,
) -> list[list[int]]:
    """Flood-fill ``n`` contiguous regions, one seeded on each queen.

    ``balance`` biases which region gets to claim the next cell. Positive
    values push the regions towards equal size; negative values let big
    regions keep growing, which is what large boards need (see
    :func:`balance_range`).

    ``size_cap`` stops any one region from running away. Without it a strongly
    negative balance produces a single region swallowing most of the grid,
    which is uniquely solvable but a degenerate, trivial puzzle. A cap of a few
    times ``n`` keeps the spread wide without the monster.
    """
    if balance is None:
        balance = rng.uniform(*balance_range(n))
    if size_cap is None:
        size_cap = round(n * rng.uniform(*size_cap_range(n)))

    grid = [[-1] * n for _ in range(n)]
    frontier: list[set[Cell]] = [set() for _ in range(n)]
    sizes = [1] * n

    for region, (r, c) in enumerate((r, solution[r]) for r in range(n)):
        grid[r][c] = region
        for dr, dc in ORTHOGONALS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < n and 0 <= nc < n:
                frontier[region].add((nr, nc))

    def can_grow(i: int) -> bool:
        return any(grid[r][c] == -1 for r, c in frontier[i])

    remaining = n * n - n
    while remaining:
        live = [i for i in range(n) if sizes[i] < size_cap and can_grow(i)]
        if not live:
            # Everything under the cap is boxed in. Lift the cap rather than
            # leave cells unassigned -- the board still has to be a partition.
            live = [i for i in range(n) if can_grow(i)]
        if not live:  # unreachable on a connected grid, but stay safe
            break
        weights = [1.0 / (sizes[i] ** balance) for i in live]
        region = rng.choices(live, weights=weights, k=1)[0]

        pool = [cell for cell in frontier[region] if grid[cell[0]][cell[1]] == -1]
        r, c = rng.choice(pool)
        frontier[region] = set(pool)
        frontier[region].discard((r, c))

        grid[r][c] = region
        sizes[region] += 1
        remaining -= 1
        for dr, dc in ORTHOGONALS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < n and 0 <= nc < n and grid[nr][nc] == -1:
                frontier[region].add((nr, nc))

    return grid


# ----------------------------------------------------------------------
# Step 4 -- nudge a board that almost works
# ----------------------------------------------------------------------
def _region_members(grid: Sequence[Sequence[int]], n: int) -> list[set[Cell]]:
    members: list[set[Cell]] = [set() for _ in range(n)]
    for r in range(n):
        for c in range(n):
            members[grid[r][c]].add((r, c))
    return members


def _stays_connected(cells: set[Cell]) -> bool:
    if not cells:
        return False
    start = next(iter(cells))
    seen = {start}
    stack = [start]
    while stack:
        r, c = stack.pop()
        for dr, dc in ORTHOGONALS:
            nxt = (r + dr, c + dc)
            if nxt in cells and nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return len(seen) == len(cells)


def perturbations(
    grid: Sequence[Sequence[int]],
    solution: Sequence[int],
    rng: random.Random,
) -> Iterator[list[list[int]]]:
    """Yield boards one border-cell move away from ``grid``.

    A move is legal when the donor region keeps its queen, keeps at least one
    cell and stays contiguous.
    """
    n = len(grid)
    queens = {(r, solution[r]) for r in range(n)}
    members = _region_members(grid, n)

    moves: list[tuple[Cell, int]] = []
    for r in range(n):
        for c in range(n):
            cell = (r, c)
            if cell in queens:
                continue
            donor = grid[r][c]
            if len(members[donor]) <= 1:
                continue
            neighbours = set()
            for dr, dc in ORTHOGONALS:
                nr, nc = r + dr, c + dc
                if 0 <= nr < n and 0 <= nc < n and grid[nr][nc] != donor:
                    neighbours.add(grid[nr][nc])
            if not neighbours:
                continue
            if not _stays_connected(members[donor] - {cell}):
                continue
            for taker in neighbours:
                moves.append((cell, taker))

    rng.shuffle(moves)
    for (r, c), taker in moves:
        candidate = [list(row) for row in grid]
        candidate[r][c] = taker
        yield candidate


# ----------------------------------------------------------------------
# Assembly
# ----------------------------------------------------------------------
def classify(score: int) -> str:
    """Map a tier-weighted deduction score onto a difficulty band."""
    for name, upper in DIFFICULTY_BANDS:
        if score < upper:
            return name
    return DIFFICULTY_BANDS[-1][0]


def evaluate(grid: Sequence[Sequence[int]]) -> tuple[Board, tuple[int, ...], LogicResult] | None:
    """Return ``(board, solution, logic_result)`` for a board worth keeping.

    ``None`` means the board failed one of the two hard requirements: exactly
    one solution, and solvable by deduction alone.
    """
    try:
        board = Board(grid)
    except InvalidBoardError:
        return None
    solutions = find_solutions(board, limit=2)
    if len(solutions) != 1:
        return None
    result = solve_logically(board)
    if not result.solved:
        return None
    return board, solutions[0], result


def _make_puzzle(
    board: Board, solution: tuple[int, ...], result: LogicResult
) -> Puzzle:
    return Puzzle(
        board=board,
        solution=solution,
        difficulty=classify(result.score),
        steps=result.step_count,
        score=result.score,
        max_tier=result.max_tier,
        tier_counts=result.tier_counts,
    )


# A board that is far from unique can have a great many solutions. We never
# need the exact figure, only a number to descend on, so the count is capped.
_COUNT_CAP = 50_000

# Objective values are 3-tuples, compared lexicographically, smaller is better,
# and (0, 0, 0) means finished. There are two ways to fill them in, and which
# one is cheaper flips over as the board grows -- see `objective_mode`.
#
#   counting  (1, k, 0)  k solutions, still ambiguous
#             (0, m, 0)  unique, but deduction stalls with m queens unplaced
#   deduction (0, m, c)  deduction stalls with m queens unplaced, c candidates
#
# The deduction mode never measures the solution count at all. It can get away
# with that because the rules are sound: every queen the solver commits to
# holds in every solution of the board, so if it places all n of them then all
# solutions agree on all n cells and the board is necessarily unique. Measured
# over thousands of generated boards, every board the deduction solver finished
# did turn out to have exactly one solution.
_Objective = tuple[int, int, int]
_PERFECT: _Objective = (0, 0, 0)

# Up to this size the solution count is the better objective; above it, pure
# deduction is. Counting is cheap while a board is ambiguous but expensive once
# it is nearly unique, because the solver then has to exhaust the whole tree to
# prove no second solution exists -- and the search pays that for every
# candidate move. Profiling a 13x13 search driven by counting put 89% of its
# runtime in the exhaustive solver. Below the crossover the count is cheap and
# a much sharper gradient: at 7x7 it generates a puzzle in 0.12s against 1.2s
# for deduction. Above it, counting stops finishing at all.
COUNT_OBJECTIVE_MAX_SIZE = 10


def objective_mode(n: int) -> str:
    return "counting" if n <= COUNT_OBJECTIVE_MAX_SIZE else "deduction"


def _objective(
    grid: Sequence[Sequence[int]], n: int, mode: str, limit: int = 2
) -> tuple[_Objective, Board, LogicResult | None] | None:
    """Score a candidate region map. ``None`` if the map is not a legal board.

    In counting mode ``limit`` caps the solution enumeration. When we already
    know the score to beat, passing it here lets the solver bail out early on
    hopeless candidates, which is most of them.
    """
    try:
        board = Board(grid)
    except InvalidBoardError:
        return None

    if mode == "counting":
        solutions = find_solutions(board, limit=limit)
        if len(solutions) != 1:
            return (1, len(solutions), 0), board, None
        result = solve_logically(board)
        return (0, n - len(result.placements), 0), board, result

    solver = LogicSolver(board)
    result = solver.run()
    # Candidates left over is a tie-break: it keeps the search moving downhill
    # on boards where the placed count has not budged yet.
    return (0, n - len(result.placements), len(solver.candidates)), board, result


def search_budget(n: int) -> tuple[int, int]:
    """``(max_iters, neighbourhood)`` for a board of size ``n``.

    Each candidate move costs one deduction run, and that gets steadily more
    expensive as the board grows (about 0.2ms at 5x5 against 10ms at 15x15), so
    the neighbourhood sample shrinks to keep a single iteration affordable.
    """
    if n <= COUNT_OBJECTIVE_MAX_SIZE:
        return 120, 200
    # Above the crossover a failed search is expensive, so cap the run shorter
    # and let generate_puzzle restart from a fresh layout instead -- diversity
    # beats grinding one layout that is not going anywhere.
    return 90, max(40, 260 - 15 * n)


def _local_search(
    n: int,
    rng: random.Random,
    max_iters: int | None = None,
    neighbourhood: int | None = None,
    plateau_limit: int = 8,
) -> tuple[Board, tuple[int, ...], LogicResult] | None:
    """Hill-climb a random layout into a deduction-solvable board.

    Random region growth on its own almost never lands on a keeper above 6x6,
    but it lands *near* one often enough. Each move shifts a single cell across
    a region border, which keeps the seeded solution valid throughout, so the
    search only has to open up the deduction chain until it runs to completion.
    """
    default_iters, default_neigh = search_budget(n)
    max_iters = default_iters if max_iters is None else max_iters
    neighbourhood = default_neigh if neighbourhood is None else neighbourhood
    mode = objective_mode(n)

    def measure(candidate, limit=_COUNT_CAP):
        return _objective(candidate, n, mode, limit)

    solution = random_solution(n, rng)
    grid = [list(row) for row in grow_regions(n, solution, rng)]
    scored = measure(grid)
    if scored is None:
        return None
    current, board, result = scored
    plateau = 0

    for _ in range(max_iters):
        if current == _PERFECT:
            # Deduction mode never counted solutions, and it does not have to:
            # a board the sound solver finishes cannot have a second solution.
            # Confirm it anyway rather than ship on an invariant the code does
            # not check -- once the board is this constrained the proof costs
            # milliseconds. Belt and braces on the one property that matters.
            if len(find_solutions(board, limit=2)) != 1:
                return None
            return board, solution, result or solve_logically(board)

        # In counting mode a candidate can only beat us by being unique (when
        # we already are) or by having fewer solutions (when we are not).
        limit = current[1] if current[0] == 1 else 2
        best: _Objective | None = None
        best_state: tuple[list[list[int]], Board, LogicResult | None] | None = None
        for i, candidate in enumerate(perturbations(grid, solution, rng)):
            if i >= neighbourhood:
                break
            scored = measure(candidate, limit)
            if scored is None:
                continue
            value, cand_board, cand_result = scored
            if best is None or value < best:
                best = value
                best_state = (candidate, cand_board, cand_result)
                if value < current:
                    break  # take the first improvement we see
        if best_state is None:
            return None

        if best < current or plateau < plateau_limit:
            # Sideways moves are allowed for a while: the region map drifts
            # even when the score does not, which is usually enough to find a
            # downhill move next round.
            plateau = 0 if best < current else plateau + 1
            grid = best_state[0]
        else:
            # Stuck. Kick the layout a few cells away and re-measure.
            for i, candidate in enumerate(perturbations(grid, solution, rng)):
                grid = candidate
                if i >= 2:
                    break
            plateau = 0

        # Re-measure without the early-exit limit so `current` is exact.
        rescored = measure(grid)
        if rescored is None:
            return None
        current, board, result = rescored

    return None


def attempt_budget(n: int) -> int:
    """How many fresh local searches to try before giving up on a request.

    A search costs well under a second up to 9x9 but tens of seconds at 15x15,
    so a flat retry count would make a single unlucky large board run for the
    best part of an hour. Above the crossover the budget shrinks and the work
    of hitting a requested difficulty shifts to :func:`_retune`, which walks an
    already-valid board towards the band instead of starting over.
    """
    if n <= COUNT_OBJECTIVE_MAX_SIZE:
        return 60
    return max(6, 60 // (n - COUNT_OBJECTIVE_MAX_SIZE + 1))


def generate_puzzle(
    n: int,
    rng: random.Random | None = None,
    difficulty: str | None = None,
    attempts: int | None = None,
    retune_budget: int = 60,
) -> Puzzle:
    """Generate one puzzle of size ``n``, optionally of a required difficulty.

    Raises :class:`GenerationError` if ``attempts`` local searches go by
    without a match. ``attempts`` defaults to :func:`attempt_budget`.
    """
    if not MIN_SIZE <= n <= MAX_SIZE:
        raise ValueError(f"size must be between {MIN_SIZE} and {MAX_SIZE}, got {n}")
    if difficulty is not None and difficulty not in {b[0] for b in DIFFICULTY_BANDS}:
        raise ValueError(f"unknown difficulty {difficulty!r}")
    rng = rng or random.Random()
    attempts = attempt_budget(n) if attempts is None else attempts

    fallback: Puzzle | None = None
    for _ in range(attempts):
        found = _local_search(n, rng)
        if found is None:
            continue

        puzzle = _make_puzzle(*found)
        if difficulty is None or puzzle.difficulty == difficulty:
            return puzzle
        fallback = fallback or puzzle

        # Right board, wrong band: walk the neighbourhood towards the band we
        # were asked for, staying inside the valid region the whole way.
        tuned = _retune(puzzle, rng, difficulty, retune_budget)
        if tuned is not None:
            return tuned

    if difficulty is None and fallback is not None:
        return fallback
    raise GenerationError(
        f"could not generate a {difficulty or 'valid'} {n}x{n} puzzle "
        f"in {attempts} attempts"
    )


def _retune(
    puzzle: Puzzle, rng: random.Random, difficulty: str, budget: int
) -> Puzzle | None:
    """Hill-climb from a valid puzzle towards a different difficulty band."""
    current = puzzle
    for _ in range(4):
        best: Puzzle | None = None
        for i, candidate in enumerate(
            perturbations(current.board.regions, current.solution, rng)
        ):
            if i >= budget:
                break
            found = evaluate(candidate)
            if found is None:
                continue
            neighbour = _make_puzzle(*found)
            if neighbour.difficulty == difficulty:
                return neighbour
            if best is None or _closer(neighbour, best, difficulty):
                best = neighbour
        if best is None or not _closer(best, current, difficulty):
            return None
        current = best
    return None


def _band_target(difficulty: str) -> float:
    """A representative score for a band, used to steer the hill climb."""
    lower = 0.0
    for name, upper in DIFFICULTY_BANDS:
        if name == difficulty:
            # The open-ended top band has no midpoint; aim a little past its
            # lower edge so the climb has somewhere to go.
            return lower * 1.4 if upper == float("inf") else (lower + upper) / 2
        lower = upper
    raise ValueError(f"unknown difficulty {difficulty!r}")


def _closer(a: Puzzle, b: Puzzle, difficulty: str) -> bool:
    target = _band_target(difficulty)
    return abs(a.score - target) < abs(b.score - target)


@dataclass
class CellReport:
    """How one (size, difficulty) cell of the matrix went."""

    size: int
    difficulty: str
    requested: int
    puzzles: list[Puzzle] = field(default_factory=list)
    seconds: float = 0.0
    failures: int = 0

    @property
    def produced(self) -> int:
        return len(self.puzzles)

    @property
    def seconds_each(self) -> float:
        return self.seconds / self.produced if self.puzzles else 0.0

    def to_dict(self) -> dict:
        return {
            "size": self.size,
            "difficulty": self.difficulty,
            "requested": self.requested,
            "produced": self.produced,
            "failed": self.failures,
            "seconds": round(self.seconds, 2),
            "seconds_each": round(self.seconds_each, 2),
        }


@dataclass
class MatrixReport:
    """Result of a full size x difficulty generation run."""

    cells: list[CellReport] = field(default_factory=list)

    @property
    def puzzles(self) -> list[Puzzle]:
        return [p for cell in self.cells for p in cell.puzzles]

    @property
    def seconds(self) -> float:
        return sum(cell.seconds for cell in self.cells)

    def by_size(self) -> dict[int, dict]:
        """Per-size totals -- the headline timing for a run."""
        out: dict[int, dict] = {}
        for cell in self.cells:
            entry = out.setdefault(
                cell.size,
                {"requested": 0, "produced": 0, "failed": 0, "seconds": 0.0},
            )
            entry["requested"] += cell.requested
            entry["produced"] += cell.produced
            entry["failed"] += cell.failures
            entry["seconds"] += cell.seconds
        for entry in out.values():
            entry["seconds"] = round(entry["seconds"], 2)
            entry["seconds_each"] = (
                round(entry["seconds"] / entry["produced"], 2)
                if entry["produced"]
                else 0.0
            )
        return out

    def to_dict(self) -> dict:
        return {
            "total_seconds": round(self.seconds, 2),
            "by_size": {str(k): v for k, v in sorted(self.by_size().items())},
            "cells": [cell.to_dict() for cell in self.cells],
        }


def generate_matrix(
    per_cell: int = 3,
    sizes: Sequence[int] = tuple(range(MIN_SIZE, MAX_SIZE + 1)),
    difficulties: Sequence[str] = ("easy", "medium", "hard"),
    seed: int | None = None,
    progress: bool = False,
    attempts: int | None = None,
) -> MatrixReport:
    """Generate ``per_cell`` puzzles for every (size, difficulty) pair.

    Timing is recorded per cell and rolled up per size, because generation cost
    grows very steeply with the board: a 5x5 lands in hundredths of a second
    while a 15x15 takes the best part of a minute.

    A cell that cannot be filled is reported rather than raised -- a run over
    the whole matrix is long, and losing all of it because one hard cell at the
    top size came up dry would be a poor trade.
    """
    if per_cell < 1:
        raise ValueError("per_cell must be at least 1")
    rng = random.Random(seed)
    report = MatrixReport()
    seen: set[tuple] = set()

    for size in sizes:
        for difficulty in difficulties:
            cell = CellReport(size=size, difficulty=difficulty, requested=per_cell)
            started = time.perf_counter()
            for _ in range(per_cell):
                puzzle = _distinct_puzzle(size, rng, difficulty, seen, attempts)
                if puzzle is None:
                    cell.failures += 1
                    continue
                seen.add(puzzle.key())
                cell.puzzles.append(puzzle)
            cell.seconds = time.perf_counter() - started
            report.cells.append(cell)
            if progress:
                print(
                    f"  {size:>2}x{size:<2} {difficulty:<6} "
                    f"{cell.produced}/{cell.requested} in {cell.seconds:6.1f}s "
                    f"({cell.seconds_each:5.2f}s each)"
                    + (f"  [{cell.failures} failed]" if cell.failures else ""),
                    flush=True,
                )
        if progress:
            totals = report.by_size()[size]
            print(
                f"size {size:>2}: {totals['produced']}/{totals['requested']} puzzles "
                f"in {totals['seconds']:.1f}s ({totals['seconds_each']:.2f}s each)",
                flush=True,
            )
    return report


def _distinct_puzzle(
    size: int,
    rng: random.Random,
    difficulty: str,
    seen: set[tuple],
    attempts: int | None,
) -> Puzzle | None:
    """One puzzle for a matrix cell, or ``None`` if the cell came up dry."""
    kwargs = {} if attempts is None else {"attempts": attempts}
    for _ in range(20):
        try:
            puzzle = generate_puzzle(size, rng=rng, difficulty=difficulty, **kwargs)
        except GenerationError:
            try:
                puzzle = generate_puzzle(size, rng=rng, **kwargs)
            except GenerationError:
                return None
        if puzzle.key() not in seen:
            return puzzle
    return None


def generate_many(
    count: int,
    sizes: Sequence[int] = tuple(range(MIN_SIZE, MAX_SIZE + 1)),
    difficulties: Sequence[str] = ("easy", "medium", "hard"),
    seed: int | None = None,
    progress: bool = False,
) -> list[Puzzle]:
    """Generate ``count`` distinct puzzles spread over sizes and difficulties.

    Requests cycle through the sizes fastest and the difficulties slowest, so
    every size gets an even share of the total and a mix of all three bands.
    """
    if not sizes or not difficulties:
        raise ValueError("need at least one size and one difficulty")
    rng = random.Random(seed)
    plan = [
        (sizes[i % len(sizes)], difficulties[(i // len(sizes)) % len(difficulties)])
        for i in range(count)
    ]

    seen: set[tuple] = set()
    puzzles: list[Puzzle] = []
    for index, (size, difficulty) in enumerate(plan):
        for _ in range(60):
            try:
                puzzle = generate_puzzle(size, rng=rng, difficulty=difficulty)
            except GenerationError:
                # The band is unreachable from this rng state; take whatever
                # this size gives us rather than abandoning the whole run.
                puzzle = generate_puzzle(size, rng=rng)
            if puzzle.key() not in seen:
                break
        else:
            raise GenerationError(
                f"could not find a {size}x{size} board that is not already in the set"
            )
        seen.add(puzzle.key())
        puzzles.append(puzzle)
        if progress:
            print(
                f"[{index + 1}/{count}] {size}x{size} {puzzle.difficulty} "
                f"steps={puzzle.steps} score={puzzle.score} tier={puzzle.max_tier}",
                flush=True,
            )
    return puzzles
