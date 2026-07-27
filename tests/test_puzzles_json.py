"""Checks on the shipped puzzles.json.

Every puzzle in the file is re-verified from scratch here: the region map is
re-parsed, the exhaustive solver is asked how many solutions it has, and the
deduction solver is asked to finish it without guessing. Nothing is taken on
trust from the generator that wrote the file.
"""

import json
import unittest
from pathlib import Path

from queens.board import Board
from queens.generator import DIFFICULTY_BANDS, MAX_SIZE, MIN_SIZE, classify
from queens.logic import TIER_WEIGHTS, solve_logically
from queens.solver import find_solutions
from tests.reference import brute_force_solutions, is_legal

PUZZLES_PATH = Path(__file__).resolve().parent.parent / "puzzles.json"
DIFFICULTIES = [name for name, _ in DIFFICULTY_BANDS]
EXPECTED_SIZES = list(range(MIN_SIZE, MAX_SIZE + 1))


def load():
    if not PUZZLES_PATH.exists():  # pragma: no cover - file is committed
        raise unittest.SkipTest(
            f"{PUZZLES_PATH.name} is missing; "
            "run python scripts/generate_puzzles.py"
        )
    return json.loads(PUZZLES_PATH.read_text())


class PuzzleFileShapeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load()

    def test_header(self):
        self.assertEqual(self.data["schema_version"], 1)
        self.assertEqual(self.data["count"], len(self.data["puzzles"]))
        per_cell = self.data["generator"]["per_cell"]
        expected = per_cell * len(EXPECTED_SIZES) * len(DIFFICULTIES)
        self.assertEqual(self.data["count"], expected)

    def test_matrix_is_complete(self):
        """Every (size, difficulty) cell must hold exactly per_cell puzzles."""
        per_cell = self.data["generator"]["per_cell"]
        counts = {}
        for entry in self.data["puzzles"]:
            key = (entry["size"], entry["difficulty"])
            counts[key] = counts.get(key, 0) + 1
        for size in EXPECTED_SIZES:
            for difficulty in DIFFICULTIES:
                self.assertEqual(
                    counts.get((size, difficulty), 0),
                    per_cell,
                    f"cell {size}x{size} {difficulty} is not full",
                )

    def test_ids_are_unique(self):
        ids = [p["id"] for p in self.data["puzzles"]]
        self.assertEqual(len(set(ids)), len(ids))

    def test_no_duplicate_boards(self):
        boards = [
            (p["size"], tuple(tuple(row) for row in p["regions"]))
            for p in self.data["puzzles"]
        ]
        self.assertEqual(len(set(boards)), len(boards))

    def test_every_size_in_range_is_represented(self):
        sizes = {p["size"] for p in self.data["puzzles"]}
        self.assertEqual(sizes, set(EXPECTED_SIZES))

    def test_timing_is_reported_for_every_size(self):
        timing = self.data["generator"]["timing"]
        by_size = timing["by_size"]
        self.assertEqual(
            sorted(int(k) for k in by_size), EXPECTED_SIZES
        )
        for size, row in by_size.items():
            self.assertGreaterEqual(row["seconds"], 0.0)
            self.assertEqual(row["produced"], row["requested"])
            self.assertEqual(row["failed"], 0)
        self.assertEqual(
            len(timing["cells"]), len(EXPECTED_SIZES) * len(DIFFICULTIES)
        )
        # The per-size figures have to add up to the reported total.
        self.assertAlmostEqual(
            sum(row["seconds"] for row in by_size.values()),
            timing["total_seconds"],
            places=1,
        )

    def test_large_boards_are_reported_as_slower_than_small_ones(self):
        by_size = self.data["generator"]["timing"]["by_size"]
        smallest = by_size[str(EXPECTED_SIZES[0])]["seconds_each"]
        largest = by_size[str(EXPECTED_SIZES[-1])]["seconds_each"]
        self.assertGreater(largest, smallest)

    def test_every_difficulty_is_represented(self):
        found = {p["difficulty"] for p in self.data["puzzles"]}
        self.assertEqual(found, set(DIFFICULTIES))

    def test_summary_counts_match_the_puzzles(self):
        by_size = {}
        by_difficulty = {}
        for p in self.data["puzzles"]:
            by_size[str(p["size"])] = by_size.get(str(p["size"]), 0) + 1
            by_difficulty[p["difficulty"]] = by_difficulty.get(p["difficulty"], 0) + 1
        self.assertEqual(self.data["counts_by_size"], by_size)
        self.assertEqual(
            self.data["counts_by_difficulty"],
            {name: by_difficulty.get(name, 0) for name in DIFFICULTIES},
        )


class PuzzleFileContentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.puzzles = load()["puzzles"]

    def test_every_puzzle_has_exactly_one_solution(self):
        for entry in self.puzzles:
            with self.subTest(entry["id"]):
                board = Board(entry["regions"])
                solutions = find_solutions(board, limit=2)
                self.assertEqual(
                    len(solutions), 1, f"{entry['id']} does not have a unique solution"
                )
                self.assertEqual(list(solutions[0]), entry["solution"])

    def test_uniqueness_confirmed_independently_on_the_small_boards(self):
        # Brute force is a factorial enumeration, so cap it at 7x7 (5040 perms);
        # a 15x15 sweep would be 15! permutations.
        checked = 0
        for entry in self.puzzles:
            if entry["size"] > 7:
                continue
            with self.subTest(entry["id"]):
                found = brute_force_solutions(entry["regions"])
                self.assertEqual(
                    found,
                    [tuple(entry["solution"])],
                    f"{entry['id']}: brute force found {len(found)} solutions",
                )
            checked += 1
        self.assertGreater(checked, 0)

    def test_every_puzzle_is_solvable_without_guessing(self):
        for entry in self.puzzles:
            with self.subTest(entry["id"]):
                board = Board(entry["regions"])
                result = solve_logically(board)
                self.assertTrue(
                    result.solved, f"{entry['id']} cannot be solved by deduction"
                )
                self.assertEqual(list(result.solution()), entry["solution"])

    def test_recorded_metrics_match_a_fresh_run(self):
        for entry in self.puzzles:
            with self.subTest(entry["id"]):
                result = solve_logically(Board(entry["regions"]))
                metrics = entry["metrics"]
                self.assertEqual(metrics["steps"], result.step_count)
                self.assertEqual(metrics["score"], result.score)
                self.assertEqual(metrics["max_tier"], result.max_tier)
                self.assertEqual(
                    metrics["tier_counts"],
                    {str(k): v for k, v in sorted(result.tier_counts.items())},
                )
                self.assertEqual(
                    metrics["score"],
                    sum(TIER_WEIGHTS[s.tier] for s in result.steps),
                )

    def test_difficulty_label_matches_the_score(self):
        for entry in self.puzzles:
            with self.subTest(entry["id"]):
                self.assertEqual(
                    entry["difficulty"], classify(entry["metrics"]["score"])
                )

    def test_solutions_obey_the_rules(self):
        for entry in self.puzzles:
            with self.subTest(entry["id"]):
                board = Board(entry["regions"])  # validates squareness, regions
                self.assertEqual(board.n, entry["size"])
                self.assertTrue(board.is_valid_solution(entry["solution"]))
                # Independent restatement of the rules, sharing no code.
                self.assertTrue(is_legal(entry["regions"], entry["solution"]))


if __name__ == "__main__":
    unittest.main()
