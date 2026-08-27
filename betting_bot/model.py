"""Conservative baseline model.

This is intentionally a replaceable baseline. Production performance should be
validated with historical data and calibrated before real-money execution.
"""

from math import isfinite


def fair_odds(probability: float) -> float:
    if not 0 < probability < 1 or not isfinite(probability):
        raise ValueError("probability must be between 0 and 1")
    return 1.0 / probability


def edge(probability: float, market_odds: float) -> float:
    if market_odds <= 1:
        raise ValueError("odds must be > 1")
    return probability * market_odds - 1.0


def baseline_probability(market: str, selection: str, features: dict) -> float:
    """Return a probability from supplied features.

    v1 accepts an externally calculated probability (`features['probability']`).
    Keeping this boundary explicit lets us replace it with a calibrated model
    without changing the risk or execution layers.
    """
    p = features.get("probability")
    if p is None:
        raise ValueError("No calibrated probability supplied")
    p = float(p)
    if not 0 < p < 1:
        raise ValueError("probability must be between 0 and 1")
    return p
