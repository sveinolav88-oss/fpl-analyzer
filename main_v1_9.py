import math
import os
import time
from pathlib import Path

import pandas as pd
import requests

API = "https://fantasy.premierleague.com/api"
TIMEOUT = 30
MODEL_VERSION = "V1.9"


# ============================================================
# HELPERS / FPL API
# ============================================================

def get_json(path):
    r = requests.get(API + path, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def safe_float(x, default=0.0):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def position_name(element_type):
    return {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}.get(int(element_type), "UNK")


def load_fpl():
    data = get_json("/bootstrap-static/")
    teams = {t["id"]: t for t in data["teams"]}
    return data, teams, data["elements"]


def load_fixtures():
    return get_json("/fixtures/")


# ============================================================
# FIXTURE MODEL
# ============================================================

def fixture_rows_for_team(player_team, fixtures, horizon=5):
    rows = []
    for f in fixtures:
        if f.get("finished"):
            continue
        if f.get("team_h") == player_team:
            rows.append((f.get("event") or 99, True, f))
        elif f.get("team_a") == player_team:
            rows.append((f.get("event") or 99, False, f))
    rows.sort(key=lambda x: x[0])
    return rows[:horizon]


def fixture_factor(player_team, fixtures, horizon=5):
    rows = fixture_rows_for_team(player_team, fixtures, horizon)
    if not rows:
        return 0.50, 3.0

    diffs = []
    for _, home, f in rows:
        key = "team_h_difficulty" if home else "team_a_difficulty"
        diffs.append(safe_float(f.get(key), 3.0))

    avg = sum(diffs) / len(diffs)
    factor = clamp((5.0 - avg) / 4.0, 0.0, 1.0)
    return factor, avg


def fixture_quality(player_team, fixtures):
    ff1, diff1 = fixture_factor(player_team, fixtures, 1)
    ff3, diff3 = fixture_factor(player_team, fixtures, 3)
    ff5, diff5 = fixture_factor(player_team, fixtures, 5)
    return {
        "fixture_next1": ff1,
        "fixture_next3": ff3,
        "fixture_next5": ff5,
        "difficulty_next1": diff1,
        "difficulty_next3": diff3,
        "difficulty_next5": diff5,
    }


# ============================================================
# MINUTES MODEL
# ============================================================

def expected_minutes(p):
    chance_raw = p.get("chance_of_playing_next_round")
    if chance_raw is not None:
        chance = clamp(safe_float(chance_raw, 100.0), 0.0, 100.0) / 100.0
    else:
        chance = 1.0 if p.get("status", "a") == "a" else 0.0

    ppg = safe_float(p.get("points_per_game"), 0.0)
    starts = safe_float(p.get("starts"), 0.0)
    minutes = safe_float(p.get("minutes"), 0.0)
    appearances = safe_float(p.get("appearances"), 0.0)

    if minutes > 0 and appearances > 0:
        avg_min = clamp(minutes / appearances, 0.0, 90.0)
    else:
        # Early-season fallback. Do not assume every new player is 90.
        avg_min = 75.0

    if starts >= 15:
        base = max(avg_min, 80.0)
    elif starts >= 10:
        base = max(avg_min, 75.0)
    elif starts >= 5:
        base = max(avg_min, 65.0)
    else:
        base = min(avg_min, 60.0)

    if ppg >= 5.5:
        base += 3.0
    elif ppg <= 2.0:
        base -= 4.0

    status = p.get("status", "a")
    if status == "i":
        chance *= 0.20
    elif status == "s":
        chance *= 0.40
    elif status == "u":
        chance *= 0.30
    elif status == "d":
        chance *= 0.70

    if chance <= 0:
        return 0.0

    return round(clamp(base * chance, 0.0, 90.0), 1)


def minutes_probability(minutes):
    if minutes <= 0:
        return 0.0
    if minutes >= 80:
        return 0.92
    if minutes >= 70:
        return 0.85
    if minutes >= 60:
        return 0.76
    if minutes >= 45:
        return 0.62
    return 0.40


# ============================================================
# ATTACKING / PERFORMANCE SIGNALS
# ============================================================

def season_rate(value, minutes, fallback=0.0):
    value = safe_float(value, 0.0)
    minutes = safe_float(minutes, 0.0)
    if minutes <= 180:
        return fallback
    return max(0.0, value / minutes * 90.0)


def get_xg_rate(p):
    value = p.get("expected_goals")
    if value is None:
        value = p.get("xG")
    return season_rate(value, p.get("minutes"), 0.0)


def get_xa_rate(p):
    value = p.get("expected_assists")
    if value is None:
        value = p.get("xA")
    return season_rate(value, p.get("minutes"), 0.0)


def get_xgi_rate(p):
    value = p.get("expected_goal_involvements")
    if value is not None:
        return season_rate(value, p.get("minutes"), 0.0)
    return get_xg_rate(p) + get_xa_rate(p)


def get_goal_rate(p):
    return season_rate(p.get("goals_scored"), p.get("minutes"), 0.0)


def get_assist_rate(p):
    return season_rate(p.get("assists"), p.get("minutes"), 0.0)


def get_bonus_rate(p):
    return season_rate(p.get("bps"), p.get("minutes"), 0.0)


def position_base_points(pos):
    return {"GKP": 2.0, "DEF": 2.0, "MID": 2.0, "FWD": 2.0}.get(pos, 2.0)


# ============================================================
# EXPECTED POINTS MODEL V1.9
# ============================================================

def expected_points(p, minutes, fixtures):
    """
    One-GW projection designed to avoid double-counting FPL signals.

    The model combines:
      - FPL ep_next when credible
      - PPG/form baseline
      - xG/xA/xGI attacking signal
      - next-3 fixture quality for the independent model
      - a mild minutes reliability adjustment

    Important: ep_next already contains FPL's own modelling, so fixture
    quality is NOT applied a second time to the ep_next component.
    """
    pos = position_name(p.get("element_type", 0))
    ppg = safe_float(p.get("points_per_game"), 0.0)
    form = safe_float(p.get("form"), 0.0)
    ep_next = safe_float(p.get("ep_next"), 0.0)

    xg90 = get_xg_rate(p)
    xa90 = get_xa_rate(p)
    xgi90 = get_xgi_rate(p)

    # Independent baseline.
    history = 0.50 * ppg + 0.30 * form + 0.20 * position_base_points(pos)

    if pos in ("MID", "FWD"):
        attack = clamp(0.55 * xgi90 + 0.30 * xg90 + 0.15 * xa90, 0.0, 1.8)
        history += 0.55 * attack
    elif pos == "DEF":
        attack = clamp(0.55 * xgi90 + 0.25 * xg90 + 0.20 * xa90, 0.0, 1.2)
        history += 0.28 * attack

    form_delta = clamp(form - ppg, -2.5, 2.5)
    history += 0.10 * form_delta

    ff3, _ = fixture_factor(p.get("team"), fixtures, 3)
    model_projection = history * (0.93 + 0.14 * ff3)

    # FPL's ep_next is useful, but blending prevents one opaque number from
    # completely dominating the model.
    if 0.5 <= ep_next <= 12.0:
        base = 0.65 * ep_next + 0.35 * model_projection
    else:
        base = model_projection

    # ep_next normally already reflects availability. Minutes therefore get
    # only a mild adjustment rather than the old heavy double penalty.
    minute_factor = 0.84 + 0.16 * clamp(minutes / 90.0, 0.0, 1.0)
    base *= minute_factor

    # Explicitly unavailable players should still be suppressed.
    status = p.get("status", "a")
    if status in ("i", "u", "s"):
        base *= 0.55
    elif status == "d":
        base *= 0.80

    caps = {"GKP": 7.5, "DEF": 9.0, "MID": 11.0, "FWD": 11.0}
    return round(clamp(base, 1.0, caps.get(pos, 9.0)), 3)


# ============================================================
# PLAYER DATAFRAME
# ============================================================

def build_players(raw, teams, fixtures):
    out = []

    for p in raw:
        team = teams.get(p.get("team"), {})
        pos = position_name(p.get("element_type", 0))
        minutes = expected_minutes(p)
        fixture = fixture_quality(p.get("team"), fixtures)
        pts = expected_points(p, minutes, fixtures)

        price = safe_float(p.get("now_cost"), 0.0) / 10.0
        ownership = safe_float(p.get("selected_by_percent"), 0.0)
        ppg = safe_float(p.get("points_per_game"), 0.0)
        form = safe_float(p.get("form"), 0.0)

        xg90 = get_xg_rate(p)
        xa90 = get_xa_rate(p)
        xgi90 = get_xgi_rate(p)
        goal90 = get_goal_rate(p)
        assist90 = get_assist_rate(p)
        bonus90 = get_bonus_rate(p)

        value = pts / max(price, 4.0)
        minutes_component = clamp(minutes / 90.0, 0.0, 1.0)
        form_delta = clamp(form - ppg, -3.0, 3.0)

        # Keep raw components. Final 0-100 scores are built below using
        # cross-player percentiles, which makes the ranking much more stable.
        out.append({
            "id": p.get("id"),
            "name": p.get("web_name") or f'{p.get("first_name", "")} {p.get("second_name", "")}'.strip(),
            "team_name": team.get("name", "?"),
            "team_id": p.get("team"),
            "position": pos,
            "price": round(price, 1),
            "ownership": ownership,
            "expected_minutes": minutes,
            "minutes_probability": round(minutes_probability(minutes), 3),
            "expected_gw_points": pts,
            "ep_next_fpl": round(safe_float(p.get("ep_next"), 0.0), 3),
            "xg90": round(xg90, 3),
            "xa90": round(xa90, 3),
            "xgi90": round(xgi90, 3),
            "goals_per90": round(goal90, 3),
            "assists_per90": round(assist90, 3),
            "bonus_per90": round(bonus90, 3),
            "value": round(value, 4),
            "fixture_next1": round(fixture["fixture_next1"], 3),
            "fixture_next3": round(fixture["fixture_next3"], 3),
            "fixture_next5": round(fixture["fixture_next5"], 3),
            "next1_avg_difficulty": round(fixture["difficulty_next1"], 2),
            "next3_avg_difficulty": round(fixture["difficulty_next3"], 2),
            "next5_avg_difficulty": round(fixture["difficulty_next5"], 2),
            "form": form,
            "points_per_game": ppg,
            "form_delta": round(form_delta, 3),
        })

    df = pd.DataFrame(out)
    if df.empty:
        return df

    # ========================================================
    # NORMALISED MODEL SCORES
    # ========================================================
    def pct(series):
        # Percentile rank gives every component a comparable 0-100 scale.
        if len(series) <= 1:
            return pd.Series([50.0] * len(series), index=series.index)
        return series.rank(pct=True, method="average") * 100.0

    df["points_pct"] = pct(df["expected_gw_points"])
    df["value_pct"] = pct(df["value"])
    df["fixture_pct"] = pct(df["fixture_next3"])
    df["minutes_pct"] = pct(df["minutes_probability"])
    df["xgi_pct"] = pct(df["xgi90"])
    df["form_pct"] = pct(df["form"])

    # Differential bonus is intentionally capped. Low ownership should never
    # rescue a weak projection.
    df["differential_pct"] = ((15.0 - df["ownership"]) / 15.0).clip(0.0, 1.0) * 100.0

    # Transfer score: points first, then value/fixtures/minutes.
    df["transfer_score"] = (
        0.35 * df["points_pct"]
        + 0.22 * df["value_pct"]
        + 0.15 * df["fixture_pct"]
        + 0.12 * df["minutes_pct"]
        + 0.08 * df["form_pct"]
        + 0.05 * df["xgi_pct"]
        + 0.03 * df["differential_pct"]
    )

    # Captain score: ownership is deliberately excluded. The question is
    # simply who has the best expected output and upside this GW.
    df["captain_score"] = (
        0.62 * df["points_pct"]
        + 0.14 * df["minutes_pct"]
        + 0.10 * pct(df["fixture_next1"])
        + 0.09 * df["xgi_pct"]
        + 0.05 * df["form_pct"]
    )

    # Defenders/GKs should not win captain ranking merely from value.
    df.loc[df["position"].isin(["GKP", "DEF"]), "captain_score"] *= 0.94

    # Differential: upside + value + fixtures, with low ownership as a bonus.
    df["differential_score"] = (
        0.40 * df["points_pct"]
        + 0.20 * df["value_pct"]
        + 0.15 * df["xgi_pct"]
        + 0.10 * df["fixture_pct"]
        + 0.10 * df["minutes_pct"]
        + 0.05 * df["differential_pct"]
    )

    # Best value should answer "how much projection do I get for the money?"
    df["value_score"] = (
        0.55 * df["value_pct"]
        + 0.25 * df["points_pct"]
        + 0.10 * df["minutes_pct"]
        + 0.10 * df["fixture_pct"]
    )

    for col in ["transfer_score", "captain_score", "differential_score", "value_score"]:
        df[col] = df[col].round(2)

    return df


# ============================================================
# RECOMMENDATIONS
# ============================================================

def assign_recommendations(df):
    df = df.copy()
    recs = []

    for _, r in df.iterrows():
        if r.expected_minutes < 45 or r.expected_gw_points < 1.5:
            recs.append("AVOID")
        elif r.transfer_score >= 75 and r.expected_minutes >= 60:
            recs.append("BUY")
        elif r.transfer_score >= 55 and r.expected_minutes >= 60:
            recs.append("WATCH")
        else:
            recs.append("AVOID")

    df["recommendation"] = recs
    return df


# ============================================================
# STARTING XI
# ============================================================

def starting_xi(squad):
    gk = [x for x in squad if x["position"] == "GKP"]
    defs = [x for x in squad if x["position"] == "DEF"]
    mids = [x for x in squad if x["position"] == "MID"]
    fwds = [x for x in squad if x["position"] == "FWD"]

    if not gk:
        return [], 0.0

    def xi_weight(x):
        return x["expected_gw_points"] + 0.10 * x.get("minutes_probability", 0.7)

    formations = [(3,4,3),(3,5,2),(4,3,3),(4,4,2),(4,5,1),(5,2,3),(5,3,2),(5,4,1)]
    best = None

    for nd, nm, nf in formations:
        if len(defs) < nd or len(mids) < nm or len(fwds) < nf:
            continue
        xi = (
            sorted(gk, key=xi_weight, reverse=True)[:1]
            + sorted(defs, key=xi_weight, reverse=True)[:nd]
            + sorted(mids, key=xi_weight, reverse=True)[:nm]
            + sorted(fwds, key=xi_weight, reverse=True)[:nf]
        )
        pts = sum(x["expected_gw_points"] for x in xi)
        if best is None or pts > best[1]:
            best = (xi, pts)

    return best if best else ([], 0.0)


# ============================================================
# SQUAD OPTIMIZER
# ============================================================

def squad_objective(squad):
    xi, xi_pts = starting_xi(squad)
    if len(xi) != 11:
        return -1e9, xi, []

    xi_ids = {x["id"] for x in xi}
    bench = sorted(
        [x for x in squad if x["id"] not in xi_ids],
        key=lambda x: (x["expected_gw_points"], x.get("minutes_probability", 0)),
        reverse=True,
    )

    bench_cover = sum(x["expected_gw_points"] for x in bench) * 0.18
    minutes_cover = sum(clamp(x["expected_minutes"] / 90.0, 0.0, 1.0) for x in bench) * 0.05
    return xi_pts + bench_cover + minutes_cover, xi, bench


def select_squad(df, budget=100.0, locked_ids=None):
    locked_ids = set(locked_ids or [])
    positions = ["GKP", "DEF", "MID", "FWD"]
    needs = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}

    if df.empty:
        return None

    if locked_ids:
        existing = set(df["id"].tolist())
        if not locked_ids.issubset(existing) or len(locked_ids) > 15:
            return None
        locked_df = df[df["id"].isin(locked_ids)].copy()
        if locked_df.price.sum() > budget:
            return None
        for pos in positions:
            if len(locked_df[locked_df.position == pos]) > needs[pos]:
                return None
        if locked_df.groupby("team_id").size().max() > 3:
            return None
    else:
        locked_df = df.iloc[0:0].copy()

    # Candidate pools are broad enough to avoid the old "top N only" trap.
    pools = {}
    for pos in positions:
        g = df[df.position == pos].copy()
        candidates = pd.concat([
            g.nlargest(80, "expected_gw_points"),
            g.nlargest(70, "value_score"),
            g.nlargest(60, "transfer_score"),
            g.nlargest(50, "fixture_next3"),
        ]).drop_duplicates("id")
        pools[pos] = candidates.to_dict("records")

    def valid(chosen):
        if len(chosen) != 15:
            return False
        if sum(x["price"] for x in chosen) > budget + 1e-9:
            return False
        for pos in positions:
            if sum(x["position"] == pos for x in chosen) != needs[pos]:
                return False
        clubs = {}
        for x in chosen:
            clubs[x["team_id"]] = clubs.get(x["team_id"], 0) + 1
        return max(clubs.values(), default=0) <= 3

    def seed(mode):
        chosen = locked_df.to_dict("records")
        ids = {x["id"] for x in chosen}
        cost = sum(x["price"] for x in chosen)
        clubs = {}
        for x in chosen:
            clubs[x["team_id"]] = clubs.get(x["team_id"], 0) + 1

        for pos in positions:
            need = needs[pos] - sum(x["position"] == pos for x in chosen)
            if need <= 0:
                continue
            candidates = [x for x in pools[pos] if x["id"] not in ids]
            if mode == 0:
                key = lambda x: x["expected_gw_points"]
            elif mode == 1:
                key = lambda x: x["value_score"]
            elif mode == 2:
                key = lambda x: x["fixture_next3"]
            elif mode == 3:
                key = lambda x: x["transfer_score"]
            else:
                key = lambda x: x["expected_gw_points"] + 0.45 * x["value"] + 0.20 * x["fixture_next3"]
            candidates = sorted(candidates, key=key, reverse=True)

            for x in candidates:
                if need <= 0:
                    break
                if clubs.get(x["team_id"], 0) >= 3:
                    continue
                if cost + x["price"] > budget + 1e-9:
                    continue
                chosen.append(x)
                ids.add(x["id"])
                cost += x["price"]
                clubs[x["team_id"]] = clubs.get(x["team_id"], 0) + 1
                need -= 1

        # Repair remaining slots with the cheapest sensible candidates.
        while len(chosen) < 15:
            missing = next((pos for pos in positions if sum(x["position"] == pos for x in chosen) < needs[pos]), None)
            if missing is None:
                break
            candidates = sorted(pools[missing], key=lambda x: (x["price"], -x["expected_gw_points"]))
            added = False
            for x in candidates:
                if x["id"] in ids or clubs.get(x["team_id"], 0) >= 3:
                    continue
                if cost + x["price"] > budget + 1e-9:
                    continue
                chosen.append(x)
                ids.add(x["id"])
                cost += x["price"]
                clubs[x["team_id"]] = clubs.get(x["team_id"], 0) + 1
                added = True
                break
            if not added:
                return None

        return chosen if valid(chosen) else None

    def improve(chosen):
        cost = sum(x["price"] for x in chosen)
        locked = locked_ids
        best_obj = squad_objective(chosen)[0]
        loops = 0
        improved = True

        while improved and loops < 80:
            improved = False
            loops += 1
            ids = {x["id"] for x in chosen}
            for i, old in enumerate(list(chosen)):
                if old["id"] in locked:
                    continue
                pos = old["position"]
                candidates = sorted(
                    pools[pos],
                    key=lambda x: x["expected_gw_points"] + 0.30 * x["value"] + 0.18 * x["fixture_next3"],
                    reverse=True,
                )[:60]
                for new in candidates:
                    if new["id"] in ids:
                        continue
                    new_cost = cost - old["price"] + new["price"]
                    if new_cost > budget + 1e-9:
                        continue
                    trial = chosen.copy()
                    trial[i] = new
                    clubs = {}
                    for z in trial:
                        clubs[z["team_id"]] = clubs.get(z["team_id"], 0) + 1
                    if max(clubs.values(), default=0) > 3:
                        continue
                    obj = squad_objective(trial)[0]
                    if obj > best_obj + 1e-7:
                        chosen = trial
                        cost = new_cost
                        best_obj = obj
                        improved = True
                        break
                if improved:
                    break
        return chosen

    best = None
    for mode in range(5):
        seed_squad = seed(mode)
        if seed_squad is None:
            continue
        candidate = improve(seed_squad)
        obj, xi, bench = squad_objective(candidate)
        cost = sum(x["price"] for x in candidate)
        if cost <= budget + 1e-9 and (best is None or obj > best[0]):
            best = (obj, cost, candidate, xi, bench)

    return best


# ============================================================
# BUILD AROUND USER'S PLAYERS
# ============================================================

def build_around_players(df, selected_player_ids, budget=100.0):
    ids = list(dict.fromkeys(selected_player_ids or []))
    return select_squad(df, budget, locked_ids=ids)


# ============================================================
# OUTPUT / CLI COMPATIBILITY
# ============================================================

def save_outputs(df, squad_result, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    df.sort_values("transfer_score", ascending=False).to_csv(outdir / "players_v19.csv", index=False)
    for filename, col, filt in [
        ("top_transfers_v19.csv", "transfer_score", None),
        ("top_captains_v19.csv", "captain_score", None),
        ("top_differentials_v19.csv", "differential_score", df.ownership <= 10),
        ("top_value_v19.csv", "value_score", None),
    ]:
        x = df if filt is None else df[filt]
        x.sort_values(col, ascending=False).head(25).to_csv(outdir / filename, index=False)

    if squad_result:
        _, cost, squad, xi, bench = squad_result
        pd.DataFrame(squad).to_csv(outdir / "best_squad_v19.csv", index=False)
        pd.DataFrame(xi).to_csv(outdir / "starting_xi_v19.csv", index=False)
        pd.DataFrame(bench).to_csv(outdir / "bench_v19.csv", index=False)
        return cost, squad
    return None, []


def print_table(title, df, cols, n=20):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)
    print(df[cols].head(n).to_string(index=False))


def run_sanity_checks(df):
    if df.empty:
        print("SANITY CHECK: no players")
        return
    print("\nSANITY CHECK")
    print("  Players:", len(df))
    print("  Expected GW points:", round(df.expected_gw_points.min(), 2), "-", round(df.expected_gw_points.max(), 2))
    print("  Expected minutes:", round(df.expected_minutes.min(), 1), "-", round(df.expected_minutes.max(), 1))
    print("  Fixed-minute bug:", "PASS" if df.expected_minutes.nunique() > 5 else "FAIL")
    print("  Projection range:", "PASS" if df.expected_gw_points.max() <= 11.5 else "CHECK")
    print("  xG/xA fields:", "YES" if (df.xg90.sum() + df.xa90.sum()) > 0 else "NO / FALLBACK")


def main():
    started = time.time()
    print(f"FPL ANALYZER {MODEL_VERSION} – SMART FPL DECISION ENGINE")
    data, teams, raw_players = load_fpl()
    fixtures = load_fixtures()
    print("Live spillere:", len(raw_players))
    df = assign_recommendations(build_players(raw_players, teams, fixtures))
    run_sanity_checks(df)

    result = select_squad(df, 100.0)
    if result:
        score, cost, squad, xi, bench = result
        print(f"Best squad cost: £{cost:.1f}m | objective: {score:.2f}")
        print_table("V1.9 TOP TRANSFERS", df.sort_values("transfer_score", ascending=False), ["name","team_name","position","price","expected_minutes","expected_gw_points","xg90","xa90","fixture_next3","transfer_score","recommendation"], 20)
        print_table("V1.9 TOP CAPTAINS", df[df.expected_minutes >= 60].sort_values(["captain_score","expected_gw_points"], ascending=False), ["name","team_name","position","price","expected_minutes","expected_gw_points","xg90","xa90","fixture_next1","captain_score"], 10)
        print("Starting XI:")
        print(pd.DataFrame(xi)[["name","team_name","position","price","expected_gw_points"]].to_string(index=False))

    outdir = Path(__file__).resolve().parent / "data"
    save_outputs(df, result, outdir)
    print(f"{MODEL_VERSION} FERDIG – {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
