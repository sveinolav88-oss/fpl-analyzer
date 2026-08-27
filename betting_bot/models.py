from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Market:
    event_id: str
    home_team: str
    away_team: str
    market: str
    selection: str
    odds: float
    observed_at: datetime
    kickoff_at: datetime


@dataclass(frozen=True)
class Candidate:
    market: Market
    probability: float
    fair_odds: float
    edge: float
    stake_eur: float


@dataclass(frozen=True)
class BetRecord:
    event_id: str
    selection: str
    odds: float
    stake_eur: float
    status: str
    placed_at: datetime
