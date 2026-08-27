"""FPL decision engine v2.

The engine is deliberately conservative: it evaluates the user's real 15-man
squad, legal starting XIs, captaincy, fixture runs, minutes/availability,
transfer cost and the opportunity cost of saving a free transfer. It is
recomputed for the next actionable Gameweek from live FPL data.
"""

from collections import Counter
import time

import pandas as pd

from decision_engine import current_gameweek, _get, FPLAPIError


NUMERIC_COLUMNS = [
    "id", "team_id", "price", "selling_price", "expected_gw_points",
    "expected_minutes", "minutes_probability", "fixture_next1", "fixture_next3",
    "fixture_next5", "value", "value_score", "transfer_score", "captain_score",
    "ownership", "form", "points_per_game", "ep_next_fpl", "xg90", "xa90", "xgi90",
]

FORMATIONS = ((3, 4, 3), (3, 5, 2), (4, 3, 3), (4, 4, 2),
              (4, 5, 1), (5, 2, 3), (5, 3, 2), (5, 4, 1))

_MANAGER_CACHE = {}
_MANAGER_CACHE_TTL = 300


def _num(value, default=0.0):
    try:
        if value is None or value == "":
            return float(default)
        value = float(value)
        return value if value == value else float(default)
    except (TypeError, ValueError):
        return float(default)


def _clean_df(df):
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
    defaults = {
        "price": 0.0, "expected_gw_points": 0.0, "expected_minutes": 0.0,
        "minutes_probability": 0.7, "fixture_next1": 0.5,
        "fixture_next3": 0.5, "fixture_next5": 0.5, "value": 0.0,
        "value_score": 0.0, "transfer_score": 0.0, "captain_score": 0.0,
        "ownership": 0.0, "form": 0.0, "points_per_game": 0.0,
        "ep_next_fpl": 0.0, "xg90": 0.0, "xa90": 0.0, "xgi90": 0.0,
    }
    for col, default in defaults.items():
        if col in out.columns:
            out[col] = out[col].fillna(default).astype(float)
    return out


def _cache_get(key, path, ttl=_MANAGER_CACHE_TTL):
    now = time.time()
    hit = _MANAGER_CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = _get(path)
    _MANAGER_CACHE[key] = (now, value)
    return value


def _derive_free_transfers(history, target_gw):
    """Reconstruct the banked FT balance from official manager history.

    FPL allows up to five rolled free transfers. Wildcard/Free Hit preserve
    the banked transfers, so those weeks do not consume the FT balance here.
    """
    history = history or {}
    rows = sorted(history.get("current", []) or [], key=lambda x: int(x.get("event", 0) or 0))
    chips = {int(c.get("event", 0)): str(c.get("name", "")).lower() for c in (history.get("chips", []) or [])}
    available = 0
    for row in rows:
        gw = int(row.get("event", 0) or 0)
        if gw >= int(target_gw):
            break
        used = int(_num(row.get("event_transfers"), 0))
        chip = chips.get(gw, "")
        if chip in {"wildcard", "freehit"}:
            used = 0
        available = max(0, min(5, available + 1 - used))
    return int(available)


def load_manager(entry_id, event):
    """Load manager data without stale forever-caching and attach sync metadata."""
    entry_id = int(entry_id)
    event = int(event)
    entry = _cache_get(("entry", entry_id), f"/entry/{entry_id}/")
    try:
        picks = _cache_get(("picks", entry_id, event), f"/entry/{entry_id}/event/{event}/picks/")
    except FPLAPIError as exc:
        if "HTTP 404" in str(exc) and "/picks/" in str(exc):
            return entry, None
        raise

    try:
        history = _cache_get(("history", entry_id), f"/entry/{entry_id}/history/")
    except Exception:
        history = {}

    target_gw = min(38, event + 1)
    free_transfers = _derive_free_transfers(history, target_gw)
    picks = dict(picks or {})
    picks["_sync"] = {
        "free_transfers": free_transfers,
        "current_gw": event,
        "target_gw": target_gw,
        "updated_at": time.time(),
    }
    return entry, picks


def _numeric_points(points_by_id):
    result = {}
    for key, value in (points_by_id or {}).items():
        try:
            result[int(key)] = _num(value)
        except Exception:
            continue
    return result


def _fixture_map(fixtures):
    out = {}
    for fixture in fixtures or []:
        event = fixture.get("event")
        if event is None:
            continue
        try:
            event = int(event)
        except (TypeError, ValueError):
            continue
        for team_id, home in ((fixture.get("team_h"), True), (fixture.get("team_a"), False)):
            if team_id is None:
                continue
            out.setdefault((int(team_id), event), []).append((home, fixture))
    return out


def _fixture_quality(team_id, gw, fmap):
    rows = fmap.get((int(team_id), int(gw)), [])
    if not rows:
        return 0.0, 0
    values = []
    for home, fixture in rows:
        key = "team_h_difficulty" if home else "team_a_difficulty"
        values.append(_num(fixture.get(key), 3.0))
    avg = sum(values) / len(values)
    quality = max(0.0, min(1.0, (5.0 - avg) / 4.0))
    return quality, len(rows)


def build_projection_matrix(df, fixtures, start_gw, horizon=4):
    """Project each player for each future GW using the current FPL priors.

    A double gameweek is modelled as the sum of two fixture-level expectations,
    rather than multiplying a single-GW score by an arbitrary DGW factor.
    """
    df = _clean_df(df)
    fmap = _fixture_map(fixtures)
    start_gw = int(start_gw)
    horizon = max(1, min(4, int(horizon or 4)))
    gameweeks = list(range(start_gw, min(38, start_gw + horizon - 1) + 1))
    rows = []
    for _, player in df.iterrows():
        base = max(0.25, _num(player.get("expected_gw_points"), 0.0))
        minutes_prob = max(0.05, min(1.0, _num(player.get("minutes_probability"), 0.7)))
        current_q = max(0.15, min(1.0, _num(player.get("fixture_next1"), 0.5)))
        row = {"id": int(player.id), "name": str(player.get("name", "?"))}
        for gw in gameweeks:
            quality, count = _fixture_quality(player.team_id, gw, fmap)
            if count == 0:
                row[gw] = 0.0
                continue
            # FDR adjustment is modest; it changes the expectation without
            # overpowering FPL's own ep_next / form / minutes prior.
            fixture_mult = 0.90 + 0.20 * quality
            baseline_mult = 0.90 + 0.20 * current_q
            per_fixture = base * (fixture_mult / baseline_mult)
            per_fixture *= 0.72 + 0.28 * minutes_prob
            # Small rotation discount when a team has a double: the model
            # assumes a player may not get a full 90 in both matches.
            if count > 1:
                per_fixture *= 0.94
            row[gw] = round(max(0.0, per_fixture * count), 3)
        rows.append(row)
    return pd.DataFrame(rows).set_index("id") if rows else pd.DataFrame()


def _legal_xi(squad_df, points_by_id):
    squad_df = _clean_df(squad_df)
    if squad_df.empty:
        return [], 0.0, None
    points = _numeric_points(points_by_id)
    groups = {
        pos: squad_df[squad_df["position"].astype(str) == pos].copy()
        for pos in ("GKP", "DEF", "MID", "FWD")
    }
    best = None
    for defenders, midfielders, forwards in FORMATIONS:
        if len(groups["GKP"]) < 1 or len(groups["DEF"]) < defenders or len(groups["MID"]) < midfielders or len(groups["FWD"]) < forwards:
            continue
        chosen = []
        for pos, amount in (("GKP", 1), ("DEF", defenders), ("MID", midfielders), ("FWD", forwards)):
            group = groups[pos].copy()
            group["_score"] = pd.to_numeric(group["id"], errors="coerce").map(points).fillna(0.0).astype(float)
            chosen.append(group.sort_values("_score", ascending=False).head(amount))
        xi = pd.concat(chosen, ignore_index=True)
        xi_score = float(pd.to_numeric(xi["_score"], errors="coerce").fillna(0.0).sum())
        captain = max(xi.to_dict("records"), key=lambda p: points.get(int(p["id"]), 0.0)) if len(xi) else None
        captain_points = points.get(int(captain["id"]), 0.0) if captain else 0.0
        total = xi_score + captain_points
        if best is None or total > best[0]:
            best = (total, xi, captain)
    if best is None:
        return [], 0.0, None
    return best[1].to_dict("records"), float(best[0]), best[2]


def fpl_projection(squad_ids, df, matrix, gameweeks):
    df = _clean_df(df)
    ids = {int(x) for x in squad_ids}
    squad = df[df["id"].isin(ids)].copy()
    total = 0.0
    by_gw = {}
    xi_by_gw = {}
    captain_by_gw = {}
    for gw in gameweeks:
        if gw not in matrix.columns:
            continue
        xi, score, captain = _legal_xi(squad, matrix[gw].to_dict())
        by_gw[int(gw)] = round(float(score), 3)
        xi_by_gw[int(gw)] = xi
        captain_by_gw[int(gw)] = captain.get("name") if captain else None
        total += float(score)
    return {
        "total": round(total, 3),
        "by_gw": by_gw,
        "xi_by_gw": xi_by_gw,
        "captain_by_gw": captain_by_gw,
    }


def _club_limit_ok(ids, df):
    counts = Counter(int(x) for x in df[df["id"].isin(ids)]["team_id"].tolist())
    return max(counts.values(), default=0) <= 3


def _transfer_candidates_for_matrix(current_ids, df, matrix, bank, horizon=4, top_per_position=22):
    df = _clean_df(df)
    ids = {int(x) for x in current_ids}
    current = df[df["id"].isin(ids)].copy()
    gameweeks = list(matrix.columns)[:horizon]
    if current.empty or not gameweeks:
        return []
    base = fpl_projection(ids, df, matrix, gameweeks)
    base_total = float(base["total"])
    horizon_values = matrix[gameweeks].apply(pd.to_numeric, errors="coerce").sum(axis=1)
    pool = df.copy()
    pool["_horizon"] = pool["id"].map(horizon_values).fillna(0.0).astype(float)
    results = []
    for _, old in current.iterrows():
        position = str(old.get("position", ""))
        sell_price = _num(old.get("selling_price", old.get("price")))
        candidates = pool[(pool["position"] == position) & (~pool["id"].isin(ids))].copy()
        candidates = candidates.sort_values(["_horizon", "expected_gw_points", "minutes_probability"], ascending=False).head(top_per_position)
        for _, new in candidates.iterrows():
            buy_price = _num(new.get("price"))
            if buy_price > _num(bank) + sell_price + 1e-9:
                continue
            new_ids = ids - {int(old.id)} | {int(new.id)}
            if not _club_limit_ok(new_ids, df):
                continue
            projected = fpl_projection(new_ids, df, matrix, gameweeks)
            gain = float(projected["total"]) - base_total
            results.append({
                "out_id": int(old.id), "out": str(old.get("name", "?")),
                "in_id": int(new.id), "in": str(new.get("name", "?")),
                "position": position,
                "cost": round(buy_price - sell_price, 1),
                "projected_gain": round(gain, 3),
                "new_total": round(float(projected["total"]), 3),
                "out_next_gw": round(float(matrix.loc[int(old.id), gameweeks[0]]) if int(old.id) in matrix.index else 0.0, 3),
                "in_next_gw": round(float(matrix.loc[int(new.id), gameweeks[0]]) if int(new.id) in matrix.index else 0.0, 3),
                "fixture_delta": round(_num(new.get("fixture_next3")) - _num(old.get("fixture_next3")), 3),
                "minutes_delta": round(_num(new.get("minutes_probability")) - _num(old.get("minutes_probability")), 3),
            })
    results.sort(key=lambda x: (x["projected_gain"], x["in_next_gw"]), reverse=True)
    return results


def _best_one_transfer_gain(squad_ids, df, matrix, bank, horizon=1):
    candidates = _transfer_candidates_for_matrix(squad_ids, df, matrix, bank, horizon=horizon, top_per_position=12)
    return max([float(x.get("projected_gain", 0.0)) for x in candidates] or [0.0])


def _future_free_transfer_value(squad_ids, df, fixtures, bank, current_ft, target_gw):
    """Estimate the opportunity cost of spending today's free transfer.

    We do not assume a transfer is automatically valuable. Instead we look at
    the best available move in the following GW and discount it for uncertainty.
    This makes the engine patient when the squad already has good fixtures.
    """
    if int(current_ft) >= 5 or int(target_gw) >= 38:
        return 0.0
    next_gw = int(target_gw) + 1
    matrix = build_projection_matrix(df, fixtures, next_gw, horizon=1)
    if matrix.empty:
        return 0.0
    gain = _best_one_transfer_gain(squad_ids, df, matrix, bank, horizon=1)
    # Only part of the theoretical gain is an option value: injuries, lineups,
    # price changes and new information can make the eventual move irrelevant.
    return round(max(0.0, min(3.5, gain * 0.62)), 3)


def _bench_cover_value(squad_ids, df, matrix, target_gw):
    ids = {int(x) for x in squad_ids}
    if target_gw not in matrix.columns:
        return 0.0
    squad = df[df["id"].isin(ids)].copy()
    xi, _, _ = _legal_xi(squad, matrix[target_gw].to_dict())
    xi_ids = {int(p["id"]) for p in xi}
    bench = squad[~squad["id"].isin(xi_ids)]
    if bench.empty:
        return 0.0
    bench_scores = pd.to_numeric(bench["id"], errors="coerce").map(_numeric_points(matrix[target_gw].to_dict())).fillna(0.0)
    return round(float(bench_scores.max()) if len(bench_scores) else 0.0, 3)


def _best_two_transfer(current_ids, df, matrix, bank, free_transfers, horizon=4):
    if int(free_transfers) < 2:
        return None
    one = _transfer_candidates_for_matrix(current_ids, df, matrix, bank, horizon=horizon, top_per_position=12)[:18]
    if not one:
        return None
    ids = {int(x) for x in current_ids}
    best = None
    for first in one:
        ids1 = ids - {first["out_id"]} | {first["in_id"]}
        bank1 = _num(bank) - _num(first["cost"])
        if bank1 < 0 or not _club_limit_ok(ids1, df):
            continue
        second_candidates = _transfer_candidates_for_matrix(ids1, df, matrix, bank1, horizon=horizon, top_per_position=10)[:12]
        for second in second_candidates:
            if second["out_id"] == first["in_id"] or second["in_id"] == first["out_id"]:
                continue
            total_gain = float(first["projected_gain"]) + float(second["projected_gain"])
            item = {"first": first, "second": second, "net_gain": round(total_gain, 3)}
            if best is None or item["net_gain"] > best["net_gain"]:
                best = item
    return best


def decision_summary(df, fixtures, squad_ids, budget, bank, free_transfers, start_gw, horizon=4):
    """Return the next-GW decision using the user's actual 15-man squad.

    ``start_gw`` is the live/current GW. Recommendations are for the next
    actionable GW. The four-GW window is recalculated every time the FPL data
    changes, so after a GW finishes the model naturally moves forward one week.
    """
    df = _clean_df(df)
    ids = {int(x) for x in squad_ids}
    budget = float(budget)
    bank = float(bank)
    free_transfers = max(0, min(5, int(free_transfers)))
    current_gw = int(start_gw)
    target_gw = min(38, current_gw + 1)
    horizon = max(1, min(4, int(horizon or 4)))

    matrix = build_projection_matrix(df, fixtures, target_gw, horizon=horizon)
    if matrix.empty:
        return {
            "matrix": pd.DataFrame(), "current": {"total": 0.0, "by_gw": {}, "xi_by_gw": {}, "captain_by_gw": {}},
            "transfers": [], "two_transfers": None, "chips": pd.DataFrame(), "wildcard": None,
            "best_action": "HOLD", "target_gw": target_gw, "decision": {"action": "HOLD"},
        }

    gameweeks = list(matrix.columns)[:horizon]
    current_proj = fpl_projection(ids, df, matrix, gameweeks)
    transfers = _transfer_candidates_for_matrix(ids, df, matrix, bank, horizon=horizon, top_per_position=24)

    future_value = _future_free_transfer_value(ids, df, fixtures, bank, free_transfers, target_gw)
    bench_cover = _bench_cover_value(ids, df, matrix, target_gw)

    for item in transfers:
        hit = 0 if free_transfers > 0 else 4
        item["hit"] = hit
        item["future_ft_value"] = future_value
        item["bench_cover"] = bench_cover
        # A transfer is only a genuine improvement if it survives the cost of
        # the hit AND the option value of keeping the FT for new information.
        item["net_gain"] = round(float(item["projected_gain"]) - hit - future_value, 3)
        item["decision_score"] = round(item["net_gain"] + max(0.0, item["fixture_delta"]) * 0.25 + max(0.0, item["minutes_delta"]) * 0.35, 3)

    transfers.sort(key=lambda x: (x["decision_score"], x["net_gain"], x["projected_gain"]), reverse=True)
    best = transfers[0] if transfers else None

    # Minimum edge before the engine tells the manager to move. This is not an
    # arbitrary points target; it is a guard against noise and knee-jerks.
    threshold = 0.75 if free_transfers > 0 else 4.75
    action = "HOLD"
    if best and float(best["net_gain"]) >= threshold:
        action = "TRANSFER"

    two = _best_two_transfer(ids, df, matrix, bank, free_transfers, horizon=horizon)
    if two and action == "TRANSFER" and float(two["net_gain"]) > float(best["net_gain"]) + 0.75:
        action = "TWO TRANSFERS"

    if best:
        reasons = []
        if best["projected_gain"] > 0:
            reasons.append(f'{best["in"]} gir ca. +{best["projected_gain"]:.1f} forventede poeng mot å beholde laget over {horizon} GW')
        if best["fixture_delta"] > 0.08:
            reasons.append("bedre fixture-run")
        if best["minutes_delta"] > 0.08:
            reasons.append("bedre forventet spilletid")
        if future_value > 0.5:
            reasons.append(f'å spare FT har beregnet opsjonsverdi på ca. {future_value:.1f} poeng')
        if bench_cover > 0:
            reasons.append(f'benken dekker allerede rundt {bench_cover:.1f} poeng i neste GW')
        if best["net_gain"] < threshold:
            reasons.append("fordelen er ikke stor nok til å forsvare å bruke transferen nå")
        confidence = max(0.0, min(0.99, 0.55 + 0.12 * max(0.0, best["net_gain"])))
    else:
        reasons = ["Ingen realistisk transfer gir tydelig positiv nettoverdi innenfor budsjett og FPL-regler."]
        confidence = 0.60

    decision = {
        "action": action,
        "target_gw": target_gw,
        "out": best.get("out") if best else None,
        "in": best.get("in") if best else None,
        "projected_gain": float(best.get("projected_gain", 0.0)) if best else 0.0,
        "net_gain": float(best.get("net_gain", 0.0)) if best else 0.0,
        "future_ft_value": float(future_value),
        "bench_cover": float(bench_cover),
        "threshold": float(threshold),
        "confidence": round(confidence, 2),
        "reasons": reasons,
    }

    # Keep only moves that are actually actionable in the UI. The top move is
    # still retained when HOLD is returned so the manager can see what the
    # model considered and why it rejected the move.
    return {
        "matrix": matrix,
        "current": current_proj,
        "transfers": transfers,
        "two_transfers": two,
        "chips": pd.DataFrame(),
        "wildcard": None,
        "best_action": action,
        "target_gw": target_gw,
        "decision": decision,
    }
