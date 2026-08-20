"""Calibrated FPL scoring model used by the Streamlit app.

The goal is not to inflate projections, but to avoid double-counting the
minutes penalty already reflected in FPL ep_next and to expose a more useful
FPL-level expectation (XI + captain + rolling 4-GW outlook).
"""

import math
from collections import Counter

import pandas as pd

from main import (
    clamp,
    safe_float,
    position_name,
    expected_minutes,
    minutes_probability,
    fixture_quality,
    fixture_factor,
    get_xg_rate,
    get_xa_rate,
    get_xgi_rate,
    get_goal_rate,
    get_assist_rate,
    get_bonus_rate,
    select_squad,
)


def _sample_reliability(p):
    minutes = safe_float(p.get("minutes"), 0.0)
    appearances = safe_float(p.get("appearances"), 0.0)
    if minutes >= 900:
        return 1.0
    if minutes >= 450:
        return 0.92
    if minutes >= 180:
        return 0.82
    if appearances >= 2:
        return 0.72
    return 0.60


def _availability_factor(p, minutes):
    status = p.get("status", "a")
    chance = p.get("chance_of_playing_next_round")
    if chance is None:
        chance = 100.0 if status == "a" else 0.0
    chance = clamp(safe_float(chance, 100.0) / 100.0, 0.0, 1.0)
    if status == "d":
        chance *= 0.85
    elif status == "s":
        chance *= 0.65
    elif status in ("i", "u"):
        chance *= 0.45
    # ep_next already contains a minutes/availability signal. Only apply a
    # light availability adjustment here; do not multiply it by minutes again.
    if minutes >= 75:
        minutes_factor = 1.0
    elif minutes >= 60:
        minutes_factor = 0.97
    elif minutes >= 45:
        minutes_factor = 0.88
    elif minutes >= 30:
        minutes_factor = 0.68
    else:
        minutes_factor = 0.40
    return chance * minutes_factor


def _underlying_attack_signal(p, pos):
    xg90 = get_xg_rate(p)
    xa90 = get_xa_rate(p)
    xgi90 = get_xgi_rate(p)
    goal90 = get_goal_rate(p)
    assist90 = get_assist_rate(p)

    if pos == "FWD":
        return clamp(0.55 * xg90 + 0.30 * xa90 + 0.15 * goal90, 0.0, 1.8)
    if pos == "MID":
        return clamp(0.42 * xg90 + 0.38 * xa90 + 0.20 * goal90, 0.0, 1.6)
    if pos == "DEF":
        return clamp(0.55 * xgi90 + 0.25 * xa90 + 0.20 * assist90, 0.0, 1.0)
    return 0.0


def calibrated_expected_points(p, minutes, fixtures):
    """Return a calibrated one-GW FPL expectation.

    FPL ep_next is treated as a strong prior rather than the whole answer.
    Historical PPG/form and underlying numbers provide a bounded correction.
    Fixture and availability are applied once, avoiding the previous
    double-minutes discount that pushed XI totals too low.
    """
    pos = position_name(p.get("element_type", 0))
    ep_next = safe_float(p.get("ep_next"), 0.0)
    ppg = safe_float(p.get("points_per_game"), 0.0)
    form = safe_float(p.get("form"), 0.0)
    reliability = _sample_reliability(p)
    fixture_q, _ = fixture_factor(p.get("team"), fixtures, 1)
    fixture_q3, _ = fixture_factor(p.get("team"), fixtures, 3)
    attack = _underlying_attack_signal(p, pos)

    # Build a prior. FPL ep_next is normally the best short-term signal, but
    # blending it prevents a single stale/over-conservative value dominating.
    if ep_next > 0:
        historical = 0.62 * ppg + 0.38 * form if ppg > 0 or form > 0 else ep_next
        base = 0.62 * ep_next + 0.26 * historical + 0.12 * (2.0 + attack)
    else:
        base = 0.58 * ppg + 0.27 * form + 0.15 * (2.0 + attack)

    # Small underlying-data correction, bounded so xG/xA cannot overwhelm FPL data.
    if pos in ("MID", "FWD"):
        base += clamp(0.32 * attack, 0.0, 0.65)
    elif pos == "DEF":
        base += clamp(0.18 * attack, 0.0, 0.20)

    # Fixture adjustment is intentionally modest: 1..5 FDR should move a
    # projection, not completely rewrite it.
    fixture_multiplier = 0.94 + 0.12 * fixture_q
    near_term_bonus = (fixture_q3 - 0.5) * 0.10
    base = base * fixture_multiplier + near_term_bonus

    # Apply availability once. This is the key calibration change versus the
    # old model, which multiplied ep_next by a large minutes factor again.
    base *= _availability_factor(p, minutes)

    # Keep a small appearance floor for reliable starters and a strong penalty
    # for players unlikely to feature.
    if minutes >= 75 and base < 2.0:
        base = max(base, 2.0)
    if minutes < 45:
        base *= 0.82

    caps = {"GKP": 9.0, "DEF": 11.0, "MID": 13.0, "FWD": 13.0}
    return round(clamp(base, 1.0 if minutes >= 45 else 0.5, caps.get(pos, 11.0)), 3)


def build_players(raw, teams, fixtures):
    rows = []
    for p in raw:
        team = teams.get(p.get("team"), {})
        minutes = expected_minutes(p)
        fixture = fixture_quality(p.get("team"), fixtures)
        pos = position_name(p.get("element_type", 0))
        pts = calibrated_expected_points(p, minutes, fixtures)
        price = safe_float(p.get("now_cost"), 0.0) / 10.0
        ownership = safe_float(p.get("selected_by_percent"), 0.0)
        xg90, xa90, xgi90 = get_xg_rate(p), get_xa_rate(p), get_xgi_rate(p)
        goal90, assist90, bonus90 = get_goal_rate(p), get_assist_rate(p), get_bonus_rate(p)
        ppg = safe_float(p.get("points_per_game"), 0.0)
        form = safe_float(p.get("form"), 0.0)
        minutes_component = clamp(minutes / 90.0, 0.0, 1.0)
        differential_bonus = clamp((15.0 - ownership) / 15.0, 0.0, 1.0)
        value = pts / max(price, 4.0)
        pos_value_scale = {"GKP": 0.82, "DEF": 0.94, "MID": 1.05, "FWD": 1.08}
        value_component = value * pos_value_scale.get(pos, 1.0)
        form_delta = clamp(form - ppg, -3.0, 3.0)

        transfer_score = (
            pts * 1.65 + value_component * 1.30 + fixture["fixture_next3"] * 1.05
            + fixture["fixture_next5"] * 0.35 + minutes_component * 0.85
            + differential_bonus * 0.35 + clamp(xgi90, 0.0, 1.2) * 0.50
            + clamp(form_delta / 2.0, -1.0, 1.0) * 0.18
        )
        if minutes < 45:
            transfer_score *= 0.55

        captain_score = (
            pts * {"GKP": 0.82, "DEF": 0.94, "MID": 1.08, "FWD": 1.12}.get(pos, 1.0)
            * (0.88 + 0.12 * minutes_component)
            * (0.94 + 0.12 * fixture["fixture_next1"])
        )
        if pos in ("MID", "FWD"):
            captain_score += clamp(0.45 * _underlying_attack_signal(p, pos), 0.0, 0.7)
        if pos in ("GKP", "DEF") and pts < 3.5:
            captain_score *= 0.88

        differential_score = pts * 1.35 + value_component * 1.65 + differential_bonus * 1.65 + fixture["fixture_next3"] * 0.85 + minutes_component * 0.55 + clamp(xgi90, 0.0, 1.2) * 0.55
        value_score = value * 2.0 + pts * 0.75 + fixture["fixture_next3"] * 0.45 + minutes_component * 0.55

        rows.append({
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
            "xg90": round(xg90, 3), "xa90": round(xa90, 3), "xgi90": round(xgi90, 3),
            "goals_per90": round(goal90, 3), "assists_per90": round(assist90, 3), "bonus_per90": round(bonus90, 3),
            "value": round(value, 4),
            "fixture_next1": round(fixture["fixture_next1"], 3), "fixture_next3": round(fixture["fixture_next3"], 3), "fixture_next5": round(fixture["fixture_next5"], 3),
            "next1_avg_difficulty": round(fixture["difficulty_next1"], 2), "next3_avg_difficulty": round(fixture["difficulty_next3"], 2), "next5_avg_difficulty": round(fixture["difficulty_next5"], 2),
            "form": form, "points_per_game": ppg,
            "transfer_score": round(transfer_score, 3), "captain_score": round(captain_score, 3),
            "differential_score": round(differential_score, 3), "value_score": round(value_score, 3),
        })
    return pd.DataFrame(rows)


def assign_recommendations(df):
    df = df.copy()
    eligible = df[(df.expected_minutes >= 60) & (df.expected_gw_points >= 1.5)]
    if len(eligible):
        t85, t60 = eligible.transfer_score.quantile(0.85), eligible.transfer_score.quantile(0.60)
        good_points = eligible.expected_gw_points.quantile(0.65)
    else:
        t85, t60, good_points = 5.0, 3.5, 2.5
    recs=[]
    for _, r in df.iterrows():
        if r.expected_minutes < 45 or r.expected_gw_points < 1.5:
            recs.append("AVOID")
        elif r.transfer_score >= t85 and r.expected_gw_points >= good_points:
            recs.append("BUY")
        elif r.transfer_score >= t60:
            recs.append("WATCH")
        else:
            recs.append("AVOID")
    df["recommendation"] = recs
    return df


def captain_expectation(xi):
    if not xi:
        return None
    cap = max(xi, key=lambda x: float(x.get("captain_score", 0.0)))
    vice_pool = [x for x in xi if x.get("id") != cap.get("id")]
    vice = max(vice_pool, key=lambda x: float(x.get("captain_score", 0.0))) if vice_pool else cap
    return cap, vice


def fpl_level_projection(xi):
    """Return expected XI, captain bonus and expected FPL score."""
    xi_points = sum(float(x.get("expected_gw_points", 0.0)) for x in xi)
    pair = captain_expectation(xi)
    if not pair:
        return {"xi": xi_points, "captain": 0.0, "total": xi_points, "captain_name": None, "vice_name": None}
    cap, vice = pair
    cap_points = float(cap.get("expected_gw_points", 0.0))
    return {
        "xi": xi_points,
        "captain": cap_points,
        "total": xi_points + cap_points,
        "captain_name": cap.get("name"),
        "vice_name": vice.get("name"),
    }


def four_gw_player_projection(df, fixtures, start_gw, horizon=4):
    """Create a lightweight rolling projection using the same calibrated GW1 model."""
    events = list(range(int(start_gw), min(38, int(start_gw) + horizon - 1) + 1))
    rows=[]
    for _, r in df.iterrows():
        vals={"id":int(r.id),"name":r["name"]}
        current_q=max(0.15,min(1.0,float(r.get("fixture_next3",0.5))))
        for gw in events:
            # The FPL API fixture difficulty is handled by the existing matrix
            # in decision_engine; this keeps the UI model consistent without
            # inventing future player stats.
            vals[gw]=round(float(r.expected_gw_points) * (0.94 + 0.12*current_q), 3)
        rows.append(vals)
    return pd.DataFrame(rows).set_index("id") if rows else pd.DataFrame()
