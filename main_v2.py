import json
import math
import os
import time
from pathlib import Path

import pandas as pd
import requests

API = "https://fantasy.premierleague.com/api"
TIMEOUT = 30


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
    print("  Henter FPL live-data...")
    data = get_json("/bootstrap-static/")
    teams = {t["id"]: t for t in data["teams"]}
    players = data["elements"]
    return data, teams, players


def load_fixtures():
    print("  Henter fixtures...")
    return get_json("/fixtures/")


def fixture_factor(player_team, fixtures, horizon=5):
    rows = []
    for f in fixtures:
        if f.get("finished"):
            continue
        if f.get("team_h") == player_team:
            rows.append((f.get("event") or 99, True, f))
        elif f.get("team_a") == player_team:
            rows.append((f.get("event") or 99, False, f))
    rows.sort(key=lambda x: x[0])
    rows = rows[:horizon]
    if not rows:
        return 0.50, 3.0
    diffs = []
    for _, home, f in rows:
        d = safe_float(f.get("team_h_difficulty" if home else "team_a_difficulty"), 3.0)
        diffs.append(d)
    avg = sum(diffs) / len(diffs)
    # FPL difficulty is 1..5. Lower is easier.
    factor = clamp((5.0 - avg) / 4.0, 0.0, 1.0)
    return factor, avg


def expected_minutes(p):
    # Conservative preseason/early-season estimate.
    # FPL's chance-of-playing fields are explicit signals when available.
    chance = p.get("chance_of_playing_next_round")
    if chance is not None:
        chance = clamp(safe_float(chance, 100), 0, 100) / 100.0
    else:
        chance = 1.0 if p.get("status", "a") == "a" else 0.0

    # Avoid the old fixed 67.5-minute output.
    ppg = safe_float(p.get("points_per_game"), 0)
    starts = safe_float(p.get("starts"), 0)
    minutes = safe_float(p.get("minutes"), 0)

    if minutes > 0:
        avg_min = clamp(minutes / max(1.0, safe_float(p.get("appearances"), 1)), 0, 90)
    else:
        avg_min = 75.0

    # Strong starters get more minutes; fringe players remain conservative.
    if starts >= 10:
        base = max(avg_min, 75.0)
    elif starts >= 5:
        base = max(avg_min, 65.0)
    else:
        base = min(avg_min, 60.0)

    # At preseason, points_per_game can be misleading, so cap its influence.
    if ppg >= 5.5:
        base += 5
    elif ppg <= 2.0:
        base -= 5

    return round(clamp(base * chance, 20.0 if chance > 0 else 0.0, 90.0), 1)


def _underlying_rate_score(p):
    """Convert underlying production into a conservative 0-1 score.

    FPL's bootstrap fields are season-to-date, so rates are only used as a
    supporting signal rather than a standalone projection.
    """
    pos = position_name(p.get("element_type", 0))
    minutes = max(1.0, safe_float(p.get("minutes"), 0))
    xgi = safe_float(p.get("expected_goal_involvements"), 0)
    xg = safe_float(p.get("expected_goals"), 0)
    xa = safe_float(p.get("expected_assists"), 0)
    goals = safe_float(p.get("goals_scored"), 0)
    assists = safe_float(p.get("assists"), 0)
    shots = safe_float(p.get("shots"), 0)
    threat = safe_float(p.get("threat"), 0)
    creativity = safe_float(p.get("creativity"), 0)
    ict = safe_float(p.get("ict_index"), 0)

    # Per-90 rates are more useful than raw season totals.
    xgi90 = 90.0 * xgi / minutes
    xg90 = 90.0 * xg / minutes
    xa90 = 90.0 * xa / minutes
    ga90 = 90.0 * (goals + assists) / minutes
    shots90 = 90.0 * shots / minutes

    if pos in ("MID", "FWD"):
        raw = (
            0.36 * clamp(xgi90 / 0.55, 0, 1)
            + 0.18 * clamp(xg90 / 0.35, 0, 1)
            + 0.14 * clamp(xa90 / 0.25, 0, 1)
            + 0.12 * clamp(ga90 / 0.55, 0, 1)
            + 0.08 * clamp(shots90 / 4.0, 0, 1)
            + 0.06 * clamp(threat / 1000.0, 0, 1)
            + 0.06 * clamp(creativity / 700.0, 0, 1)
        )
    elif pos == "DEF":
        clean = safe_float(p.get("clean_sheets"), 0)
        cs_rate = clamp(clean / max(1.0, safe_float(p.get("starts"), 1)), 0, 1)
        raw = (
            0.38 * cs_rate
            + 0.22 * clamp(xgi90 / 0.22, 0, 1)
            + 0.12 * clamp(xa90 / 0.14, 0, 1)
            + 0.10 * clamp(ga90 / 0.22, 0, 1)
            + 0.08 * clamp(threat / 500.0, 0, 1)
            + 0.10 * clamp(ict / 200.0, 0, 1)
        )
    else:  # GKP
        clean = safe_float(p.get("clean_sheets"), 0)
        starts = max(1.0, safe_float(p.get("starts"), 0))
        cs_rate = clamp(clean / starts, 0, 1)
        saves90 = 90.0 * safe_float(p.get("saves"), 0) / minutes
        raw = (
            0.48 * cs_rate
            + 0.30 * clamp(saves90 / 5.0, 0, 1)
            + 0.12 * clamp(safe_float(p.get("bonus"), 0) / 10.0, 0, 1)
            + 0.10 * clamp(ict / 150.0, 0, 1)
        )

    return clamp(raw, 0.0, 1.0)


def _role_score(p):
    """Estimate how secure the player's role is, independently of minutes."""
    starts = safe_float(p.get("starts"), 0)
    appearances = safe_float(p.get("appearances"), 0)
    minutes = safe_float(p.get("minutes"), 0)

    if appearances > 0:
        start_rate = starts / appearances
    else:
        start_rate = 0.0

    avg_minutes = minutes / max(1.0, appearances)
    return clamp(0.55 * start_rate + 0.45 * (avg_minutes / 90.0), 0.0, 1.0)


def expected_points(p, minutes, fixture3, fixture5, underlying):
    """V2 expected GW points.

    The FPL ep_next value remains useful, but is now only one component.
    The model blends:
      - FPL projection
      - points-per-game
      - form
      - underlying production
      - role security
      - expected minutes
      - fixture difficulty
    """
    pos = position_name(p.get("element_type", 0))
    ppg = safe_float(p.get("points_per_game"), 0)
    form = safe_float(p.get("form"), 0)
    ep_next = safe_float(p.get("ep_next"), 0)

    # Robust baseline: do not let a missing/noisy ep_next dominate.
    ep_component = ep_next if ep_next > 0 else ppg
    baseline = (
        0.38 * clamp(ep_component, 0.5, 8.5)
        + 0.24 * clamp(ppg, 0.5, 8.0)
        + 0.13 * clamp(form, 0.0, 8.0)
    )

    # Underlying signal adds a controlled amount rather than replacing FPL data.
    underlying_bonus = {
        "GKP": 0.55,
        "DEF": 0.65,
        "MID": 1.05,
        "FWD": 1.15,
    }.get(pos, 0.75) * underlying

    role = _role_score(p)
    role_bonus = 0.35 * role

    # 5-match fixture context is slightly smoother than a single fixture.
    fixture_factor = 0.65 * fixture3 + 0.35 * fixture5
    fixture_multiplier = 0.84 + 0.32 * fixture_factor

    minute_factor = clamp(minutes / 90.0, 0.0, 1.0)

    raw = (baseline + underlying_bonus + role_bonus) * minute_factor * fixture_multiplier

    floors = {"GKP": 1.3, "DEF": 1.2, "MID": 1.0, "FWD": 1.0}
    caps = {"GKP": 7.0, "DEF": 7.5, "MID": 10.0, "FWD": 10.5}
    return round(clamp(raw, floors.get(pos, 1.0), caps.get(pos, 8.0)), 3)

def attacking_proxy(p):
    pos = position_name(p.get("element_type", 0))
    if pos == "GKP":
        return 0.05
    xgi = safe_float(p.get("expected_goal_involvements"), 0)
    # xGI is season-to-date; normalize very conservatively.
    return clamp(xgi / 10.0, 0.0, 1.0)


def build_players(raw, teams, fixtures):
    out = []

    # First pass: calculate underlying signals and minutes.
    staged = []
    for p in raw:
        team = teams.get(p.get("team"), {})
        minutes = expected_minutes(p)
        ff5, diff5 = fixture_factor(p.get("team"), fixtures, 5)
        ff3, _ = fixture_factor(p.get("team"), fixtures, 3)
        underlying = _underlying_rate_score(p)

        staged.append((p, team, minutes, ff3, ff5, diff5, underlying))

    # Peer-relative underlying score helps prevent one extreme raw statistic
    # from dominating the whole model.
    underlying_values = [x[-1] for x in staged]
    median_underlying = sorted(underlying_values)[len(underlying_values)//2] if underlying_values else 0.0

    for p, team, minutes, ff3, ff5, diff5, underlying in staged:
        pos = position_name(p.get("element_type", 0))
        price = safe_float(p.get("now_cost"), 0) / 10.0
        own = safe_float(p.get("selected_by_percent"), 0)

        pts = expected_points(p, minutes, ff3, ff5, underlying)

        # Availability / minutes penalties remain explicit.
        status = p.get("status")
        if status in ("u", "i", "s"):
            pts *= 0.40
        elif status == "d":
            chance = safe_float(p.get("chance_of_playing_next_round"), 75)
            pts *= 0.60 if chance < 75 else 0.75

        if minutes < 45:
            pts *= 0.72
        elif minutes < 60:
            pts *= 0.88

        pts = round(pts, 3)

        value = pts / max(price, 4.0)
        pos_value_scale = {"GKP": 0.78, "DEF": 0.92, "MID": 1.05, "FWD": 1.08}
        value_component = value * pos_value_scale.get(pos, 1.0)

        minutes_component = clamp(minutes / 90.0, 0.0, 1.0)
        role_component = _role_score(p)
        differential_bonus = clamp((15.0 - own) / 15.0, 0.0, 1.0)

        # Explicit model components, exposed to Streamlit later.
        form_score = clamp(
            0.55 * safe_float(p.get("form"), 0) / 6.0
            + 0.45 * safe_float(p.get("points_per_game"), 0) / 6.0,
            0, 1
        )

        fixture_score = clamp(0.65 * ff3 + 0.35 * ff5, 0, 1)

        # FPL Score 0-100. This is a decision score, not a projection.
        # Expected points remain the main driver.
        fpl_score_raw = (
            0.36 * clamp(pts / 7.0, 0, 1)
            + 0.20 * minutes_component
            + 0.14 * underlying
            + 0.12 * fixture_score
            + 0.08 * form_score
            + 0.07 * clamp(value_component / 1.5, 0, 1)
            + 0.03 * role_component
        )
        fpl_score = round(100.0 * clamp(fpl_score_raw, 0, 1), 1)

        # Transfer score: expected points dominate. Ownership is only a
        # strategic bonus, never a substitute for quality.
        transfer_score = (
            pts * 1.20
            + value_component * 1.55
            + fixture_score * 0.90
            + minutes_component * 0.85
            + role_component * 0.55
            + differential_bonus * 0.45
            + fpl_score * 0.025
        )

        if own < 1.0 and pts < 2.0:
            transfer_score -= 0.50

        # Captain score: expected returns + minutes + attacking upside.
        position_cap_weight = {
            "GKP": 0.82,
            "DEF": 0.93,
            "MID": 1.07,
            "FWD": 1.10,
        }
        attack_weight = {
            "GKP": 0.00,
            "DEF": 0.18,
            "MID": 0.55,
            "FWD": 0.70,
        }

        captain_score = (
            pts
            * position_cap_weight.get(pos, 1.0)
            * (0.72 + 0.28 * minutes_component)
            * (0.88 + 0.24 * fixture_score)
            + attack_weight.get(pos, 0.0) * underlying
        )

        # Do not allow a low-projection defender/GK to become captain merely
        # through a good clean-sheet fixture.
        if pos in ("GKP", "DEF") and pts < 3.5:
            captain_score *= 0.78

        differential_score = (
            pts * 1.35
            + value_component * 1.90
            + differential_bonus * 1.55
            + fixture_score * 0.80
            + minutes_component * 0.65
            + fpl_score * 0.020
        )

        # Human-readable risk classification.
        if minutes >= 80 and role_component >= 0.75:
            minutes_risk = "LOW"
        elif minutes >= 60:
            minutes_risk = "MEDIUM"
        else:
            minutes_risk = "HIGH"

        if status in ("u", "i", "s"):
            availability_risk = "HIGH"
        elif status == "d":
            availability_risk = "MEDIUM"
        else:
            availability_risk = "LOW"

        out.append({
            "id": p.get("id"),
            "name": p.get("web_name") or f'{p.get("first_name","")} {p.get("second_name","")}'.strip(),
            "team_name": team.get("name", "?"),
            "team_id": p.get("team"),
            "position": pos,
            "price": price,
            "ownership": own,
            "expected_minutes": minutes,
            "expected_gw_points": pts,
            "value": round(value, 4),
            "fixture_next3": round(ff3, 3),
            "fixture_next5": round(ff5, 3),
            "next5_avg_difficulty": round(diff5, 2),
            "underlying_score": round(underlying, 4),
            "form_score": round(form_score, 4),
            "fixture_score": round(fixture_score, 4),
            "role_score": round(role_component, 4),
            "fpl_score": fpl_score,
            "minutes_risk": minutes_risk,
            "availability_risk": availability_risk,
            "transfer_score": round(transfer_score, 3),
            "captain_score": round(captain_score, 3),
            "differential_score": round(differential_score, 3),
        })

    return pd.DataFrame(out)

def assign_recommendations(df):
    # Recommendations are relative to the current player pool, so the labels
    # remain useful when prices/form/fixtures change.
    df = df.copy()
    eligible = df[df.expected_minutes >= 60]
    if len(eligible):
        t80 = eligible.transfer_score.quantile(0.80)
        t55 = eligible.transfer_score.quantile(0.55)
        good_points = eligible.expected_gw_points.quantile(0.65)
    else:
        t80, t55, good_points = 5.0, 3.5, 2.5

    recs = []
    for _, r in df.iterrows():
        if r.expected_minutes < 45 or r.expected_gw_points < 1.5:
            recs.append("AVOID")
        elif r.transfer_score >= t80 and r.expected_gw_points >= good_points:
            recs.append("BUY")
        elif r.transfer_score >= t55:
            recs.append("WATCH")
        else:
            recs.append("AVOID")
    df["recommendation"] = recs
    return df


def starting_xi(squad):
    """Return the best legal starting XI and its projected points."""
    gk = [x for x in squad if x["position"] == "GKP"]
    defs = [x for x in squad if x["position"] == "DEF"]
    mids = [x for x in squad if x["position"] == "MID"]
    fwds = [x for x in squad if x["position"] == "FWD"]

    if not gk:
        return [], 0.0

    best = None
    # Legal formations: 3-4-3, 3-5-2, 4-3-3, 4-4-2, 4-5-1, 5-2-3,
    # 5-3-2, 5-4-1.
    for nd, nm, nf in [(3,4,3),(3,5,2),(4,3,3),(4,4,2),
                       (4,5,1),(5,2,3),(5,3,2),(5,4,1)]:
        if len(defs) < nd or len(mids) < nm or len(fwds) < nf:
            continue
        xi = (
            sorted(gk, key=lambda x: x["expected_gw_points"], reverse=True)[:1]
            + sorted(defs, key=lambda x: x["expected_gw_points"], reverse=True)[:nd]
            + sorted(mids, key=lambda x: x["expected_gw_points"], reverse=True)[:nm]
            + sorted(fwds, key=lambda x: x["expected_gw_points"], reverse=True)[:nf]
        )
        pts = sum(x["expected_gw_points"] for x in xi)
        if best is None or pts > best[1]:
            best = (xi, pts)

    return best if best else ([], 0.0)


def squad_objective(squad):
    xi, xi_pts = starting_xi(squad)
    if len(xi) != 11:
        return -1e9, xi, []

    xi_ids = {x["id"] for x in xi}
    bench = [x for x in squad if x["id"] not in xi_ids]
    bench = sorted(bench, key=lambda x: x["expected_gw_points"], reverse=True)

    # Bench has value, but substantially less than the starting XI.
    bench_cover = sum(x["expected_gw_points"] for x in bench) * 0.18
    minutes_cover = sum(clamp(x["expected_minutes"] / 90.0, 0, 1) for x in bench) * 0.05
    return xi_pts + bench_cover + minutes_cover, xi, bench


def select_squad(df, budget=100.0):
    # Fast stochastic + local-search optimizer. It respects the official
    # 2/5/5/3 structure, £100m budget and max 3 players per club.
    positions = ["GKP", "DEF", "MID", "FWD"]
    needs = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}

    pools = {}
    for pos in positions:
        g = df[df.position == pos].copy()
        # Keep strong candidates plus value candidates to preserve diversity.
        a = g.sort_values("expected_gw_points", ascending=False).head(35)
        b = g.sort_values("value", ascending=False).head(20)
        c = g.sort_values("fixture_next3", ascending=False).head(15)
        pools[pos] = pd.concat([a, b, c]).drop_duplicates("id").to_dict("records")

    def make_seed(mode):
        chosen, cost, clubs = [], 0.0, {}
        for pos in positions:
            need = needs[pos]
            candidates = pools[pos]
            if mode == 1:
                candidates = sorted(candidates, key=lambda x: x["value"], reverse=True)
            elif mode == 2:
                candidates = sorted(candidates, key=lambda x: x["fixture_next3"], reverse=True)
            elif mode == 3:
                candidates = sorted(candidates, key=lambda x: x["transfer_score"], reverse=True)
            elif mode == 4:
                candidates = sorted(candidates, key=lambda x: x["expected_gw_points"] + 0.5*x["value"], reverse=True)

            for x in candidates:
                if len([z for z in chosen if z["position"] == pos]) >= need:
                    break
                if clubs.get(x["team_id"], 0) >= 3:
                    continue
                if cost + x["price"] > budget:
                    continue
                chosen.append(x)
                cost += x["price"]
                clubs[x["team_id"]] = clubs.get(x["team_id"], 0) + 1

        # Repair missing slots using the cheapest valid candidates.
        while len(chosen) < 15:
            missing = next((p for p in positions if len([z for z in chosen if z["position"] == p]) < needs[p]), None)
            if missing is None:
                break
            cand = sorted(
                pools[missing],
                key=lambda x: (x["price"], -x["expected_gw_points"])
            )
            added = False
            for x in cand:
                if x["id"] in {z["id"] for z in chosen}:
                    continue
                if clubs.get(x["team_id"], 0) >= 3:
                    continue
                if cost + x["price"] <= budget:
                    chosen.append(x)
                    cost += x["price"]
                    clubs[x["team_id"]] = clubs.get(x["team_id"], 0) + 1
                    added = True
                    break
            if not added:
                return None
        return chosen

    def improve(chosen):
        cost = sum(x["price"] for x in chosen)
        best_obj = squad_objective(chosen)[0]
        improved = True
        loops = 0
        while improved and loops < 80:
            improved = False
            loops += 1
            current_ids = {x["id"] for x in chosen}
            for i, old in enumerate(list(chosen)):
                pos = old["position"]
                candidates = sorted(
                    pools[pos],
                    key=lambda x: x["expected_gw_points"] + 0.25*x["value"],
                    reverse=True
                )[:25]
                for new in candidates:
                    if new["id"] in current_ids:
                        continue
                    new_cost = cost - old["price"] + new["price"]
                    if new_cost > budget + 1e-9:
                        continue
                    trial = chosen.copy()
                    trial[i] = new
                    club_counts = {}
                    for z in trial:
                        club_counts[z["team_id"]] = club_counts.get(z["team_id"], 0) + 1
                    if max(club_counts.values()) > 3:
                        continue
                    obj = squad_objective(trial)[0]
                    if obj > best_obj + 1e-7:
                        chosen = trial
                        current_ids = {x["id"] for x in chosen}
                        cost = new_cost
                        best_obj = obj
                        improved = True
                        break
                if improved:
                    break
        return chosen

    best = None
    for mode in range(5):
        seed = make_seed(mode)
        if seed is None:
            continue
        seed = improve(seed)
        obj, xi, bench = squad_objective(seed)
        cost = sum(x["price"] for x in seed)
        if cost <= budget + 1e-9 and (best is None or obj > best[0]):
            best = (obj, cost, seed, xi, bench)

    return best


def save_outputs(df, squad_result, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    df.sort_values("transfer_score", ascending=False).to_csv(outdir / "players_v20.csv", index=False)

    for name, col, filt in [
        ("top_transfers_v20.csv", "transfer_score", None),
        ("top_captains_v20.csv", "captain_score", None),
        ("top_differentials_v20.csv", "differential_score", df.ownership <= 10),
        ("top_value_v20.csv", "value", None),
    ]:
        x = df if filt is None else df[filt]
        x.sort_values(col, ascending=False).head(25).to_csv(outdir / name, index=False)

    if squad_result:
        _, cost, squad, xi, bench = squad_result
        pd.DataFrame(squad).sort_values(["position", "expected_gw_points"], ascending=[True, False]).to_csv(
            outdir / "best_squad_v20.csv", index=False
        )
        pd.DataFrame(xi).to_csv(outdir / "starting_xi_v20.csv", index=False)
        pd.DataFrame(bench).to_csv(outdir / "bench_v20.csv", index=False)
        return cost, squad
    return None, []


def print_table(title, df, cols, n=20):
    print("\n" + "=" * 92)
    print(title)
    print("=" * 92)
    print(df[cols].head(n).to_string(index=False))


def main():
    started = time.time()
    print("FPL ANALYZER V2.0 – SMART FPL DECISION ENGINE")
    print("Live data + fixtures + transfer model + captain model + starting XI optimizer.")
    print("Python:", __import__("sys").version.split()[0])

    data, teams, raw_players = load_fpl()
    fixtures = load_fixtures()
    print("Live spillere:", len(raw_players))

    df = assign_recommendations(build_players(raw_players, teams, fixtures))

    # Sanity checks: these are intentionally visible.
    print("\nSANITY CHECK")
    print("  Expected GW points range:", round(df.expected_gw_points.min(), 2), "-", round(df.expected_gw_points.max(), 2))
    print("  Expected minutes range:", round(df.expected_minutes.min(), 1), "-", round(df.expected_minutes.max(), 1))
    print("  Fixed-point bug check:", "PASS" if df.expected_minutes.nunique() > 5 else "FAIL")
    print("  Captain premium sanity:", "PASS" if df[df.position.isin(["MID","FWD"])].captain_score.max() >= df[df.position.isin(["GKP","DEF"])].captain_score.max() * 0.90 else "CHECK")
    print("  Extreme GW projection check:", "PASS" if df.expected_gw_points.max() <= 10 else "FAIL")

    cols = ["name", "team_name", "position", "price", "ownership", "expected_minutes",
            "expected_gw_points", "value", "fixture_next3", "transfer_score", "recommendation"]
    print_table("V2.0 LIVE TOPPVALG – TRANSFER", df.sort_values("transfer_score", ascending=False), cols)

    cap_cols = ["name", "team_name", "position", "price", "expected_minutes",
                "expected_gw_points", "fixture_next3", "captain_score"]
    captain_pool = df[df.expected_minutes >= 60].copy()
    captain_pool = captain_pool.sort_values(["captain_score", "expected_gw_points"], ascending=False)
    print_table("V2.0 TOPP KAPTEINER", captain_pool.sort_values("captain_score", ascending=False), cap_cols, 10)

    diff_cols = ["name", "team_name", "position", "price", "ownership", "expected_minutes",
                 "expected_gw_points", "value", "fixture_next3", "differential_score"]
    print_table("V2.0 TOPP DIFFERENTIALS (<=10% OWNERSHIP)",
                df[df.ownership <= 10].sort_values("differential_score", ascending=False),
                diff_cols, 20)

    print_table("V2.0 BEST VALUE (£m)", df.sort_values("value", ascending=False), cols, 15)

    print("\n" + "=" * 92)
    print("BEST 15-MAN SQUAD (<= £100m, valid FPL structure)")
    print("=" * 92)
    result = select_squad(df, 100.0)
    if result:
        score, cost, squad, xi, bench = result
        print(f"Total cost: £{cost:.1f}m")
        print(f"Squad objective: {score:.2f}")
        print("STARTING XI:")
        print(pd.DataFrame(xi)[["name", "team_name", "position", "price", "expected_gw_points"]].to_string(index=False))
        print("\nBENCH:")
        print(pd.DataFrame(bench)[["name", "team_name", "position", "price", "expected_gw_points"]].to_string(index=False))
        cap = max(xi, key=lambda x: x["captain_score"])
        vice_pool = [x for x in xi if x["id"] != cap["id"]]
        vice = max(vice_pool, key=lambda x: x["captain_score"])
        print(f"\nCAPTAIN: {cap['name']} ({cap['position']})")
        print(f"VICE-CAPTAIN: {vice['name']} ({vice['position']})")
    else:
        print("Ingen gyldig tropp funnet.")

    outdir = Path(__file__).resolve().parent / "data"
    save_outputs(df, result, outdir)

    print("\n" + "=" * 92)
    print("V2.0 FERDIG")
    print("Data lagret i:", outdir)
    print("Tid brukt:", round(time.time() - started, 1), "sekunder")
    print("=" * 92)


if __name__ == "__main__":
    main()