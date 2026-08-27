# Football Value Betting Bot v1

Automated football value-betting engine with a hard bankroll/risk layer.

## Current rules
- Starting bankroll: EUR 100
- Maximum daily exposure: EUR 5
- Football only
- Maximum 5 single bets/day
- Minimum model edge: 5%
- No parlays
- Fail closed when odds are stale or execution is unavailable

## Architecture

`odds feed -> normalized markets -> probability model -> fair odds -> EV filter -> staking -> execution adapter -> settlement -> bankroll ledger`

The execution layer is deliberately provider-agnostic. Do **not** put Epicbet passwords, cookies, BankID data, or session tokens in the repository. Live execution should only be enabled after an official/authorized API or integration is available.

## Run

```bash
pip install -r betting_bot/requirements.txt
python -m betting_bot.runner
```

By default the bot is `PAPER_MODE=true` and will not place real bets.

## Environment

See `betting_bot/.env.example`.

## Safety

The staking engine treats EUR 5 as a hard daily exposure ceiling. It will refuse a new bet when the remaining daily risk is insufficient, when bankroll is below the configured minimum, or when a market is stale.
