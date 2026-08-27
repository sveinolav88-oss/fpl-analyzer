from datetime import datetime, timezone

from .config import Settings
from .model import edge, fair_odds, baseline_probability
from .models import Candidate, Market


FOOTBALL_MARKETS = {"1X2", "TOTALS", "BTTS", "ASIAN_HANDICAP"}


def build_candidates(rows: list[dict], settings: Settings) -> list[Candidate]:
    now = datetime.now(timezone.utc)
    candidates: list[Candidate] = []

    for row in rows:
        market = Market(
            event_id=str(row["event_id"]),
            home_team=str(row["home_team"]),
            away_team=str(row["away_team"]),
            market=str(row["market"]),
            selection=str(row["selection"]),
            odds=float(row["odds"]),
            observed_at=datetime.fromisoformat(str(row["observed_at"]).replace("Z", "+00:00")),
            kickoff_at=datetime.fromisoformat(str(row["kickoff_at"]).replace("Z", "+00:00")),
        )
        if market.market not in FOOTBALL_MARKETS:
            continue
        if market.odds < settings.min_odds or market.odds > settings.max_odds:
            continue
        if (now - market.observed_at).total_seconds() > settings.max_odds_age_seconds:
            continue

        probability = baseline_probability(market.market, market.selection, row)
        fair = fair_odds(probability)
        value = edge(probability, market.odds)
        if value >= settings.min_edge:
            candidates.append(Candidate(market, probability, fair, value, 0.0))

    return sorted(candidates, key=lambda c: c.edge, reverse=True)
