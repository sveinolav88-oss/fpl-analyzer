"""Compatibility layer for the maintained FPL Decision Engine.

The Streamlit app imports ``decision_summary`` from this module.  Keep the
v3 engine as the source of truth, but normalise the player dataframe before
calling it so transfer affordability works with the v2 model dataframe.
"""

from decision_engine_v3 import *  # noqa: F401,F403
from decision_engine_v3 import decision_summary as _decision_summary


def _prepare_transfer_prices(df):
    """Ensure the decision engine has a usable selling price.

    ``fpl_model_v2.build_players`` exposes the current player price but does
    not expose ``selling_price``.  The v3 engine deliberately defaults a
    missing selling price to 0, which made every transfer from a £0-bank team
    appear unaffordable and consequently produced an empty GW plan.

    For the planning screen we use current price as a conservative planning
    proxy when the actual selling price is unavailable.  This is replaced by
    the real selling price automatically when a caller supplies that column.
    """
    out = df.copy()
    if "selling_price" not in out.columns:
        if "price" in out.columns:
            out["selling_price"] = out["price"]
        else:
            out["selling_price"] = 0.0
    else:
        # Existing values are preserved; only missing/zero values fall back
        # to current price so the transfer engine cannot silently return []
        # just because the model dataframe lacks FPL selling prices.
        if "price" in out.columns:
            mask = out["selling_price"].isna() | (out["selling_price"] <= 0)
            out.loc[mask, "selling_price"] = out.loc[mask, "price"]
    return out


def decision_summary(df, fixtures, squad_ids, budget, bank, free_transfers, start_gw, horizon=4):
    """Return the normal v3 decision summary with a visible GW plan.

    The primary fix is the selling-price normalisation above.  A second
    fallback guarantees the UI can explain why it is holding rather than
    leaving the Gameweek Plan section empty when the strict transfer search
    finds no legal candidate.
    """
    prepared = _prepare_transfer_prices(df)
    result = _decision_summary(
        prepared,
        fixtures,
        squad_ids,
        budget,
        bank,
        free_transfers,
        start_gw,
        horizon=horizon,
    )

    # Make the result UI-safe even if a future engine change returns no
    # transfer candidates.  Do not invent a transfer: expose a HOLD reason.
    if not result.get("transfers"):
        result["transfers"] = []
        result["decision"] = result.get("decision") or {
            "action": "HOLD",
            "reason": "Ingen lovlig transfer med tydelig merverdi akkurat nå.",
        }

    return result
