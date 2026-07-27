import unittest

from queens.board import Board, InvalidBoardError


class BoardValidationTest(unittest.TestCase):
    def test_from_rows_round_trip(self):
        rows = ["AABBB", "AABBB", "CCCBB", "CDDDE", "CDDDE"]
        board = Board.from_rows(rows)
        self.assertEqual(board.n, 5)
        self.assertEqual(board.to_rows(), rows)

    def test_rejects_non_square(self):
        with self.assertRaises(InvalidBoardError):
            Board([[0, 1, 2], [0, 1, 2]])

    def test_rejects_wrong_region_count(self):
        # 3x3 using only two regions.
        with self.assertRaises(InvalidBoardError):
            Board([[0, 0, 1], [0, 0, 1], [0, 1, 1]])

    def test_rejects_out_of_range_region_id(self):
        with self.assertRaises(InvalidBoardError):
            Board([[0, 1, 5], [0, 1, 2], [0, 1, 2]])

    def test_rejects_disconnected_region(self):
        # Region 0 sits in two opposite corners with no path between them.
        grid = [
            [0, 1, 1],
            [2, 2, 1],
            [2, 2, 0],
        ]
        with self.assertRaises(InvalidBoardError):
            Board(grid)

    def test_region_cells_partition_the_grid(self):
        board = Board.from_rows(["AABBB", "AABBB", "CCCBB", "CDDDE", "CDDDE"])
        seen = [cell for cells in board.region_cells for cell in cells]
        self.assertEqual(len(seen), 25)
        self.assertEqual(set(seen), set(board.cells()))


class AttackedByTest(unittest.TestCase):
    def setUp(self):
        self.board = Board.from_rows(["AABBB", "AABBB", "CCCBB", "CDDDE", "CDDDE"])

    def test_covers_row_column_region_and_diagonals(self):
        attacked = self.board.attacked_by((2, 2))
        self.assertNotIn((2, 2), attacked)
        for c in range(5):
            if c != 2:
                self.assertIn((2, c), attacked)
        for r in range(5):
            if r != 2:
                self.assertIn((r, 2), attacked)
        for cell in [(1, 1), (1, 3), (3, 1), (3, 3)]:
            self.assertIn(cell, attacked)
        # Region C also contains (3, 0) and (4, 0).
        self.assertIn((3, 0), attacked)
        self.assertIn((4, 0), attacked)

    def test_orthogonal_neighbours_are_covered_by_row_and_column(self):
        attacked = self.board.attacked_by((0, 0))
        self.assertIn((0, 1), attacked)
        self.assertIn((1, 0), attacked)


class SolutionCheckTest(unittest.TestCase):
    def setUp(self):
        self.board = Board.from_rows(["AABBB", "AABBB", "CCCBB", "CDDDE", "CDDDE"])

    def test_rejects_repeated_column(self):
        self.assertFalse(self.board.is_valid_solution([0, 0, 1, 2, 3]))

    def test_rejects_diagonal_touch(self):
        # One region per row, so only the adjacency rule can reject anything.
        board = Board([[r] * 4 for r in range(4)])
        self.assertFalse(board.is_valid_solution([0, 1, 2, 3]))
        self.assertTrue(board.is_valid_solution([1, 3, 0, 2]))

    def test_rejects_repeated_region(self):
        board = Board.from_rows(["ABBB", "ACCB", "ACDD", "ACDD"])
        # [1, 3, 0, 2] has distinct rows, columns and no diagonal contact, but
        # (0,1) and (1,3) are both in region B.
        self.assertEqual(board.region_at((0, 1)), board.region_at((1, 3)))
        self.assertFalse(board.is_valid_solution([1, 3, 0, 2]))

    def test_rejects_wrong_length(self):
        self.assertFalse(self.board.is_valid_solution([0, 1, 2]))


if __name__ == "__main__":
    unittest.main()
