from datetime import datetime, timezone
import requests

from .config import Settings
from .models import BetRecord, Candidate


class ExecutionError(RuntimeError):
    pass


class Executor:
    """Provider-neutral execution boundary.

    Live execution requires an authorized provider endpoint. The bot never
    automates browser login, CAPTCHA, BankID, or credential handling.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def place(self, candidate: Candidate) -> BetRecord:
        now = datetime.now(timezone.utc)
        if self.settings.paper_mode:
            return BetRecord(
                candidate.market.event_id,
                candidate.market.selection,
                candidate.market.odds,
                candidate.stake_eur,
                "PAPER",
                now,
            )

        if not self.settings.execution_url:
            raise ExecutionError("Live execution disabled: no authorized execution API configured")

        payload = {
            "event_id": candidate.market.event_id,
            "market": candidate.market.market,
            "selection": candidate.market.selection,
            "odds": candidate.market.odds,
            "stake_eur": candidate.stake_eur,
        }
        response = requests.post(self.settings.execution_url, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("accepted") is not True:
            raise ExecutionError(f"Bet rejected: {data}")

        return BetRecord(
            candidate.market.event_id,
            candidate.market.selection,
            candidate.market.odds,
            candidate.stake_eur,
            "PLACED",
            now,
        )
