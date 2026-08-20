"""Captain-aware decision layer for the Streamlit app."""
from decision_engine import current_gameweek, load_manager as _load_manager, build_projection_matrix, transfer_candidates, best_two_transfer, chip_windows, wildcard_window


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


def _legal_xi_with_captain(squad_df, points_by_id):
    from decision_engine import legal_xi
    xi, xi_score = legal_xi(squad_df, points_by_id)
    if not xi:
        return [], 0.0, 0.0
    cap_points = max(float(points_by_id.get(int(p["id"]), 0.0)) for p in xi)
    return xi, xi_score, cap_points


def fpl_projection(squad_ids, df, matrix, gameweeks):
    squad = df[df.id.isin(set(int(x) for x in squad_ids))].copy()
    total = 0.0
    by_gw, xi_by_gw, captain_by_gw = {}, {}, {}
    for gw in gameweeks:
        if gw not in matrix.columns:
            continue
        points = matrix[gw].to_dict()
        xi, xi_score, cap_points = _legal_xi_with_captain(squad, points)
        by_gw[gw] = round(xi_score + cap_points, 3)
        xi_by_gw[gw] = xi
        captain_by_gw[gw] = max(xi, key=lambda p: float(points.get(int(p["id"]), 0.0)))["name"] if xi else None
        total += xi_score + cap_points
    return {"total": total, "by_gw": by_gw, "xi_by_gw": xi_by_gw, "captain_by_gw": captain_by_gw}


def decision_summary(df, fixtures, squad_ids, budget, bank, free_transfers, start_gw, horizon=4):
    horizon = int(horizon or 4)
    matrix = build_projection_matrix(df, fixtures, start_gw, horizon=horizon)
    gameweeks = list(matrix.columns)[:horizon]
    current_proj = fpl_projection(set(squad_ids), df, matrix, gameweeks)
    candidates = transfer_candidates(squad_ids, df, matrix, bank, free_transfers=free_transfers, horizon=horizon)
    baseline = current_proj["total"]
    for item in candidates:
        new_ids = set(int(x) for x in squad_ids) - {int(item["out_id"])} | {int(item["in_id"])}
        new_total = fpl_projection(new_ids, df, matrix, gameweeks)["total"]
        item["projected_gain"] = round(new_total - baseline, 2)
        item["net_gain"] = round(new_total - baseline - float(item.get("hit", 0)), 2)
        item["new_total"] = round(new_total, 2)
    candidates.sort(key=lambda x: (x["net_gain"], x["projected_gain"]), reverse=True)

    two = best_two_transfer(squad_ids, df, matrix, bank, free_transfers=free_transfers, horizon=horizon)
    if two:
        ids2 = set(int(x) for x in squad_ids) - {int(two["first"]["out_id"]), int(two["second"]["out_id"])} | {int(two["first"]["in_id"]), int(two["second"]["in_id"])}
        new_total = fpl_projection(ids2, df, matrix, gameweeks)["total"]
        two["projected_gain"] = round(new_total - baseline, 2)
        two["net_gain"] = round(new_total - baseline, 2)
        two["new_total"] = round(new_total, 2)

    chip = chip_windows(df, fixtures, squad_ids, budget, start_gw, matrix)
    wc = wildcard_window(df, squad_ids, budget, matrix, horizon=horizon)
    best = candidates[0] if candidates else None
    best_action = "HOLD"
    if best and best["net_gain"] > 0.5:
        best_action = "TRANSFER"
    if two and two["net_gain"] > (best["net_gain"] if best else 0.0) + 0.5:
        best_action = "TWO TRANSFERS"
    return {"matrix": matrix, "current": current_proj, "transfers": candidates, "two_transfers": two, "chips": chip, "wildcard": wc, "best_action": best_action}
