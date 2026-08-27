from dataclasses import dataclass
import os


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    bankroll_eur: float = _float("BANKROLL_EUR", 100.0)
    max_daily_exposure_eur: float = _float("MAX_DAILY_EXPOSURE_EUR", 5.0)
    max_bets_per_day: int = int(os.getenv("MAX_BETS_PER_DAY", "5"))
    min_edge: float = _float("MIN_EDGE", 0.05)
    min_odds: float = _float("MIN_ODDS", 1.50)
    max_odds: float = _float("MAX_ODDS", 10.0)
    max_odds_age_seconds: int = int(os.getenv("MAX_ODDS_AGE_SECONDS", "90"))
    paper_mode: bool = os.getenv("PAPER_MODE", "true").lower() == "true"
    execution_url: str = os.getenv("BET_EXECUTION_URL", "")


settings = Settings()
