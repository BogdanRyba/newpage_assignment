"""A tiny calculator used as ingestion/retrieval fixture data.

It exists so the sample repo has real, citable symbols across a few files.
"""

from __future__ import annotations


class Calculator:
    """Stateful calculator that accumulates a running total."""

    def __init__(self, start: float = 0.0) -> None:
        self.total = start

    def add(self, value: float) -> float:
        """Add ``value`` to the running total and return it."""
        self.total += value
        return self.total

    def subtract(self, value: float) -> float:
        """Subtract ``value`` from the running total and return it."""
        self.total -= value
        return self.total

    def reset(self) -> None:
        """Reset the running total back to zero."""
        self.total = 0.0


def divide(numerator: float, denominator: float) -> float:
    """Divide two numbers, raising on division by zero."""
    if denominator == 0:
        raise ZeroDivisionError("cannot divide by zero")
    return numerator / denominator
