# meowdoku-game

Core engine for a Queens-style logic puzzle: solver, deduction engine,
difficulty rating and puzzle generator. Pure Python 3.11, no dependencies.

## Rules

An `n x n` grid is split into exactly `n` contiguous colour regions. Place one
queen in every **row**, every **column** and every **colour region**, and no two
queens may be **diagonally adjacent**.

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
python -m queens show q7-004                       # print a puzzle from puzzles.json
python -m queens solve q7-004 --explain            # solve it and print the reasoning
python scripts/generate_puzzles.py --count 100     # rebuild puzzles.json
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

The score is used **raw, not divided by board area**. That is counter-intuitive,
so it is worth saying why: a bigger board needs more steps, but each individual
step is easier, and across a 200-board sample per size the two effects very
nearly cancel. Mean scores came out at 34 / 30 / 32 / 38 / 42 for 5×5 through
9×9 — near enough flat. The same figures divided by area fell steadily from
1.35 to 0.52, so normalising by area would have labelled almost every 9×9
"easy" and most 5×5s "hard". The band cut points are the tertiles of that
pooled sample (p33 = 21, p67 = 41), which splits it 350 / 307 / 343.

Rerun `python scripts/calibrate.py` after changing a rule or a tier weight; both
feed straight into the score and will move the bands.

## Generation

The generator works backwards from an answer:

1. Draw a random legal queen placement — that is the solution.
2. Seed one region on each queen and flood-fill outwards at random until the
   regions tile the board. Seeding on the queens makes the one-per-region rule
   hold automatically; flood filling keeps every region contiguous.
3. Require exactly one solution.
4. Require the deduction solver to finish it.

Steps 3 and 4 reject nearly everything: raw region growth lands on a uniquely
solvable board only about **1%** of the time, and the rate falls off a cliff
above 6×6. So the generator does not throw failures away. It hill-climbs
instead, moving one cell at a time across a region border:

```
objective (lower is better, compared lexicographically):
  (1, k)  ->  k solutions, still ambiguous
  (0, m)  ->  unique, but deduction stalls with m queens unplaced
  (0, 0)  ->  done
```

Every move keeps the seeded solution valid, so the search only ever has to push
the solution count down to one and then open up the deduction chain. Sideways
moves and a random kick get it out of local minima. That takes 9×9 from
*effectively never* to a ~60% hit rate per attempt at under a second each.

Asking for a specific difficulty runs the same climb again with the score as the
objective, so the band comes out of local search rather than rejection sampling.

## puzzles.json

100 puzzles: 20 per size from 5×5 to 9×9, split 35 easy / 35 medium / 30 hard.
Each entry is re-verified from scratch before being written — the file is
rebuilt with `python scripts/generate_puzzles.py` and takes about 40 seconds.

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
twice.

The suite covers:

* the fast solver agreeing exactly with brute force on random boards
* **soundness** — no deduction rule ever discards a cell that a real solution
  uses, and no placement is committed that not every solution shares
* the deduction solver never claiming to solve an ambiguous board
* generated puzzles being unique, contiguous and guess-free
* every puzzle in `puzzles.json` re-verified from the file, with the small
  boards double-checked by brute force
