import random
import unittest

from queens.board import Board, ORTHOGONALS
from queens.generator import (
    DIFFICULTY_BANDS,
    MAX_SIZE,
    MIN_SIZE,
    GenerationError,
    classify,
    generate_many,
    generate_puzzle,
    grow_regions,
    perturbations,
    random_solution,
)
from queens.logic import solve_logically
from queens.solver import find_solutions
from tests.reference import brute_force_solutions, is_legal

DIFFICULTIES = [name for name, _ in DIFFICULTY_BANDS]


def assert_regions_contiguous(case, board):
    for region, cells in enumerate(board.region_cells):
        case.assertTrue(cells, f"region {region} is empty")
        remaining = set(cells)
        start = next(iter(remaining))
        stack, seen = [start], {start}
        remaining.discard(start)
        while stack:
            r, c = stack.pop()
            for dr, dc in ORTHOGONALS:
                nxt = (r + dr, c + dc)
                if nxt in remaining:
                    remaining.discard(nxt)
                    seen.add(nxt)
                    stack.append(nxt)
        case.assertFalse(remaining, f"region {region} is split into pieces")


class RandomSolutionTest(unittest.TestCase):
    def test_placements_obey_every_rule_except_regions(self):
        rng = random.Random(1)
        for n in range(MIN_SIZE, MAX_SIZE + 1):
            for _ in range(30):
                solution = random_solution(n, rng)
                self.assertEqual(len(solution), n)
                self.assertEqual(len(set(solution)), n)
                for r in range(n - 1):
                    self.assertNotEqual(abs(solution[r] - solution[r + 1]), 1)


class GrowRegionsTest(unittest.TestCase):
    def test_regions_tile_the_board_and_hold_one_queen_each(self):
        rng = random.Random(2)
        for n in range(MIN_SIZE, MAX_SIZE + 1):
            for _ in range(20):
                solution = random_solution(n, rng)
                board = Board(grow_regions(n, solution, rng))
                assert_regions_contiguous(self, board)
                self.assertTrue(board.is_valid_solution(solution))
                self.assertTrue(is_legal(board.regions, solution))


class PerturbationTest(unittest.TestCase):
    def test_moves_keep_the_board_legal_and_the_seed_solution_valid(self):
        rng = random.Random(3)
        n = 7
        solution = random_solution(n, rng)
        grid = grow_regions(n, solution, rng)
        checked = 0
        for i, candidate in enumerate(perturbations(grid, solution, rng)):
            if i >= 40:
                break
            board = Board(candidate)  # raises if regions broke
            assert_regions_contiguous(self, board)
            self.assertTrue(board.is_valid_solution(solution))
            self.assertEqual(sum(1 for _ in board.cells()), n * n)
            differing = sum(
                1
                for r in range(n)
                for c in range(n)
                if candidate[r][c] != grid[r][c]
            )
            self.assertEqual(differing, 1, "a move should shift exactly one cell")
            checked += 1
        self.assertGreater(checked, 0)


class ClassifyTest(unittest.TestCase):
    def test_bands_are_ordered_and_cover_every_score(self):
        seen = [classify(score) for score in range(0, 400)]
        self.assertEqual(set(seen), set(DIFFICULTIES))
        # Difficulty must never go down as the score goes up.
        ranks = [DIFFICULTIES.index(name) for name in seen]
        self.assertEqual(ranks, sorted(ranks))


class GeneratePuzzleTest(unittest.TestCase):
    def test_generated_puzzles_are_unique_and_logically_solvable(self):
        rng = random.Random(2024)
        for n in range(MIN_SIZE, MAX_SIZE + 1):
            puzzle = generate_puzzle(n, rng=rng)
            board = puzzle.board
            self.assertEqual(board.n, n)
            assert_regions_contiguous(self, board)

            solutions = find_solutions(board, limit=2)
            self.assertEqual(len(solutions), 1, f"{n}x{n} puzzle is not unique")
            self.assertEqual(solutions[0], puzzle.solution)
            self.assertTrue(is_legal(board.regions, puzzle.solution))

            result = solve_logically(board)
            self.assertTrue(result.solved, f"{n}x{n} puzzle needs a guess")
            self.assertEqual(result.solution(), puzzle.solution)
            self.assertEqual(puzzle.steps, result.step_count)
            self.assertEqual(puzzle.score, result.score)
            self.assertEqual(puzzle.difficulty, classify(result.score))

    def test_uniqueness_confirmed_by_brute_force(self):
        rng = random.Random(77)
        for n in (5, 6, 7):
            puzzle = generate_puzzle(n, rng=rng)
            all_solutions = brute_force_solutions(puzzle.board.regions)
            self.assertEqual(
                all_solutions,
                [puzzle.solution],
                f"brute force disagrees on the {n}x{n} puzzle",
            )

    def test_rejects_sizes_outside_the_supported_range(self):
        for bad in (4, 10):
            with self.assertRaises(ValueError):
                generate_puzzle(bad, rng=random.Random(0))

    def test_rejects_unknown_difficulty(self):
        with self.assertRaises(ValueError):
            generate_puzzle(6, rng=random.Random(0), difficulty="impossible")

    def test_reports_failure_rather_than_looping_forever(self):
        with self.assertRaises(GenerationError):
            generate_puzzle(9, rng=random.Random(0), difficulty="hard", attempts=0)

    def test_honours_a_requested_difficulty(self):
        rng = random.Random(31)
        for difficulty in DIFFICULTIES:
            puzzle = generate_puzzle(6, rng=rng, difficulty=difficulty)
            self.assertEqual(puzzle.difficulty, difficulty)

    def test_is_deterministic_for_a_given_seed(self):
        first = generate_puzzle(6, rng=random.Random(12345))
        second = generate_puzzle(6, rng=random.Random(12345))
        self.assertEqual(first.board.regions, second.board.regions)
        self.assertEqual(first.solution, second.solution)
        self.assertEqual(first.score, second.score)


class GenerateManyTest(unittest.TestCase):
    def test_produces_distinct_puzzles_across_sizes(self):
        puzzles = generate_many(12, sizes=(5, 6), seed=8)
        self.assertEqual(len(puzzles), 12)
        self.assertEqual(len({p.key() for p in puzzles}), 12)
        self.assertEqual({p.size for p in puzzles}, {5, 6})
        for puzzle in puzzles:
            self.assertEqual(len(find_solutions(puzzle.board, limit=2)), 1)
            self.assertTrue(solve_logically(puzzle.board).solved)

    def test_to_dict_round_trips_through_a_board(self):
        puzzle = generate_puzzle(5, rng=random.Random(6))
        data = puzzle.to_dict("q5-001")
        self.assertEqual(data["id"], "q5-001")
        rebuilt = Board(data["regions"])
        self.assertEqual(rebuilt.regions, puzzle.board.regions)
        self.assertTrue(rebuilt.is_valid_solution(data["solution"]))
        self.assertEqual(data["metrics"]["score"], puzzle.score)


if __name__ == "__main__":
    unittest.main()
