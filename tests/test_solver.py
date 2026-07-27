import random
import unittest

from queens.board import Board
from queens.generator import generate_puzzle, grow_regions, random_solution
from queens.solver import (
    count_solutions,
    find_solutions,
    has_unique_solution,
    solve,
    solve_with_placements,
)
from tests.reference import brute_force_solutions, is_legal


class SolverBasicsTest(unittest.TestCase):
    def test_solves_a_hand_built_board(self):
        board = Board.from_rows(
            [
                "AABBB",
                "AABBB",
                "CCCBB",
                "CDDDE",
                "CDDDE",
            ]
        )
        solutions = find_solutions(board)
        for solution in solutions:
            self.assertTrue(board.is_valid_solution(solution))
            self.assertTrue(is_legal(board.regions, solution))

    def test_reports_no_solution(self):
        # Every region is a column, so the one-per-column rule and the
        # one-per-region rule coincide; three columns cannot be filled without
        # two queens touching diagonally.
        board = Board([[0, 1, 2]] * 3)
        self.assertEqual(find_solutions(board), [])
        self.assertIsNone(solve(board))
        self.assertEqual(count_solutions(board), 0)
        self.assertFalse(has_unique_solution(board))

    def test_limit_stops_early(self):
        board = Board([[r] * 6 for r in range(6)])  # one region per row
        self.assertGreater(count_solutions(board, cap=50), 1)
        self.assertEqual(len(find_solutions(board, limit=3)), 3)

    def test_solve_with_placements_respects_fixed_queens(self):
        board = Board([[r] * 6 for r in range(6)])
        every = find_solutions(board)
        pinned = solve_with_placements(board, [(0, 2)])
        self.assertEqual(sorted(pinned), sorted(s for s in every if s[0] == 2))
        self.assertTrue(pinned)

    def test_solve_with_placements_rejects_contradictory_input(self):
        board = Board([[r] * 6 for r in range(6)])
        self.assertEqual(solve_with_placements(board, [(0, 2), (0, 4)]), [])


class SolverAgainstBruteForceTest(unittest.TestCase):
    """The pruned solver must agree exactly with the naive enumeration."""

    def test_matches_brute_force_on_random_boards(self):
        rng = random.Random(20240517)
        for _ in range(120):
            n = rng.choice([5, 6, 7])
            solution = random_solution(n, rng)
            grid = grow_regions(n, solution, rng)
            board = Board(grid)

            fast = sorted(find_solutions(board))
            slow = sorted(brute_force_solutions(grid))
            self.assertEqual(fast, slow, f"disagreement on {board.to_rows()}")
            # The placement the regions were grown from is always one of them.
            self.assertIn(solution, slow)

    def test_uniqueness_flag_matches_brute_force(self):
        rng = random.Random(99)
        for _ in range(150):
            n = rng.choice([5, 6])
            grid = grow_regions(n, random_solution(n, rng), rng)
            expected = len(brute_force_solutions(grid)) == 1
            self.assertEqual(has_unique_solution(Board(grid)), expected)

    def test_uniqueness_flag_is_true_on_boards_built_to_be_unique(self):
        # Raw region growth is unique roughly one time in a hundred, so the
        # positive case has to come from the generator to be worth testing.
        rng = random.Random(100)
        for n in (5, 6, 7):
            puzzle = generate_puzzle(n, rng=rng)
            self.assertTrue(has_unique_solution(puzzle.board))
            self.assertEqual(count_solutions(puzzle.board, cap=5), 1)
            self.assertEqual(brute_force_solutions(puzzle.board.regions),
                             [puzzle.solution])


if __name__ == "__main__":
    unittest.main()
