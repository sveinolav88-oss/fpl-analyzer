import math
import time
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache

import pandas as pd
import requests

from main import select_squad

API = "https://fantasy.premierleague.com/api"
TIMEOUT = 30

# Legal FPL starting formations. The previous version referenced FORMATIONS
# without defining it, which caused the GW1 Decision Engine to crash as soon
# as a synced squad was available.
FORMATIONS = (
    (3, 4, 3),
    (3, 5, 2),
    (4, 3, 3),
    (4, 4, 2),
    (4, 5, 1),
    (5, 2, 3),
    (5, 3, 2),
    (5, 4, 1),
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://fantasy.premierleague.com/",
    "Origin": "https://fantasy.premierleague.com",
})


class FPLAPIError(RuntimeError):
    def __init__(self, path, status, message=""):
        self.path = path
        self.status = status
        self.message = message
        detail = f": {message}" if message else ""
        super().__init__(f"FPL API svarte HTTP {status} på {path}{detail}")


def _get(path):
    last_error = None
    for attempt in range(4):
        try:
            r = SESSION.get(API + path, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                last_error = FPLAPIError(path, r.status_code)
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
            text = (r.text or "").strip().replace("\n", " ")[:180]
            raise FPLAPIError(path, r.status_code, text)
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("Ukjent feil ved FPL API-kall")


def _normalise_entry_id(entry_id):
    value = str(entry_id or "").strip()
    if "/entry/" in value:
        value = value.split("/entry/", 1)[1].split("/", 1)[0]
    value = value.strip()
    if not value.isdigit() or int(value) <= 0:
        raise ValueError("FPL Team ID må være et positivt tall, eller en FPL-team-URL.")
    return int(value)


@lru_cache(maxsize=64)
def load_manager(entry_id, event):
    entry_id = _normalise_entry_id(entry_id)
    event = int(event)
    entry = _get(f"/entry/{entry_id}/")
    picks = _get(f"/entry/{entry_id}/event/{event}/picks/")
    return entry, picks


def current_gameweek(data):
    events = data.get("events", [])
    for e in events:
        if e.get("is_current"):
            return int(e["id"])
    for e in events:
        if e.get("is_next"):
            return int(e["id"])
    for e in events:
        if not e.get("finished"):
            return int(e["id"])
    return 38


def fixture_map(fixtures):
    out = {}
    for f in fixtures:
        event = f.get("event")
        if not event:
            continue
        for team_id, home in ((f.get("team_h"), True), (f.get("team_a"), False)):
            if team_id is None:
                continue
            out.setdefault((int(team_id), int(event)), []).append((home, f))
    return out


def fixture_quality_for_gw(team_id, event, fmap):
    rows = fmap.get((int(team_id), int(event)), [])
    if not rows:
        return 0.0, 0
    diffs = []
    for home, f in rows:
        key = "team_h_difficulty" if home else "team_a_difficulty"
        try:
            diffs.append(float(f.get(key, 3)))
        except Exception:
            diffs.append(3.0)
    avg = sum(diffs) / len(diffs)
    quality = max(0.0, min(1.0, (5.0 - avg) / 4.0))
    return quality, len(rows)


def build_projection_matrix(df, fixtures, start_gw, horizon=4):
    fmap = fixture_map(fixtures)
    events = list(range(int(start_gw), min(38, int(start_gw) + horizon - 1) + 1))
    rows = []
    for _, p in df.iterrows():
        base = float(p.get("expected_gw_points", 0.0))
        current_quality = max(0.15, min(1.0, float(p.get("fixture_next3", 0.5))))
        vals = {"id": int(p["id"]), "name": p["name"]}
        for gw in events:
            quality, count = fixture_quality_for_gw(p["team_id"], gw, fmap)
            if count == 0:
                value = 0.0
            else:
                fixture_multiplier = (0.86 + 0.28 * quality) / (0.86 + 0.28 * current_quality)
                minutes_factor = 0.92 + 0.08 * float(p.get("minutes_probability", 0.7))
                value = base * fixture_multiplier * minutes_factor
                if count > 1:
                    value *= 1.0 + 0.82 * (count - 1)
            vals[gw] = round(max(0.0, value), 3)
        rows.append(vals)
    return pd.DataFrame(rows).set_index("id") if rows else pd.DataFrame()


def legal_xi(squad_df, points_by_id):
    if squad_df.empty:
        return [], 0.0
    best = None
    for nd, nm, nf in FORMATIONS:
        groups = {}
        ok = True
        for pos, n in (("GKP",1),("DEF",nd),("MID",nm),("FWD",nf)):
            g = squad_df[squad_df.position == pos].copy()
            g["_score"] = g["id"].map(points_by_id).fillna(0.0)
            if len(g) < n:
                ok = False
                break
            groups[pos] = g.nlargest(n, "_score")
        if not ok:
            continue
        xi = pd.concat([groups["GKP"], groups["DEF"], groups["MID"], groups["FWD"]], ignore_index=True)
        score = float(xi["_score"].sum())
        if best is None or score > best[0]:
            best = (score, xi)
    if best is None:
        return [], 0.0
    return best[1].to_dict("records"), best[0]


def squad_projection(squad_ids, df, matrix, gameweeks):
    squad = df[df.id.isin(squad_ids)].copy()
    total = 0.0
    by_gw = {}
    xi_by_gw = {}
    for gw in gameweeks:
        if gw not in matrix.columns:
            continue
        points = matrix[gw].to_dict()
        xi, score = legal_xi(squad, points)
        by_gw[gw] = score
        xi_by_gw[gw] = xi
        total += score
    return {"total": total, "by_gw": by_gw, "xi_by_gw": xi_by_gw}


def transfer_candidates(current_ids, df, matrix, bank, free_transfers=1, horizon=4):
    current = df[df.id.isin(current_ids)].copy()
    current_ids = set(int(x) for x in current_ids)
    gameweeks = list(matrix.columns)[:horizon]
    baseline = squad_projection(current_ids, df, matrix, gameweeks)["total"]
    candidates = []
    top_pool = df.copy()
    top_pool["horizon"] = top_pool.id.map(matrix[gameweeks].sum(axis=1).to_dict()).fillna(0.0)
    top_pool = top_pool.sort_values(["horizon", "expected_gw_points"], ascending=False)
    for _, out in current.iterrows():
        sell_price = float(out.get("selling_price", out.get("price", 0.0)))
        pool = top_pool[(top_pool.position == out.position) & (~top_pool.id.isin(current_ids))].head(24)
        for _, inc in pool.iterrows():
            if float(inc.price) > bank + sell_price + 1e-9:
                continue
            new_ids = current_ids - {int(out.id)}
            new_ids.add(int(inc.id))
            counts = Counter(df[df.id.isin(new_ids)].team_id.tolist())
            if max(counts.values(), default=0) > 3:
                continue
            proj = squad_projection(new_ids, df, matrix, gameweeks)["total"]
            hit = 0 if free_transfers >= 1 else 4
            gain = proj - baseline - hit
            candidates.append({
                "out_id": int(out.id), "out": out.name, "in_id": int(inc.id), "in": inc.name,
                "position": out.position, "cost": float(inc.price) - sell_price,
                "projected_gain": round(proj - baseline, 2), "hit": hit, "net_gain": round(gain, 2),
                "new_total": round(proj, 2),
            })
    return sorted(candidates, key=lambda x: (x["net_gain"], x["projected_gain"]), reverse=True)


def best_two_transfer(current_ids, df, matrix, bank, free_transfers=1, horizon=4):
    if free_transfers < 2:
        return None
    one = transfer_candidates(current_ids, df, matrix, bank, free_transfers=2, horizon=horizon)[:30]
    best = None
    gameweeks = list(matrix.columns)[:horizon]
    base = squad_projection(set(current_ids), df, matrix, gameweeks)["total"]
    for a in one:
        ids1 = set(current_ids) - {a["out_id"]} | {a["in_id"]}
        sell = float(df.loc[df.id == a["out_id"], "price"].iloc[0])
        buy = float(df.loc[df.id == a["in_id"], "price"].iloc[0])
        bank2 = bank + sell - buy
        if bank2 < -1e-9:
            continue
        second = transfer_candidates(ids1, df, matrix, bank2, free_transfers=1, horizon=horizon)[:18]
        for b in second:
            if b["out_id"] == a["in_id"] or b["in_id"] == a["out_id"]:
                continue
            ids2 = ids1 - {b["out_id"]} | {b["in_id"]}
            proj = squad_projection(ids2, df, matrix, gameweeks)["total"]
            item = {"first": a, "second": b, "projected_gain": round(proj-base,2), "net_gain": round(proj-base,2), "new_total": round(proj,2)}
            if best is None or item["net_gain"] > best["net_gain"]:
                best = item
    return best


def chip_windows(df, fixtures, squad_ids, budget, start_gw, matrix):
    gameweeks = list(matrix.columns)
    fmap = fixture_map(fixtures)
    rows = []
    squad_ids = set(int(x) for x in squad_ids)
    squad = df[df.id.isin(squad_ids)].copy()
    for gw in gameweeks:
        points = matrix[gw].to_dict()
        xi, xi_score = legal_xi(squad, points)
        xi_ids = {int(p["id"]) for p in xi}
        bench = squad[~squad.id.isin(xi_ids)].copy()
        bench["_p"] = bench.id.map(points).fillna(0.0)
        bb = float(bench["_p"].sum())
        cap = max(points.get(int(pid),0.0) for pid in squad_ids) if squad_ids else 0.0
        temp = df.copy()
        temp["expected_gw_points"] = temp.id.map(points).fillna(0.0)
        fh = select_squad(temp, budget)
        fh_value = float(sum(points.get(int(p["id"]),0.0) for p in fh[3])) if fh else 0.0
        fh_gain = fh_value - xi_score
        fixture_counts = [len(fmap.get((int(tid), int(gw)), [])) for tid in df.team_id.unique()]
        double_count = sum(1 for n in fixture_counts if n >= 2)
        active_teams = sum(1 for n in fixture_counts if n >= 1)
        rows.append({"gw":gw,"tc_value":round(cap,2),"bb_value":round(bb,2),"fh_value":round(fh_gain,2),"double_teams":double_count,"active_teams":active_teams,"blank":active_teams<20,"double":double_count>0})
    return pd.DataFrame(rows)


def wildcard_window(df, squad_ids, budget, matrix, horizon=4):
    gameweeks = list(matrix.columns)[:horizon]
    if not gameweeks:
        return None
    current = squad_projection(set(squad_ids), df, matrix, gameweeks)["total"]
    wc_scores = matrix[gameweeks].sum(axis=1)
    temp = df.copy()
    temp["expected_gw_points"] = temp.id.map(wc_scores.to_dict()).fillna(0.0)
    result = select_squad(temp, budget)
    if not result:
        return None
    _, cost, squad, _, _ = result
    optimal_ids = {int(p["id"]) for p in squad}
    optimal = squad_projection(optimal_ids, df, matrix, gameweeks)["total"]
    return {"gain":round(optimal-current,2),"current":round(current,2),"optimal":round(optimal,2),"cost":round(cost,1),"ids":optimal_ids}


def decision_summary(df, fixtures, squad_ids, budget, bank, free_transfers, start_gw, horizon=4):
    horizon = int(horizon or 4)
    matrix = build_projection_matrix(df, fixtures, start_gw, horizon=horizon)
    gameweeks = list(matrix.columns)[:horizon]
    current_proj = squad_projection(set(squad_ids), df, matrix, gameweeks)
    transfers = transfer_candidates(squad_ids, df, matrix, bank, free_transfers=free_transfers, horizon=horizon)
    two = best_two_transfer(squad_ids, df, matrix, bank, free_transfers=free_transfers, horizon=horizon)
    chip = chip_windows(df, fixtures, squad_ids, budget, start_gw, matrix)
    wc = wildcard_window(df, squad_ids, budget, matrix, horizon=horizon)
    best = transfers[0] if transfers else None
    best_action = "HOLD"
    if best and best["net_gain"] > 0.5:
        best_action = "TRANSFER"
    if two and two["net_gain"] > (best["net_gain"] if best else 0.0) + 0.5:
        best_action = "TWO TRANSFERS"
    return {"matrix":matrix,"current":current_proj,"transfers":transfers,"two_transfers":two,"chips":chip,"wildcard":wc,"best_action":best_action}
