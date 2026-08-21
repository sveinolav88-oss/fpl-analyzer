"""Captain-aware decision layer for the Streamlit app.

This module deliberately normalises FPL/pandas data before doing any arithmetic.
The live FPL API has returned numeric-looking values as strings in some payloads,
which can otherwise leak into projection/transfer calculations.
"""
import pandas as pd

from decision_engine import (
    current_gameweek,
    load_manager as _load_manager,
    build_projection_matrix,
    transfer_candidates,
    best_two_transfer,
    chip_windows,
    wildcard_window,
)


NUMERIC_COLUMNS = [
    "id", "team_id", "price", "selling_price", "expected_gw_points",
    "expected_minutes", "minutes_probability", "fixture_next3", "value",
    "value_score", "transfer_score", "captain_score", "ownership",
]


def _clean_df(df):
    """Return a copy with all fields used in arithmetic forced to numeric types."""
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    for col in NUMERIC_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "id" in out.columns:
        out = out[out["id"].notna()].copy()
        out["id"] = out["id"].astype(int)
    if "team_id" in out.columns:
        out["team_id"] = out["team_id"].fillna(-1).astype(int)
    for col, default in (("price", 0.0), ("expected_gw_points", 0.0),
                         ("expected_minutes", 0.0), ("minutes_probability", 0.7),
                         ("fixture_next3", 0.5), ("value", 0.0),
                         ("value_score", 0.0), ("transfer_score", 0.0),
                         ("captain_score", 0.0), ("ownership", 0.0)):
        if col in out.columns:
            out[col] = out[col].fillna(default).astype(float)
    return out


def load_manager(entry_id, event):
    try:
        return _load_manager(entry_id, event)
    except Exception as exc:
        message = str(exc)
        if "HTTP 404" in message and "/picks/" in message:
            from decision_engine import _get
            entry = _get(f"/entry/{int(entry_id)}/")
            return entry, None
        raise


def _numeric_points(points_by_id):
    """Return a clean int -> float map regardless of pandas/FPL typing."""
    clean = {}
    for key, value in (points_by_id or {}).items():
        try:
            kid = int(key)
            val = float(value)
            if val != val:
                val = 0.0
            clean[kid] = val
        except (TypeError, ValueError):
            continue
    return clean


def _legal_xi_with_captain(squad_df, points_by_id):
    """Build a legal XI using numeric scores only."""
    from decision_engine import FORMATIONS

    squad_df = _clean_df(squad_df)
    if squad_df.empty:
        return [], 0.0, 0.0

    points = _numeric_points(points_by_id)
    best = None

    for nd, nm, nf in FORMATIONS:
        groups = {}
        ok = True
        for pos, n in (("GKP", 1), ("DEF", nd), ("MID", nm), ("FWD", nf)):
            g = squad_df[squad_df["position"].astype(str) == pos].copy()
            if len(g) < n:
                ok = False
                break
            g["_score"] = pd.to_numeric(g["id"], errors="coerce").map(points).fillna(0.0).astype(float)
            groups[pos] = g.sort_values("_score", ascending=False).head(n)

        if not ok:
            continue

        xi = pd.concat([groups["GKP"], groups["DEF"], groups["MID"], groups["FWD"]], ignore_index=True)
        score = float(pd.to_numeric(xi["_score"], errors="coerce").fillna(0.0).sum())
        if best is None or score > best[0]:
            best = (score, xi)

    if best is None:
        return [], 0.0, 0.0

    xi = best[1].to_dict("records")
    cap_points = max((float(points.get(int(p["id"]), 0.0)) for p in xi), default=0.0)
    return xi, float(best[0]), cap_points


def fpl_projection(squad_ids, df, matrix, gameweeks):
    df = _clean_df(df)
    squad_ids = {int(x) for x in squad_ids}
    squad = df[df["id"].isin(squad_ids)].copy()
    total = 0.0
    by_gw, xi_by_gw, captain_by_gw = {}, {}, {}
    for gw in gameweeks:
        if gw not in matrix.columns:
            continue
        points = _numeric_points(matrix[gw].to_dict())
        xi, xi_score, cap_points = _legal_xi_with_captain(squad, points)
        by_gw[gw] = round(float(xi_score + cap_points), 3)
        xi_by_gw[gw] = xi
        captain_by_gw[gw] = max(xi, key=lambda p: float(points.get(int(p["id"]), 0.0)))["name"] if xi else None
        total += float(xi_score) + float(cap_points)
    return {"total": float(total), "by_gw": by_gw, "xi_by_gw": xi_by_gw, "captain_by_gw": captain_by_gw}


def decision_summary(df, fixtures, squad_ids, budget, bank, free_transfers, start_gw, horizon=4):
    """Run the complete decision engine on a fully numeric working dataframe."""
    df = _clean_df(df)
    budget = float(budget)
    bank = float(bank)
    free_transfers = int(free_transfers)
    start_gw = int(start_gw)
    horizon = max(1, min(4, int(horizon or 4)))
    squad_ids = {int(x) for x in squad_ids}

    matrix = build_projection_matrix(df, fixtures, start_gw, horizon=horizon)
    if matrix is None or matrix.empty:
        return {
            "matrix": pd.DataFrame(),
            "current": {"total": 0.0, "by_gw": {}, "xi_by_gw": {}, "captain_by_gw": {}},
            "transfers": [], "two_transfers": None, "chips": pd.DataFrame(),
            "wildcard": None, "best_action": "HOLD",
        }

    gameweeks = list(matrix.columns)[:horizon]
    current_proj = fpl_projection(squad_ids, df, matrix, gameweeks)

    # The lower-level transfer/chip routines are now fed only numeric columns.
    # Catching an individual optional scenario must never hide the main GW plan.
    try:
        transfers = transfer_candidates(squad_ids, df, matrix, bank, free_transfers=free_transfers, horizon=horizon)
    except Exception:
        transfers = []

    for item in transfers:
        try:
            item["projected_gain"] = float(item.get("projected_gain", 0.0))
            item["net_gain"] = float(item.get("net_gain", 0.0))
            item["new_total"] = float(item.get("new_total", 0.0))
        except (TypeError, ValueError):
            item["projected_gain"] = item["net_gain"] = item["new_total"] = 0.0
    transfers.sort(key=lambda x: (float(x.get("net_gain", 0.0)), float(x.get("projected_gain", 0.0))), reverse=True)

    try:
        two = best_two_transfer(squad_ids, df, matrix, bank, free_transfers=free_transfers, horizon=horizon)
    except Exception:
        two = None

    try:
        chip = chip_windows(df, fixtures, squad_ids, budget, start_gw, matrix)
    except Exception:
        chip = pd.DataFrame()

    try:
        wc = wildcard_window(df, squad_ids, budget, matrix, horizon=horizon)
    except Exception:
        wc = None

    best = transfers[0] if transfers else None
    best_action = "HOLD"
    if best and float(best.get("net_gain", 0.0)) > 0.5:
        best_action = "TRANSFER"
    if two and float(two.get("net_gain", 0.0)) > (float(best.get("net_gain", 0.0)) if best else 0.0) + 0.5:
        best_action = "TWO TRANSFERS"

    return {
        "matrix": matrix,
        "current": current_proj,
        "transfers": transfers,
        "two_transfers": two,
        "chips": chip,
        "wildcard": wc,
        "best_action": best_action,
    }
