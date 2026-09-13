"""Pure extraction of Gaussian moment parameters for scoring consumers."""

import math
from typing import Any

GAUSSIAN_MEAN_KEYS = ("mean", "expected", "value", "point")
GAUSSIAN_SD_KEYS = ("sd", "std", "sigma", "stdev", "standard_deviation")


def gaussian_parameters(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    """Extract (mean, sd) from the moment keys or an ``equivalent_normal_*``
    summary — the inputs to the closed-form normal CRPS + the log score."""

    def _first(keys: tuple[str, ...], prefix: str = "") -> float | None:
        for key in keys:
            value = payload.get(prefix + key)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            ):
                return float(value)
        return None

    mean = _first(GAUSSIAN_MEAN_KEYS)
    if mean is None:
        mean = _first(("mean",), prefix="equivalent_normal_")
    sd = _first(GAUSSIAN_SD_KEYS)
    if sd is None:
        sd = _first(("sd",), prefix="equivalent_normal_")
    return mean, sd
