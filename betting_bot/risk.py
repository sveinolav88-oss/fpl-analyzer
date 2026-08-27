from dataclasses import dataclass

from .models import Candidate
from .config import Settings


@dataclass
class DailyRisk:
    exposure_eur: float = 0.0
    bets: int = 0

    def remaining(self, settings: Settings) -> float:
        return max(0.0, min(settings.max_daily_exposure_eur, settings.bankroll_eur) - self.exposure_eur)


def allocate_stakes(candidates: list[Candidate], settings: Settings) -> list[Candidate]:
    if not candidates or settings.bankroll_eur <= 0:
        return []

    ranked = sorted(candidates, key=lambda c: c.edge, reverse=True)[: settings.max_bets_per_day]
    remaining = min(settings.max_daily_exposure_eur, settings.bankroll_eur)
    total_edge = sum(max(0.0, c.edge) for c in ranked)
    if total_edge <= 0:
        return []

    out = []
    for c in ranked:
        if c.edge <= 0 or remaining < 0.01:
            continue
        share = c.edge / total_edge
        stake = min(remaining, settings.max_daily_exposure_eur * share)
        stake = round(stake, 2)
        if stake < 0.01:
            continue
        out.append(Candidate(c.market, c.probability, c.fair_odds, c.edge, stake))
        remaining = round(remaining - stake, 2)
    return out
