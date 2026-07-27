import random
import unittest

from queens.board import Board
from queens.generator import generate_puzzle, grow_regions, random_solution
from queens.logic import TIER_WEIGHTS, explain, solve_logically
from queens.solver import find_solutions
from tests.reference import brute_force_solutions


def _sample_boards(rng, count, sizes=(5, 6, 7)):
    """Raw region growth: mostly ambiguous boards, which is what we want here.

    Only about one in a hundred of these has a unique solution, so anything
    that needs solvable boards should go through the generator instead.
    """
    for _ in range(count):
        n = rng.choice(sizes)
        solution = random_solution(n, rng)
        grid = grow_regions(n, solution, rng)
        yield Board(grid)


class SoundnessTest(unittest.TestCase):
    """Nothing the deduction solver rules out may appear in a real solution.

    This is the property that makes "solvable by logic" mean anything. If a
    rule could discard a cell that a genuine solution uses, the generator would
    happily ship boards whose intended answer contradicts the hints.
    """

    def test_eliminations_never_touch_a_real_solution(self):
        rng = random.Random(4242)
        for board in _sample_boards(rng, 90):
            solutions = brute_force_solutions(board.regions)
            if not solutions:
                continue
            live = {
                (r, c)
                for solution in solutions
                for r, c in enumerate(solution)
            }
            solver_result = solve_logically(board)
            for step in solver_result.steps:
                for cell in step.eliminated:
                    self.assertNotIn(
                        cell,
                        live,
                        f"rule {step.rule!r} discarded {cell}, which a solution uses\n"
                        + "\n".join(board.to_rows()),
                    )

    def test_placements_hold_in_every_solution(self):
        rng = random.Random(1717)
        for board in _sample_boards(rng, 90):
            solutions = brute_force_solutions(board.regions)
            if not solutions:
                continue
            result = solve_logically(board)
            for row, col in result.placements.items():
                for solution in solutions:
                    self.assertEqual(
                        solution[row],
                        col,
                        "solver committed to a placement that not every "
                        f"solution shares:\n" + "\n".join(board.to_rows()),
                    )

    def test_never_claims_to_solve_an_ambiguous_board(self):
        rng = random.Random(31337)
        seen_ambiguous = 0
        for board in _sample_boards(rng, 120):
            count = len(find_solutions(board, limit=2))
            result = solve_logically(board)
            if count != 1:
                seen_ambiguous += 1
                self.assertFalse(result.solved)
        self.assertGreater(seen_ambiguous, 0, "sample had no ambiguous boards")


class CompletenessTest(unittest.TestCase):
    def test_solved_result_matches_the_exhaustive_solution(self):
        rng = random.Random(555)
        for size in (5, 6, 7, 8, 9):
            board = generate_puzzle(size, rng=rng).board
            result = solve_logically(board)
            self.assertTrue(result.solved)
            solutions = find_solutions(board, limit=2)
            self.assertEqual(len(solutions), 1)
            self.assertEqual(result.solution(), solutions[0])
            self.assertTrue(board.is_valid_solution(result.solution()))

    def test_deduction_agrees_with_brute_force_on_generated_boards(self):
        rng = random.Random(556)
        for size in (5, 6, 7):
            board = generate_puzzle(size, rng=rng).board
            result = solve_logically(board)
            self.assertTrue(result.solved)
            self.assertEqual(brute_force_solutions(board.regions), [result.solution()])

    def test_detects_a_contradictory_board(self):
        # No legal placement exists on this 3x3 (see test_solver).
        board = Board([[0, 1, 2]] * 3)
        result = solve_logically(board)
        self.assertTrue(result.contradiction)
        self.assertFalse(result.solved)
        self.assertIsNone(result.solution())


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.board = generate_puzzle(6, rng=random.Random(808)).board
        self.result = solve_logically(self.board)
        self.assertTrue(self.result.solved)
        self.assertGreater(self.result.step_count, 4)

    def test_score_is_the_weighted_step_total(self):
        expected = sum(TIER_WEIGHTS[step.tier] for step in self.result.steps)
        self.assertEqual(self.result.score, expected)

    def test_tier_counts_add_up_to_the_step_count(self):
        self.assertEqual(sum(self.result.tier_counts.values()), self.result.step_count)
        # max_tier is the highest tier that actually fired, not just the
        # highest key present in the counter.
        fired = [tier for tier, count in self.result.tier_counts.items() if count]
        self.assertEqual(self.result.max_tier, max(fired))

    def test_cheaper_tiers_are_preferred(self):
        # Restricting the solver to tier 1 can never make it do more work.
        limited = solve_logically(self.board, tier_cap=1)
        self.assertLessEqual(limited.score, self.result.score)

    def test_explain_covers_every_step(self):
        text = explain(self.board, self.result)
        lines = text.splitlines()
        self.assertEqual(len(lines), self.result.step_count + 1)
        self.assertIn("solved", lines[-1])


if __name__ == "__main__":
    unittest.main()
