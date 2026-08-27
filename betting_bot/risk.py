from dataclasses import dataclass

from .models import Candidate
from .config import Settings


@dataclass
class DailyRisk:
    exposure_eur: float = 0.0
    bets: int = 0

    @property
    def remaining_eur(self) -> float:
        return 0.0


def allocate_stakes(candidates: list[Candidate], settings: Settings) -> list[Candidate]:
    if not candidates:
        return []

    ranked = sorted(candidates, key=lambda c: c.edge, reverse=True)[: settings.max_bets_per_day]
    remaining = min(settings.max_daily_exposure_eur, settings.bankroll_eur)
    if remaining <= 0:
        return []

    # Edge-weighted allocation with a hard daily ceiling.
    total_edge = sum(max(0.0, c.edge) for c in ranked)
    out = []
    for c in ranked:
        if c.edge <= 0 or remaining <= 0:
            continue
        share = c.edge / total_edge if total_edge else 0
        stake = min(remaining, settings.max_daily_exposure_eur * share)
        if stake < 0.01:
            continue
        out.append(Candidate(c.market, c.probability, c.fair_odds, c.edge, round(stake, 2)))
        remaining -= stake
    return out
