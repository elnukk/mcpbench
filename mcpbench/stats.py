from __future__ import annotations

import math


def wilson_interval(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial proportion.

    More reliable than a normal approximation at small `total` (the typical
    regime for --runs 5-20), and stays within [0, 1] unlike the Wald interval.
    """
    if total <= 0:
        return (0.0, 0.0)

    n = total
    phat = hits / n
    denom = 1 + z ** 2 / n
    center = (phat + z ** 2 / (2 * n)) / denom
    margin = (z * math.sqrt((phat * (1 - phat) / n) + (z ** 2 / (4 * n ** 2)))) / denom

    return (max(0.0, center - margin), min(1.0, center + margin))
