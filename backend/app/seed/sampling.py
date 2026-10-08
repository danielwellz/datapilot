"""Small sampling helpers shared by the calendar and the generator."""

import math
from bisect import bisect
from collections.abc import Sequence
from itertools import accumulate
from random import Random


class WeightedPicker[T]:
    """Picks items with probability proportional to their weight.

    The cumulative weights are computed once, so each pick is a single
    binary search: much cheaper than ``Random.choices`` with plain weights
    when picking millions of times from the same list.
    """

    def __init__(self, items: Sequence[T], weights: Sequence[float]) -> None:
        if len(items) != len(weights) or not items:
            raise ValueError("items and weights must be non-empty and the same length")
        self._items = items
        self._cumulative = list(accumulate(weights))

    def pick(self, rng: Random, *, among_first: int | None = None) -> T:
        """Pick one item, optionally only among the first ``among_first`` items."""
        limit = len(self._items) if among_first is None else among_first
        if not 0 < limit <= len(self._items):
            raise ValueError(f"among_first must be between 1 and {len(self._items)}")
        point = rng.random() * self._cumulative[limit - 1]
        return self._items[bisect(self._cumulative, point, hi=limit)]


def apportion(weights: Sequence[float], total: int) -> list[int]:
    """Split ``total`` into whole numbers proportional to ``weights``.

    Largest-remainder rounding: floor every share, then hand the units left
    over to the shares that lost the most. Ties go to the earlier position,
    so the result is deterministic and always adds up to ``total``.
    """
    scale = total / math.fsum(weights)
    exact = [weight * scale for weight in weights]
    counts = [math.floor(value) for value in exact]
    by_remainder = sorted(range(len(exact)), key=lambda i: (counts[i] - exact[i], i))
    for index in by_remainder[: total - sum(counts)]:
        counts[index] += 1
    return counts
