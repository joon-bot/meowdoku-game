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
from dataclasses import dataclass, field
from typing import Iterator, Sequence

from .board import Board, Cell, InvalidBoardError, ORTHOGONALS
from .logic import LogicResult, solve_logically
from .solver import find_solutions

MIN_SIZE = 5
MAX_SIZE = 9

# Difficulty bands over the deduction score -- the tier-weighted sum of the
# inference steps needed to solve the board without guessing.
#
# The score is used raw, not divided by board area. That looks surprising, but
# it is what the data says: a bigger board needs more steps and each step is
# individually easier, and the two effects very nearly cancel. Across a sample
# of 200 boards per size the mean score came out at 34 / 30 / 32 / 38 / 42 for
# 5x5 through 9x9, while the same figures divided by area fell steadily from
# 1.35 to 0.52 -- so normalising by area would have made almost every 9x9
# "easy" and most 5x5s "hard". The cut points below are the tertiles of that
# pooled sample (p33 = 21, p67 = 41); rerun scripts/calibrate.py if the
# deduction rules or tier weights change.
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
def grow_regions(
    n: int,
    solution: Sequence[int],
    rng: random.Random,
    balance: float | None = None,
) -> list[list[int]]:
    """Flood-fill ``n`` contiguous regions, one seeded on each queen.

    ``balance`` biases which region gets to claim the next cell. Higher values
    push the regions towards equal size; near zero they sprawl unevenly, which
    tends to produce more interesting -- and more often uniquely solvable --
    boards.
    """
    if balance is None:
        balance = rng.uniform(0.3, 2.5)

    grid = [[-1] * n for _ in range(n)]
    frontier: list[set[Cell]] = [set() for _ in range(n)]
    sizes = [1] * n

    for region, (r, c) in enumerate((r, solution[r]) for r in range(n)):
        grid[r][c] = region
        for dr, dc in ORTHOGONALS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < n and 0 <= nc < n:
                frontier[region].add((nr, nc))

    remaining = n * n - n
    while remaining:
        live = [i for i in range(n) if frontier[i]]
        if not live:  # unreachable on a connected grid, but stay safe
            break
        weights = [1.0 / (sizes[i] ** balance) for i in live]
        region = rng.choices(live, weights=weights, k=1)[0]

        pool = [cell for cell in frontier[region] if grid[cell[0]][cell[1]] == -1]
        if not pool:
            frontier[region].clear()
            continue
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

# Objective values are compared lexicographically and smaller is better:
#   (1, k) -- k solutions, still ambiguous
#   (0, m) -- unique, but deduction stalls with m queens still unplaced
# so (0, 0) is a finished puzzle.
_Objective = tuple[int, int]
_PERFECT: _Objective = (0, 0)


def _objective(
    grid: Sequence[Sequence[int]], n: int, limit: int
) -> tuple[_Objective, Board] | None:
    """Score a candidate region map. ``None`` if the map is not a legal board.

    ``limit`` caps the solution enumeration. When we already know the score to
    beat, passing it here lets the solver bail out early on hopeless
    candidates, which is most of them.
    """
    try:
        board = Board(grid)
    except InvalidBoardError:
        return None
    solutions = find_solutions(board, limit=limit)
    if len(solutions) != 1:
        return (1, len(solutions)), board
    result = solve_logically(board)
    return (0, n - len(result.placements)), board


def _local_search(
    n: int,
    rng: random.Random,
    max_iters: int = 120,
    neighbourhood: int = 200,
    plateau_limit: int = 6,
) -> tuple[Board, tuple[int, ...], LogicResult] | None:
    """Hill-climb a random layout into a unique, deduction-solvable board.

    Random region growth on its own almost never lands on a keeper above 6x6,
    but it lands *near* one often enough. Each move shifts a single cell across
    a region border, which keeps the seeded solution valid throughout, so the
    search only ever has to push the solution count down to one and then open
    up the deduction chain.
    """
    solution = random_solution(n, rng)
    grid = [list(row) for row in grow_regions(n, solution, rng)]
    scored = _objective(grid, n, _COUNT_CAP)
    if scored is None:
        return None
    current, board = scored
    plateau = 0

    for _ in range(max_iters):
        if current == _PERFECT:
            return board, solution, solve_logically(board)

        # A candidate can only beat us by being unique (when we already are)
        # or by having fewer solutions (when we are not).
        limit = current[1] if current[0] == 1 else 2
        best: _Objective | None = None
        best_grid: list[list[int]] | None = None
        for i, candidate in enumerate(perturbations(grid, solution, rng)):
            if i >= neighbourhood:
                break
            scored = _objective(candidate, n, limit)
            if scored is None:
                continue
            value, _ = scored
            if best is None or value < best:
                best, best_grid = value, candidate
                if value < current:
                    break  # take the first improvement we see
        if best_grid is None:
            return None

        if best < current:
            grid = best_grid
            plateau = 0
        elif plateau < plateau_limit:
            # Sideways move: the region map drifts even when the score does
            # not, which is usually enough to find a downhill move next round.
            grid = best_grid
            plateau += 1
            continue
        else:
            # Stuck. Kick the layout a few cells away and re-measure.
            for i, candidate in enumerate(perturbations(grid, solution, rng)):
                grid = candidate
                if i >= 2:
                    break
            plateau = 0

        rescored = _objective(grid, n, _COUNT_CAP)
        if rescored is None:
            return None
        current, board = rescored

    return None


def generate_puzzle(
    n: int,
    rng: random.Random | None = None,
    difficulty: str | None = None,
    attempts: int = 60,
    retune_budget: int = 60,
) -> Puzzle:
    """Generate one puzzle of size ``n``, optionally of a required difficulty.

    Raises :class:`GenerationError` if ``attempts`` local searches go by
    without a match.
    """
    if not MIN_SIZE <= n <= MAX_SIZE:
        raise ValueError(f"size must be between {MIN_SIZE} and {MAX_SIZE}, got {n}")
    if difficulty is not None and difficulty not in {b[0] for b in DIFFICULTY_BANDS}:
        raise ValueError(f"unknown difficulty {difficulty!r}")
    rng = rng or random.Random()

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
