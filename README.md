# meowdoku-game

Core engine for a Queens-style logic puzzle: solver, deduction engine,
difficulty rating and puzzle generator. Pure Python 3.11, no dependencies.

## Rules

An `n x n` grid is split into exactly `n` contiguous colour regions. Place one
queen in every **row**, every **column** and every **colour region**, and no two
queens may be **diagonally adjacent**. Sizes 5×5 through 15×15 are supported.

Two queens can never be orthogonally adjacent either — that would put them in
the same row or column — so the diagonal rule is the only adjacency constraint
that has to be checked explicitly.

```
A A B B B          A Q B B B
A A B B B          B B B A Q      <- 'Q' marks a queen
C C C B B    -->   Q C C B B
C D D D E          C D Q D E
C D D D E          C D D D Q
```

## Layout

| file | what it does |
| --- | --- |
| `queens/board.py` | grid + region map, validation, the attack set of a cell |
| `queens/solver.py` | exhaustive solver; counts solutions, answers "is it unique?" |
| `queens/logic.py` | no-guessing deduction solver; produces the difficulty metrics |
| `queens/generator.py` | puzzle generation and difficulty classification |
| `scripts/generate_puzzles.py` | writes `puzzles.json` |
| `scripts/calibrate.py` | samples boards and reports the score distribution |
| `tests/` | unit tests, including an independent uniqueness check |

## Quick start

```bash
python -m queens generate 7 --difficulty hard      # make one and show its answer
python -m queens generate 15                       # 15x15 works too, just slower
python -m queens show q7-004                       # print a puzzle from puzzles.json
python -m queens solve q7-004 --explain            # solve it and print the reasoning
python scripts/generate_puzzles.py --per-cell 3    # rebuild puzzles.json (matrix)
python scripts/generate_puzzles.py --max-size 9    # ...or just the fast sizes
python -m unittest discover -s tests -t .          # run the tests
```

```python
from queens import Board, has_unique_solution, solve_logically, generate_puzzle

board = Board.from_rows(["AABBB", "AABBB", "CCCBB", "CDDDE", "CDDDE"])
has_unique_solution(board)          # -> bool
solve_logically(board).solution()   # -> (col_of_row_0, col_of_row_1, ...) or None

puzzle = generate_puzzle(7, difficulty="medium")
puzzle.solution, puzzle.difficulty, puzzle.steps, puzzle.score
```

## The exhaustive solver

`queens/solver.py` walks the board a row at a time. Every row holds exactly one
queen, so a partial position is fully described by three things: which columns
are used, which regions are used, and the column chosen in the previous row —
the only row that can be diagonally adjacent to the current one. The first two
are bitmasks.

Two prunings do most of the work:

* **Region liveness.** `alive_from[r]` is the set of regions that still have a
  cell in rows `r..n-1`. A region that is neither used nor alive can never be
  filled, so the branch is dead. It costs one mask comparison per node and it
  cuts the 9×9 search by roughly 5×.
* **Ordering.** Within a row, cells from small regions are tried first.

Uniqueness checking is just `find_solutions(board, limit=2)` — the search stops
the moment a second solution appears.

## The deduction solver

`queens/logic.py` answers a different question: *can a person solve this without
guessing, and how hard is it?* It never branches and never assumes a placement,
so any board it finishes is guaranteed guess-free. Every rule only ever removes
candidates that cannot appear in **any** solution of the current position.

Rules are grouped into tiers, and the solver always applies the cheapest tier
that fires:

| tier | rule | what it says |
| --- | --- | --- |
| 1 | `forced-single` | a row, column or region has one candidate left — place the queen |
| 2 | `confinement` | every candidate of one unit sits inside another unit, so the rest of that unit is out (a region confined to one row clears the rest of the row) |
| 3 | `shared-attack` | every candidate of a unit attacks cell `X`, so `X` is out wherever that unit's queen ends up |
| 4 | `hall-set` | `k` units between them can only reach `k` units of another family, so they own those outright — the naked/hidden set family, applied across all six row/column/region pairings |

Tier 3 subsumes tier 2, and tier 1 subsumes plain elimination, but the tiers are
kept separate because they are what the difficulty rating is built from.

`explain(board)` prints the whole chain of reasoning, which doubles as a hint
feed for a UI.

## Difficulty

Difficulty is measured by the **number of deduction steps** needed to solve the
board, weighted by how demanding each step is:

```
score = Σ weight(tier of step)      weights: T1=1, T2=3, T3=7, T4=15
```

| band | score |
| --- | --- |
| easy | 0–21 |
| medium | 22–39 |
| hard | 40+ |

The score is used **raw, not divided by board area**, and the bands are the same
at every size — a "hard" puzzle should mean the same amount of reasoning whether
it is 5×5 or 15×15.

Normalising by area would be much worse. Sampled mean scores by size:

| n | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mean score | 32 | 29 | 32 | 36 | 37 | 43 | 22 | 21 | 33 | 25 | 22 |
| ÷ area | 1.28 | 0.79 | 0.65 | 0.56 | 0.46 | 0.43 | 0.18 | 0.15 | 0.19 | 0.13 | 0.10 |

Divided by area the figure falls 13×, so an area-based rule would call
essentially every large board easy. Raw, the bands hold their meaning.

The dip at 11×11 is real and worth knowing about: above the counting crossover
the generator grows deliberately lopsided regions, and a small region pins its
queen immediately, so those boards need less reasoning on average. It costs
nothing in output balance — the matrix asks for each band explicitly and walks a
board into it — but the hard cells at large sizes do take longer to fill.

The cut points are the tertiles of the pooled sample (p33 = 18, p67 = 38),
rounded, splitting it 411 / 265 / 324. Rerun `python scripts/calibrate.py` after
changing a rule or a tier weight; both feed straight into the score and will
move the bands.

## Generation

The generator works backwards from an answer:

1. Draw a random legal queen placement — that is the solution.
2. Seed one region on each queen and flood-fill outwards at random until the
   regions tile the board. Seeding on the queens makes the one-per-region rule
   hold automatically; flood filling keeps every region contiguous.
3. Require exactly one solution.
4. Require the deduction solver to finish it.

Steps 3 and 4 reject nearly everything, so the generator does not throw failures
away — it hill-climbs, moving one cell at a time across a region border. Every
move keeps the seeded solution valid, so the search only has to make the board
more constrained. Sideways moves and a random kick get it out of local minima.

Three things make this work across the whole 5×5–15×15 range.

### Region size variance is the main lever

Regions hold `n` cells on average, so as the board grows each region pins its
queen *less*, and the solution count explodes. Measured medians for the raw
solution count of a freshly grown 15×15 board:

| growth | median solutions |
| --- | --- |
| even regions (`balance ≥ 0`) | 200 000+ (measurement cap) |
| lopsided regions (`balance = -2`) | ~300 |

Three orders of magnitude. Nothing else came close — compact regions and
row/column-banded regions both made it *worse*. So the `balance` window slides
negative as the board grows, and a per-region size cap of 3–4×`n` stops a
strongly negative balance from producing one region that swallows the grid
(uniquely solvable, but a degenerate puzzle).

### Two objectives, because the cheap one flips over

```
counting   (1, k, 0)   k solutions, still ambiguous
           (0, m, 0)   unique, but deduction stalls with m queens unplaced
deduction  (0, m, c)   deduction stalls with m queens unplaced, c candidates
```

Counting solutions is a sharp gradient and it is cheap *while a board is
ambiguous* — but expensive once it is nearly unique, because the solver then has
to exhaust the whole tree to prove no second solution exists, for every
candidate move. Profiling a 13×13 search driven by counting put **89%** of its
runtime in the exhaustive solver.

So above 10×10 the search switches to pure deduction and never counts at all.
It can do that because the rules are sound: every queen the deduction solver
commits to holds in every solution, so **if it places all `n` queens, all
solutions agree on all `n` cells and the board is necessarily unique**.
Uniqueness is still verified once per finished puzzle — it is just no longer in
the inner loop. Every board produced this way has checked out as unique.

Below the crossover, counting wins clearly (0.12s per 7×7 puzzle against 1.2s
for deduction), so both modes stay.

### Cost, and what it buys

Seconds per finished puzzle, from the run that produced the shipped
`puzzles.json` (9 puzzles per size, difficulty targeted):

| n | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s/puzzle | 0.02 | 0.05 | 0.14 | 0.33 | 2.3 | 3.9 | 3.3 | 4.7 | 23.3 | 18.6 | 25.5 |

Three orders of magnitude across the range, and the whole 99-puzzle matrix in
about 12 minutes. The climb is intrinsic, not an artefact: bigger boards have
weaker region constraints, so uniquely solvable layouts are genuinely rarer.
It is not perfectly monotonic either — 14×14 came in faster than 13×13 — because
success is a hit rate on random restarts, so an unlucky size costs extra
attempts.

Every run records these per-size timings, on stdout and in the output file.

Asking for a specific difficulty runs the same climb again with the score as the
objective, so the band comes out of local search rather than rejection sampling.

## puzzles.json

A full **size × difficulty matrix**: every board size from 5×5 to 15×15, in each
of easy/medium/hard, with `--per-cell` puzzles in each of the 33 cells (3 by
default, so 99 puzzles). Each entry is re-verified from scratch before being
written.

The file also records how long each size took, since that is the thing that
varies by three orders of magnitude across the range:

```jsonc
"generator": {
  "seed": 20240517,
  "per_cell": 3,
  "timing": {
    "total_seconds": 1234.5,
    "by_size": {
      "5":  {"produced": 9, "seconds":   0.4, "seconds_each": 0.04, "failed": 0},
      "15": {"produced": 9, "seconds": 512.7, "seconds_each": 56.9, "failed": 0}
    },
    "cells": [ /* one entry per (size, difficulty) pair */ ]
  }
}
```

The same breakdown is printed live during a run, per cell and per size.

```jsonc
{
  "id": "q7-004",
  "size": 7,
  "regions": [[0, 0, 1, ...], ...],   // regions[r][c] = colour region id of (r, c)
  "solution": [1, 3, 5, ...],         // solution[r]   = column of the queen in row r
  "difficulty": "medium",
  "metrics": {
    "steps": 14,                      // deduction steps
    "score": 33,                      // tier-weighted score
    "max_tier": 3,                    // hardest rule the board needed
    "tier_counts": {"1": 7, "2": 3, "3": 4, "4": 0}
  }
}
```

Every puzzle in the file is guaranteed to have **exactly one solution** and to
be **solvable by deduction alone**.

## Tests

```bash
python -m unittest discover -s tests -t .
```

`tests/reference.py` holds a deliberately naive solver that enumerates every
column permutation and filters it with the rules read straight off the puzzle
statement. It shares no code with `queens/solver.py`, so the uniqueness claims
are checked against something independent rather than against the same algorithm
twice. It is a factorial enumeration, so it is applied up to 7×7 — beyond that
uniqueness is checked with the fast solver only.

The suite covers:

* the fast solver agreeing exactly with brute force on random boards
* **soundness** — no deduction rule ever discards a cell that a real solution
  uses, and no placement is committed that not every solution shares
* the deduction solver never claiming to solve an ambiguous board
* generated puzzles being unique, contiguous and guess-free
* the growth and search schedules behaving across the size range — the balance
  window sliding negative, the size cap holding, the objective mode and attempt
  budget tracking the crossover
* `generate_matrix` filling every cell and reporting per-size timings that add
  up to the run total
* every puzzle in `puzzles.json` re-verified from the file, with the small
  boards double-checked by brute force
