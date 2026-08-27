import json
import os
from pathlib import Path

from .config import settings
from .executor import Executor
from .risk import allocate_stakes
from .strategy import build_candidates


DATA_FILE = Path(os.getenv("ODDS_JSON_FILE", "betting_bot/sample_odds.json"))


def load_rows() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def run() -> int:
    rows = load_rows()
    candidates = build_candidates(rows, settings)
    selected = allocate_stakes(candidates, settings)

    print(f"Candidates: {len(candidates)}")
    print(f"Selected: {len(selected)}")
    for c in selected:
        print(
            f"{c.market.home_team} - {c.market.away_team} | "
            f"{c.market.market} {c.market.selection} | "
            f"odds={c.market.odds:.2f} fair={c.fair_odds:.2f} "
            f"edge={c.edge:.1%} stake=EUR {c.stake_eur:.2f}"
        )

    executor = Executor(settings)
    for c in selected:
        record = executor.place(c)
        print(f"Execution status: {record.status}")

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
