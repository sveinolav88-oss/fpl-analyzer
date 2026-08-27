"""Compatibility layer for the maintained FPL Decision Engine.

The Streamlit app imports ``decision_summary`` from this module. Keep the v3
engine as the source of truth, but normalise the player dataframe before
calling it so transfer affordability works with the v2 model dataframe.
"""

from decision_engine_v3 import *  # noqa: F401,F403
from decision_engine_v3 import decision_summary as _decision_summary


def _prepare_transfer_prices(df):
    """Ensure the decision engine has a usable selling price."""
    out = df.copy()
    if "selling_price" not in out.columns:
        out["selling_price"] = out["price"] if "price" in out.columns else 0.0
    elif "price" in out.columns:
        mask = out["selling_price"].isna() | (out["selling_price"] <= 0)
        out.loc[mask, "selling_price"] = out.loc[mask, "price"]
    return out


def _fallback_candidates(df, fixtures, squad_ids, bank, free_transfers, start_gw, horizon):
    """Find legal comparison transfers if the strict engine returns none.

    This is deliberately a *comparison* fallback, not a reason to invent a
    transfer. It uses the same multi-GW projection matrix, budget and three-
    player club rule as the main engine. If no legal candidate exists, the UI
    receives an explicit HOLD decision instead of an empty panel.
    """
    prepared = clean(df)
    ids = {int(x) for x in squad_ids}
    matrix = projection_matrix(prepared, fixtures, int(start_gw) + 1, horizon)
    gws = list(matrix.columns)[:int(horizon)]
    if not gws or not ids:
        return []

    weights = horizon_weights(len(gws))
    base = squad_projection(ids, prepared, matrix, gws)
    base_weighted = sum(base["by_gw"].get(int(gw), 0.0) * weights[i] for i, gw in enumerate(gws))
    bank = num(bank)
    current = prepared[prepared.id.isin(ids)]
    results = []

    for _, old in current.iterrows():
        pos = str(old.get("position", ""))
        sell = num(old.get("selling_price", old.get("price")))
        pool = prepared[(prepared.position.astype(str) == pos) & (~prepared.id.isin(ids))].copy()
        pool = pool.sort_values(["expected_gw_points", "fixture_next3", "minutes_probability"], ascending=False).head(40)
        for _, new in pool.iterrows():
            buy = num(new.get("price"))
            if buy > bank + sell + 1e-9:
                continue
            new_ids = ids - {int(old.id)} | {int(new.id)}
            if not club_ok(new_ids, prepared):
                continue
            new_proj = squad_projection(new_ids, prepared, matrix, gws)
            projected = sum(new_proj["by_gw"].get(int(gw), 0.0) * weights[i] for i, gw in enumerate(gws))
            gain = projected - base_weighted
            next_delta = num(matrix.loc[int(new.id), gws[0]]) - num(matrix.loc[int(old.id), gws[0]])
            results.append({
                "out_id": int(old.id),
                "out": str(old.get("name", "?")),
                "in_id": int(new.id),
                "in": str(new.get("name", "?")),
                "position": pos,
                "cost": round(buy - sell, 1),
                "projected_gain": round(gain, 3),
                "next_gw_delta": round(next_delta, 3),
                "fixture_delta": round(num(new.get("fixture_next3")) - num(old.get("fixture_next3")), 3),
                "fixture_run_edge": round(num(new.get("fixture_next3")) - num(old.get("fixture_next3")), 3),
                "minutes_delta": round(num(new.get("minutes_probability")) - num(old.get("minutes_probability")), 3),
                "out_4gw_points": round(sum(num(matrix.loc[int(old.id), gw]) * weights[i] for i, gw in enumerate(gws)), 2),
                "in_4gw_points": round(sum(num(matrix.loc[int(new.id), gw]) * weights[i] for i, gw in enumerate(gws)), 2),
                "hit": 0 if int(free_transfers) > 0 else 4,
                "new_total": round(projected, 3),
            })

    return sorted(results, key=lambda x: (x["projected_gain"], x["next_gw_delta"]), reverse=True)


def decision_summary(df, fixtures, squad_ids, budget, bank, free_transfers, start_gw, horizon=4):
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

    if not result.get("transfers"):
        fallback = _fallback_candidates(prepared, fixtures, squad_ids, bank, free_transfers, start_gw, horizon)
        if fallback:
            result["transfers"] = fallback
            result["fallback_mode"] = True
            result["decision"] = {
                "action": "HOLD" if fallback[0].get("projected_gain", 0) < 0.9 else "TRANSFER",
                "reason": "Fallback: viser beste lovlige sammenligning fordi hovedsøket ikke returnerte kandidater.",
            }
        else:
            result["transfers"] = []
            result["decision"] = result.get("decision") or {
                "action": "HOLD",
                "reason": "Ingen lovlig transfer med tilgjengelig budsjett og klubbregler akkurat nå.",
            }

    return result
