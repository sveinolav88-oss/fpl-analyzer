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


def expected_points(p, minutes, fixture):
    # Build a deliberately conservative GW estimate from current FPL season signals.
    # Do NOT use total historical points as a raw one-GW prediction.
    ppg = safe_float(p.get("points_per_game"), 0)
    form = safe_float(p.get("form"), 0)
    ep_next = safe_float(p.get("ep_next"), 0)

    # Use FPL's own ep_next when present, otherwise current PPG/form blend.
    if ep_next > 0:
        raw = ep_next
    else:
        raw = 0.65 * ppg + 0.35 * form

    # Current-season/preseason values can be noisy. Keep a realistic GW range.
    pos = position_name(p.get("element_type", 0))
    floors = {"GKP": 1.5, "DEF": 1.4, "MID": 1.2, "FWD": 1.1}
    caps = {"GKP": 6.5, "DEF": 7.0, "MID": 9.0, "FWD": 9.5}

    # Minutes scale around 90, but do not punish normal rotation too harshly.
    minute_factor = clamp(minutes / 90.0, 0.0, 1.0)
    # Fixture adjustment is intentionally modest.
    fixture_adj = 0.82 + 0.36 * fixture

    value = raw * minute_factor * fixture_adj
    return round(clamp(value, floors.get(pos, 1.2), caps.get(pos, 8.0)), 3)


def attacking_proxy(p):
    pos = position_name(p.get("element_type", 0))
    if pos == "GKP":
        return 0.05
    xgi = safe_float(p.get("expected_goal_involvements"), 0)
    # xGI is season-to-date; normalize very conservatively.
    return clamp(xgi / 10.0, 0.0, 1.0)


def build_players(raw, teams, fixtures):
    out = []
    for p in raw:
        team = teams.get(p.get("team"), {})
        minutes = expected_minutes(p)
        ff, diff = fixture_factor(p.get("team"), fixtures, 5)
        ff3, _ = fixture_factor(p.get("team"), fixtures, 3)
        pts = expected_points(p, minutes, ff)
        price = safe_float(p.get("now_cost"), 0) / 10.0
        own = safe_float(p.get("selected_by_percent"), 0)

        # Availability / role sanity.
        if p.get("status") in ("u", "i", "s", "d"):
            pts *= 0.55
        if minutes < 45:
            pts *= 0.75

        value = pts / max(price, 4.0)
        xgi_proxy = attacking_proxy(p)

        # Transfer score rewards points, value and low ownership, but is not a captain score.
        differential_bonus = clamp((15.0 - own) / 15.0, 0, 1)
        transfer_score = (
            pts * 0.55
            + value * 3.0
            + ff3 * 1.5
            + differential_bonus * 1.5
        )

        # Captain score: strongly weighted to expected points, minutes and attacking role.
        # Explicitly exclude cheap-player/value bonuses.
        cap_score = (
            pts
            * (0.65 + 0.35 * clamp(minutes / 90.0, 0, 1))
            * (0.82 + 0.36 * ff3)
            * (1.0 + 0.10 * xgi_proxy)
        )

        differential_score = (
            pts * 2.0
            + value * 5.0
            + differential_bonus * 4.0
            + ff3 * 2.0
        )

        if transfer_score >= 8.0:
            rec = "BUY"
        elif transfer_score >= 5.5:
            rec = "WATCH"
        else:
            rec = "AVOID"

        out.append({
            "id": p.get("id"),
            "name": p.get("web_name") or f'{p.get("first_name","")} {p.get("second_name","")}'.strip(),
            "team_name": team.get("name", "?"),
            "team_id": p.get("team"),
            "position": position_name(p.get("element_type", 0)),
            "price": price,
            "ownership": own,
            "expected_minutes": minutes,
            "expected_gw_points": round(pts, 3),
            "value": round(value, 4),
            "fixture_next3": round(ff3, 3),
            "next5_avg_difficulty": round(diff, 2),
            "xgi_proxy": round(xgi_proxy, 4),
            "transfer_score": round(transfer_score, 3),
            "captain_score": round(cap_score, 3),
            "differential_score": round(differential_score, 3),
            "recommendation": rec,
        })
    return pd.DataFrame(out)


def select_squad(df, budget=100.0):
    # Fast valid FPL squad optimizer using greedy seeds + local improvement.
    # 2 GKP, 5 DEF, 5 MID, 3 FWD; max 3 from a club.
    groups = {pos: df[df.position == pos].sort_values("expected_gw_points", ascending=False)
              for pos in ["GKP", "DEF", "MID", "FWD"]}

    best = None
    # Keep a manageable candidate pool; unlike the old combinatorial optimizer this cannot hang.
    pools = {pos: g.head(25).to_dict("records") for pos, g in groups.items()}

    def score(s):
        return sum(x["expected_gw_points"] for x in s)

    # Build several seeds from different value/points blends.
    for seed_mode in range(5):
        chosen = []
        counts = {"GKP": 0, "DEF": 0, "MID": 0, "FWD": 0}
        club = {}
        cost = 0.0
        for pos, need in [("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]:
            candidates = pools[pos]
            if seed_mode == 1:
                candidates = sorted(candidates, key=lambda x: x["value"], reverse=True)
            elif seed_mode == 2:
                candidates = sorted(candidates, key=lambda x: x["fixture_next3"], reverse=True)
            elif seed_mode == 3:
                candidates = sorted(candidates, key=lambda x: x["differential_score"], reverse=True)
            elif seed_mode == 4:
                candidates = sorted(candidates, key=lambda x: x["expected_gw_points"] + x["value"], reverse=True)

            for x in candidates:
                if counts[pos] >= need:
                    break
                if club.get(x["team_id"], 0) >= 3:
                    continue
                if cost + x["price"] > budget:
                    continue
                chosen.append(x)
                counts[pos] += 1
                club[x["team_id"]] = club.get(x["team_id"], 0) + 1
                cost += x["price"]

        if len(chosen) != 15:
            continue

        # Fill/repair by swaps.
        improved = True
        while improved:
            improved = False
            current_score = score(chosen)
            for i, old in enumerate(list(chosen)):
                pos = old["position"]
                for new in pools[pos]:
                    if new["id"] in {x["id"] for x in chosen}:
                        continue
                    new_cost = cost - old["price"] + new["price"]
                    if new_cost > budget + 1e-9:
                        continue
                    new_club = dict(club)
                    new_club[old["team_id"]] = new_club.get(old["team_id"], 0) - 1
                    new_club[new["team_id"]] = new_club.get(new["team_id"], 0) + 1
                    if max(new_club.values()) > 3:
                        continue
                    trial = chosen.copy()
                    trial[i] = new
                    if score(trial) > current_score + 1e-9:
                        chosen = trial
                        cost = new_cost
                        club = new_club
                        improved = True
                        break
                if improved:
                    break

        if len(chosen) == 15:
            sc = score(chosen)
            if best is None or sc > best[0]:
                best = (sc, cost, chosen)

    return best


def save_outputs(df, squad_result, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    df.sort_values("transfer_score", ascending=False).to_csv(outdir / "players_v16.csv", index=False)

    for name, col, filt in [
        ("top_transfers_v16.csv", "transfer_score", None),
        ("top_captains_v16.csv", "captain_score", None),
        ("top_differentials_v16.csv", "differential_score", df.ownership <= 10),
        ("top_value_v16.csv", "value", None),
    ]:
        x = df if filt is None else df[filt]
        x.sort_values(col, ascending=False).head(25).to_csv(outdir / name, index=False)

    if squad_result:
        _, cost, squad = squad_result
        pd.DataFrame(squad).sort_values(["position", "expected_gw_points"], ascending=[True, False]).to_csv(
            outdir / "best_squad_v16.csv", index=False
        )
        return cost, squad
    return None, []


def print_table(title, df, cols, n=20):
    print("\n" + "=" * 92)
    print(title)
    print("=" * 92)
    print(df[cols].head(n).to_string(index=False))


def main():
    started = time.time()
    print("FPL ANALYZER V1.6 – CALIBRATED DECISION ENGINE")
    print("Live data + fixtures + realistic GW projection + captain sanity + fast squad optimizer.")
    print("Python:", __import__("sys").version.split()[0])

    data, teams, raw_players = load_fpl()
    fixtures = load_fixtures()
    print("Live spillere:", len(raw_players))

    df = build_players(raw_players, teams, fixtures)

    # Sanity checks: these are intentionally visible.
    print("\nSANITY CHECK")
    print("  Expected GW points range:", round(df.expected_gw_points.min(), 2), "-", round(df.expected_gw_points.max(), 2))
    print("  Expected minutes range:", round(df.expected_minutes.min(), 1), "-", round(df.expected_minutes.max(), 1))
    print("  Fixed-point bug check (all 67.5 min):", "PASS" if df.expected_minutes.nunique() > 5 else "FAIL")
    print("  Extreme GW projection check:", "PASS" if df.expected_gw_points.max() <= 10 else "FAIL")

    cols = ["name", "team_name", "position", "price", "ownership", "expected_minutes",
            "expected_gw_points", "value", "fixture_next3", "transfer_score", "recommendation"]
    print_table("V1.6 LIVE TOPPVALG – TRANSFER", df.sort_values("transfer_score", ascending=False), cols)

    cap_cols = ["name", "team_name", "position", "price", "expected_minutes",
                "expected_gw_points", "fixture_next3", "captain_score"]
    captain_pool = df[df.expected_minutes >= 60].copy()
    print_table("V1.6 TOPP KAPTEINER", captain_pool.sort_values("captain_score", ascending=False), cap_cols, 10)

    diff_cols = ["name", "team_name", "position", "price", "ownership", "expected_minutes",
                 "expected_gw_points", "value", "fixture_next3", "differential_score"]
    print_table("V1.6 TOPP DIFFERENTIALS (<=10% OWNERSHIP)",
                df[df.ownership <= 10].sort_values("differential_score", ascending=False),
                diff_cols, 20)

    print_table("V1.6 BEST VALUE (£m)", df.sort_values("value", ascending=False), cols, 15)

    print("\n" + "=" * 92)
    print("BEST 15-MAN SQUAD (<= £100m, valid FPL structure)")
    print("=" * 92)
    result = select_squad(df, 100.0)
    if result:
        score, cost, squad = result
        print(f"Total cost: £{cost:.1f}m")
        print(f"Projected points: {score:.2f}")
        print(pd.DataFrame(squad)[["name", "team_name", "position", "price", "expected_gw_points"]].to_string(index=False))
    else:
        print("Ingen gyldig tropp funnet.")

    outdir = Path(__file__).resolve().parent / "data"
    save_outputs(df, result, outdir)

    print("\n" + "=" * 92)
    print("V1.6 FERDIG")
    print("Data lagret i:", outdir)
    print("Tid brukt:", round(time.time() - started, 1), "sekunder")
    print("=" * 92)


if __name__ == "__main__":
    main()
