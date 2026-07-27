"""Core engine for Queens-style logic puzzles.

An ``n x n`` grid is split into ``n`` contiguous colour regions. Place one
queen in every row, every column and every region, with no two queens
diagonally adjacent.

Public surface:

* :class:`~queens.board.Board` -- the grid and its region map
* :mod:`queens.solver` -- exhaustive search, uniqueness checking
* :mod:`queens.logic` -- no-guessing deduction solver and difficulty metrics
* :mod:`queens.generator` -- puzzle generation
"""

from .board import Board, InvalidBoardError
from .generator import (
    DIFFICULTY_BANDS,
    GenerationError,
    Puzzle,
    classify,
    generate_many,
    generate_puzzle,
)
from .logic import LogicResult, explain, is_logically_solvable, solve_logically
from .solver import count_solutions, find_solutions, has_unique_solution, solve

__all__ = [
    "Board",
    "InvalidBoardError",
    "DIFFICULTY_BANDS",
    "GenerationError",
    "Puzzle",
    "classify",
    "generate_many",
    "generate_puzzle",
    "LogicResult",
    "explain",
    "is_logically_solvable",
    "solve_logically",
    "count_solutions",
    "find_solutions",
    "has_unique_solution",
    "solve",
]
