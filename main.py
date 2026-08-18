import math
import os
import time
from pathlib import Path

import pandas as pd
import requests

API = "https://fantasy.premierleague.com/api"
TIMEOUT = 30


# ============================================================
# FPL API
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
    return {
        1: "GKP",
        2: "DEF",
        3: "MID",
        4: "FWD",
    }.get(int(element_type), "UNK")


def load_fpl():
    print("  Henter FPL live-data...")
    data = get_json("/bootstrap-static/")
    teams = {t["id"]: t for t in data["teams"]}
    players = data["elements"]
    return data, teams, players


def load_fixtures():
    print("  Henter fixtures...")
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
            rows.append(
                (
                    f.get("event") or 99,
                    True,
                    f,
                )
            )
        elif f.get("team_a") == player_team:
            rows.append(
                (
                    f.get("event") or 99,
                    False,
                    f,
                )
            )

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

    # FPL difficulty: 1 = easiest, 5 = hardest.
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
    """
    Estimate expected minutes for the next GW.

    Uses:
    - chance_of_playing_next_round
    - status
    - starts
    - minutes
    - appearances
    - points_per_game

    This is intentionally conservative.
    """

    chance = p.get("chance_of_playing_next_round")

    if chance is not None:
        chance = clamp(
            safe_float(chance, 100.0),
            0.0,
            100.0,
        ) / 100.0
    else:
        chance = 1.0 if p.get("status", "a") == "a" else 0.0

    ppg = safe_float(p.get("points_per_game"), 0.0)
    starts = safe_float(p.get("starts"), 0.0)
    minutes = safe_float(p.get("minutes"), 0.0)
    appearances = safe_float(p.get("appearances"), 0.0)

    if minutes > 0 and appearances > 0:
        avg_min = clamp(
            minutes / appearances,
            0.0,
            90.0,
        )
    else:
        avg_min = 75.0

    # Starts are a strong signal of expected minutes.
    if starts >= 15:
        base = max(avg_min, 80.0)
    elif starts >= 10:
        base = max(avg_min, 75.0)
    elif starts >= 5:
        base = max(avg_min, 65.0)
    else:
        base = min(avg_min, 60.0)

    # PPG is only a weak supporting signal.
    if ppg >= 5.5:
        base += 4.0
    elif ppg <= 2.0:
        base -= 5.0

    # Availability status.
    status = p.get("status", "a")
    if status == "i":
        chance *= 0.25
    elif status == "s":
        chance *= 0.45
    elif status == "u":
        chance *= 0.35
    elif status == "d":
        chance *= 0.70

    result = base * chance

    if chance <= 0:
        return 0.0

    return round(
        clamp(result, 20.0, 90.0),
        1,
    )


def minutes_probability(minutes):
    """
    Converts expected minutes into a soft probability of getting
    a meaningful appearance.
    """

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
# ATTACKING / DEFENSIVE MODEL
# ============================================================

def season_rate(value, minutes, fallback=0.0):
    """
    Convert season totals to a per-90 style rate.

    Returns fallback if there is not enough information.
    """

    value = safe_float(value, 0.0)
    minutes = safe_float(minutes, 0.0)

    if minutes <= 180:
        return fallback

    return max(0.0, value / minutes * 90.0)


def get_xg_rate(p):
    minutes = safe_float(p.get("minutes"), 0.0)

    xg = p.get("expected_goals")
    if xg is None:
        xg = p.get("xG")

    return season_rate(xg, minutes, 0.0)


def get_xa_rate(p):
    minutes = safe_float(p.get("minutes"), 0.0)

    xa = p.get("expected_assists")
    if xa is None:
        xa = p.get("xA")

    return season_rate(xa, minutes, 0.0)


def get_xgi_rate(p):
    xgi = p.get("expected_goal_involvements")
    minutes = safe_float(p.get("minutes"), 0.0)

    if xgi is not None:
        return season_rate(xgi, minutes, 0.0)

    return get_xg_rate(p) + get_xa_rate(p)


def get_goal_rate(p):
    return season_rate(
        p.get("goals_scored"),
        p.get("minutes"),
        0.0,
    )


def get_assist_rate(p):
    return season_rate(
        p.get("assists"),
        p.get("minutes"),
        0.0,
    )


def get_bonus_rate(p):
    return season_rate(
        p.get("bps"),
        p.get("minutes"),
        0.0,
    )


def attacking_proxy(p):
    pos = position_name(p.get("element_type", 0))

    if pos == "GKP":
        return 0.05

    xgi = get_xgi_rate(p)

    # Soft cap so a tiny sample does not dominate.
    return clamp(xgi / 1.2, 0.0, 1.0)


# ============================================================
# EXPECTED POINTS MODEL
# ============================================================

def position_base_points(pos):
    return {
        "GKP": 2.0,
        "DEF": 2.0,
        "MID": 2.0,
        "FWD": 2.0,
    }.get(pos, 2.0)


def expected_points(p, minutes, fixtures):
    """
    More explicit one-GW expected-points model.

    Priority:
    1. FPL ep_next if it is available and credible.
    2. PPG/form blend.
    3. xG/xA/xGI supporting signal.
    4. Fixture adjustment.
    5. Expected minutes.

    The output is deliberately conservative and is not presented as
    a statistical certainty.
    """

    pos = position_name(p.get("element_type", 0))

    ppg = safe_float(p.get("points_per_game"), 0.0)
    form = safe_float(p.get("form"), 0.0)
    ep_next = safe_float(p.get("ep_next"), 0.0)

    xg90 = get_xg_rate(p)
    xa90 = get_xa_rate(p)
    xgi90 = get_xgi_rate(p)

    # FPL's own next-GW projection is the strongest single signal
    # when present.
    if ep_next > 0:
        base = ep_next
    else:
        base = (
            0.55 * ppg
            + 0.30 * form
            + 0.15 * position_base_points(pos)
        )

    # xGI is used as a small upside correction.
    # We intentionally avoid making raw xG/xA the entire model.
    if pos in ("MID", "FWD"):
        attacking_signal = clamp(
            0.45 * xgi90 + 0.30 * xg90 + 0.25 * xa90,
            0.0,
            1.5,
        )
        base += 0.55 * attacking_signal

    elif pos == "DEF":
        attacking_signal = clamp(
            0.55 * xgi90 + 0.25 * xg90 + 0.20 * xa90,
            0.0,
            1.0,
        )
        base += 0.30 * attacking_signal

    # Form is useful, but should not overpower the underlying projection.
    form_delta = clamp(form - ppg, -2.0, 2.0)
    base += 0.12 * form_delta

    # Fixture quality over next 3.
    ff3, _ = fixture_factor(p.get("team"), fixtures, 3)

    # Translate 0..1 fixture quality into a modest multiplier.
    fixture_multiplier = 0.88 + 0.24 * ff3
    base *= fixture_multiplier

    # Expected minutes.
    minute_factor = clamp(minutes / 90.0, 0.0, 1.0)
    base *= 0.45 + 0.55 * minute_factor

    # Availability.
    status = p.get("status", "a")

    if status == "d":
        base *= 0.72
    elif status in ("i", "u", "s"):
        base *= 0.45

    # Keep outputs realistic for a single GW.
    floors = {
        "GKP": 1.0,
        "DEF": 1.0,
        "MID": 1.0,
        "FWD": 1.0,
    }

    caps = {
        "GKP": 7.5,
        "DEF": 8.5,
        "MID": 10.5,
        "FWD": 10.5,
    }

    return round(
        clamp(
            base,
            floors.get(pos, 1.0),
            caps.get(pos, 8.5),
        ),
        3,
    )


# ============================================================
# PLAYER DATAFRAME
# ============================================================

def build_players(raw, teams, fixtures):
    out = []

    for p in raw:
        team = teams.get(p.get("team"), {})

        minutes = expected_minutes(p)
        fixture = fixture_quality(
            p.get("team"),
            fixtures,
        )

        pts = expected_points(
            p,
            minutes,
            fixtures,
        )

        price = safe_float(
            p.get("now_cost"),
            0.0,
        ) / 10.0

        ownership = safe_float(
            p.get("selected_by_percent"),
            0.0,
        )

        pos = position_name(
            p.get("element_type", 0)
        )

        # ----------------------------------------------------
        # Basic rates
        # ----------------------------------------------------

        xg90 = get_xg_rate(p)
        xa90 = get_xa_rate(p)
        xgi90 = get_xgi_rate(p)

        goal90 = get_goal_rate(p)
        assist90 = get_assist_rate(p)
        bonus90 = get_bonus_rate(p)

        # ----------------------------------------------------
        # Value
        # ----------------------------------------------------

        value = pts / max(price, 4.0)

        pos_value_scale = {
            "GKP": 0.82,
            "DEF": 0.94,
            "MID": 1.05,
            "FWD": 1.08,
        }

        value_component = (
            value
            * pos_value_scale.get(pos, 1.0)
        )

        # ----------------------------------------------------
        # Ownership / differential
        # ----------------------------------------------------

        differential_bonus = clamp(
            (15.0 - ownership) / 15.0,
            0.0,
            1.0,
        )

        minutes_component = clamp(
            minutes / 90.0,
            0.0,
            1.0,
        )

        # ----------------------------------------------------
        # Form
        # ----------------------------------------------------

        ppg = safe_float(
            p.get("points_per_game"),
            0.0,
        )

        form = safe_float(
            p.get("form"),
            0.0,
        )

        form_delta = clamp(
            form - ppg,
            -3.0,
            3.0,
        )

        # ----------------------------------------------------
        # Transfer score
        # ----------------------------------------------------

        transfer_score = (
            pts * 1.45
            + value_component * 1.50
            + fixture["fixture_next3"] * 1.10
            + fixture["fixture_next5"] * 0.45
            + minutes_component * 0.90
            + differential_bonus * 0.45
            + clamp(xgi90 / 1.0, 0.0, 1.0) * 0.45
            + clamp(form_delta / 2.0, -1.0, 1.0) * 0.20
        )

        # Poor availability should be heavily penalised.
        if minutes < 45:
            transfer_score *= 0.55

        # Do not let low ownership make a bad player look good.
        if ownership < 1.0 and pts < 2.0:
            transfer_score -= 0.50

        # ----------------------------------------------------
        # Captain score
        # ----------------------------------------------------

        position_cap_weight = {
            "GKP": 0.86,
            "DEF": 0.94,
            "MID": 1.07,
            "FWD": 1.10,
        }

        role_weight = {
            "GKP": 0.00,
            "DEF": 0.18,
            "MID": 0.60,
            "FWD": 0.72,
        }

        explosiveness = clamp(
            0.55 * xg90
            + 0.25 * xa90
            + 0.20 * xgi90,
            0.0,
            1.5,
        )

        captain_score = (
            pts
            * position_cap_weight.get(pos, 1.0)
            * (0.72 + 0.28 * minutes_component)
            * (0.88 + 0.24 * fixture["fixture_next3"])
            + role_weight.get(pos, 0.0)
            * explosiveness
        )

        if pos in ("GKP", "DEF") and pts < 3.5:
            captain_score *= 0.82

        # ----------------------------------------------------
        # Differential score
        # ----------------------------------------------------

        differential_score = (
            pts * 1.25
            + value_component * 1.80
            + differential_bonus * 2.00
            + fixture["fixture_next3"] * 0.90
            + minutes_component * 0.55
            + clamp(xgi90 / 1.0, 0.0, 1.0) * 0.55
        )

        # ----------------------------------------------------
        # Best value score
        # ----------------------------------------------------

        value_score = (
            value * 2.00
            + pts * 0.65
            + fixture["fixture_next3"] * 0.40
            + minutes_component * 0.55
        )

        out.append(
            {
                "id": p.get("id"),
                "name": (
                    p.get("web_name")
                    or f'{p.get("first_name", "")} '
                       f'{p.get("second_name", "")}'.strip()
                ),
                "team_name": team.get(
                    "name",
                    "?",
                ),
                "team_id": p.get("team"),
                "position": pos,
                "price": round(price, 1),
                "ownership": ownership,

                "expected_minutes": minutes,
                "minutes_probability": round(
                    minutes_probability(minutes),
                    3,
                ),

                "expected_gw_points": round(
                    pts,
                    3,
                ),

                "xg90": round(xg90, 3),
                "xa90": round(xa90, 3),
                "xgi90": round(xgi90, 3),

                "goals_per90": round(
                    goal90,
                    3,
                ),
                "assists_per90": round(
                    assist90,
                    3,
                ),
                "bonus_per90": round(
                    bonus90,
                    3,
                ),

                "value": round(
                    value,
                    4,
                ),

                "fixture_next1": round(
                    fixture["fixture_next1"],
                    3,
                ),
                "fixture_next3": round(
                    fixture["fixture_next3"],
                    3,
                ),
                "fixture_next5": round(
                    fixture["fixture_next5"],
                    3,
                ),

                "next1_avg_difficulty": round(
                    fixture["difficulty_next1"],
                    2,
                ),
                "next3_avg_difficulty": round(
                    fixture["difficulty_next3"],
                    2,
                ),
                "next5_avg_difficulty": round(
                    fixture["difficulty_next5"],
                    2,
                ),

                "form": form,
                "points_per_game": ppg,

                "transfer_score": round(
                    transfer_score,
                    3,
                ),
                "captain_score": round(
                    captain_score,
                    3,
                ),
                "differential_score": round(
                    differential_score,
                    3,
                ),
                "value_score": round(
                    value_score,
                    3,
                ),
            }
        )

    return pd.DataFrame(out)


# ============================================================
# RECOMMENDATIONS
# ============================================================

def assign_recommendations(df):
    df = df.copy()

    eligible = df[
        (df.expected_minutes >= 60)
        & (df.expected_gw_points >= 1.5)
    ]

    if len(eligible):
        t85 = eligible.transfer_score.quantile(0.85)
        t60 = eligible.transfer_score.quantile(0.60)
        good_points = eligible.expected_gw_points.quantile(0.65)
    else:
        t85 = 5.0
        t60 = 3.5
        good_points = 2.5

    recs = []

    for _, r in df.iterrows():
        if (
            r.expected_minutes < 45
            or r.expected_gw_points < 1.5
        ):
            recs.append("AVOID")

        elif (
            r.transfer_score >= t85
            and r.expected_gw_points >= good_points
        ):
            recs.append("BUY")

        elif r.transfer_score >= t60:
            recs.append("WATCH")

        else:
            recs.append("AVOID")

    df["recommendation"] = recs

    return df


# ============================================================
# STARTING XI
# ============================================================

def starting_xi(squad):
    """
    Find the best legal starting XI.

    Uses expected GW points as the main driver and gives a tiny
    preference to minutes reliability.
    """

    gk = [
        x for x in squad
        if x["position"] == "GKP"
    ]

    defs = [
        x for x in squad
        if x["position"] == "DEF"
    ]

    mids = [
        x for x in squad
        if x["position"] == "MID"
    ]

    fwds = [
        x for x in squad
        if x["position"] == "FWD"
    ]

    if not gk:
        return [], 0.0

    def xi_weight(x):
        return (
            x["expected_gw_points"]
            + 0.12 * x.get(
                "minutes_probability",
                0.7,
            )
        )

    best = None

    formations = [
        (3, 4, 3),
        (3, 5, 2),
        (4, 3, 3),
        (4, 4, 2),
        (4, 5, 1),
        (5, 2, 3),
        (5, 3, 2),
        (5, 4, 1),
    ]

    for nd, nm, nf in formations:

        if len(defs) < nd:
            continue

        if len(mids) < nm:
            continue

        if len(fwds) < nf:
            continue

        xi = (
            sorted(
                gk,
                key=xi_weight,
                reverse=True,
            )[:1]

            + sorted(
                defs,
                key=xi_weight,
                reverse=True,
            )[:nd]

            + sorted(
                mids,
                key=xi_weight,
                reverse=True,
            )[:nm]

            + sorted(
                fwds,
                key=xi_weight,
                reverse=True,
            )[:nf]
        )

        pts = sum(
            x["expected_gw_points"]
            for x in xi
        )

        if (
            best is None
            or pts > best[1]
        ):
            best = (
                xi,
                pts,
            )

    return (
        best
        if best
        else ([], 0.0)
    )


# ============================================================
# SQUAD OBJECTIVE
# ============================================================

def squad_objective(squad):
    xi, xi_pts = starting_xi(squad)

    if len(xi) != 11:
        return -1e9, xi, []

    xi_ids = {
        x["id"]
        for x in xi
    }

    bench = [
        x for x in squad
        if x["id"] not in xi_ids
    ]

    bench = sorted(
        bench,
        key=lambda x: (
            x["expected_gw_points"],
            x.get("minutes_probability", 0),
        ),
        reverse=True,
    )

    # Bench matters, but substantially less than XI.
    bench_cover = (
        sum(
            x["expected_gw_points"]
            for x in bench
        )
        * 0.18
    )

    minutes_cover = (
        sum(
            clamp(
                x["expected_minutes"] / 90.0,
                0.0,
                1.0,
            )
            for x in bench
        )
        * 0.05
    )

    objective = (
        xi_pts
        + bench_cover
        + minutes_cover
    )

    return (
        objective,
        xi,
        bench,
    )


# ============================================================
# SQUAD OPTIMIZER
# ============================================================

def select_squad(
    df,
    budget=100.0,
    locked_ids=None,
):
    """
    Find an optimal 15-man FPL squad.

    New in V1.8:
        locked_ids
            Optional iterable of player IDs that must be included.

    Existing callers can still use:
        select_squad(df, 100.0)

    This keeps backwards compatibility with streamlit_app.py.
    """

    locked_ids = set(
        locked_ids or []
    )

    positions = [
        "GKP",
        "DEF",
        "MID",
        "FWD",
    ]

    needs = {
        "GKP": 2,
        "DEF": 5,
        "MID": 5,
        "FWD": 3,
    }

    # --------------------------------------------------------
    # Validate locked players
    # --------------------------------------------------------

    if locked_ids:

        existing_ids = set(
            df["id"].tolist()
        )

        missing_ids = (
            locked_ids
            - existing_ids
        )

        if missing_ids:
            return None

        locked_df = df[
            df["id"].isin(
                locked_ids
            )
        ].copy()

        # Maximum squad size.
        if len(locked_df) > 15:
            return None

        # Position limits.
        for pos in positions:
            count = len(
                locked_df[
                    locked_df.position == pos
                ]
            )

            if count > needs[pos]:
                return None

        # Maximum three players per club.
        club_counts = (
            locked_df
            .groupby("team_id")
            .size()
            .to_dict()
        )

        if (
            club_counts
            and max(club_counts.values()) > 3
        ):
            return None

        locked_cost = locked_df.price.sum()

        if locked_cost > budget:
            return None

    else:
        locked_df = df.iloc[0:0].copy()
        locked_cost = 0.0

    # --------------------------------------------------------
    # Candidate pools
    # --------------------------------------------------------

    pools = {}

    for pos in positions:

        g = df[
            df.position == pos
        ].copy()

        # Keep more candidates than V1.7.
        # This reduces the risk of excluding a good player.
        candidates = pd.concat(
            [
                g.nlargest(
                    70,
                    "expected_gw_points",
                ),
                g.nlargest(
                    60,
                    "value_score",
                ),
                g.nlargest(
                    50,
                    "transfer_score",
                ),
                g.nlargest(
                    40,
                    "fixture_next3",
                ),
            ]
        ).drop_duplicates(
            "id"
        )

        pools[pos] = (
            candidates
            .to_dict("records")
        )

    # --------------------------------------------------------
    # Helper functions
    # --------------------------------------------------------

    def valid_team_counts(chosen):
        counts = {}

        for x in chosen:
            tid = x["team_id"]

            counts[tid] = (
                counts.get(tid, 0)
                + 1
            )

        return (
            max(counts.values())
            if counts
            else 0
        )

    def is_valid(chosen):
        if len(chosen) != 15:
            return False

        if (
            sum(
                x["price"]
                for x in chosen
            )
            > budget + 1e-9
        ):
            return False

        for pos in positions:

            if (
                len(
                    [
                        x
                        for x in chosen
                        if x["position"] == pos
                    ]
                )
                != needs[pos]
            ):
                return False

        if valid_team_counts(chosen) > 3:
            return False

        return True

    # --------------------------------------------------------
    # Build seed
    # --------------------------------------------------------

    def make_seed(mode):
        chosen = list(
            locked_df.to_dict(
                "records"
            )
        )

        chosen_ids = {
            x["id"]
            for x in chosen
        }

        cost = sum(
            x["price"]
            for x in chosen
        )

        clubs = {}

        for x in chosen:
            clubs[x["team_id"]] = (
                clubs.get(
                    x["team_id"],
                    0,
                )
                + 1
            )

        for pos in positions:

            need = (
                needs[pos]
                - len(
                    [
                        x
                        for x in chosen
                        if x["position"] == pos
                    ]
                )
            )

            if need <= 0:
                continue

            candidates = [
                x
                for x in pools[pos]
                if x["id"] not in chosen_ids
            ]

            if mode == 0:
                candidates = sorted(
                    candidates,
                    key=lambda x:
                        x["expected_gw_points"],
                    reverse=True,
                )

            elif mode == 1:
                candidates = sorted(
                    candidates,
                    key=lambda x:
                        x["value_score"],
                    reverse=True,
                )

            elif mode == 2:
                candidates = sorted(
                    candidates,
                    key=lambda x:
                        x["fixture_next3"],
                    reverse=True,
                )

            elif mode == 3:
                candidates = sorted(
                    candidates,
                    key=lambda x:
                        x["transfer_score"],
                    reverse=True,
                )

            else:
                candidates = sorted(
                    candidates,
                    key=lambda x:
                        (
                            x["expected_gw_points"]
                            + 0.45 * x["value"]
                            + 0.25 * x["fixture_next3"]
                        ),
                    reverse=True,
                )

            for x in candidates:

                if need <= 0:
                    break

                if (
                    clubs.get(
                        x["team_id"],
                        0,
                    )
                    >= 3
                ):
                    continue

                if (
                    cost
                    + x["price"]
                    > budget + 1e-9
                ):
                    continue

                chosen.append(x)
                chosen_ids.add(x["id"])

                cost += x["price"]

                clubs[x["team_id"]] = (
                    clubs.get(
                        x["team_id"],
                        0,
                    )
                    + 1
                )

                need -= 1

        # ----------------------------------------------------
        # Repair missing slots
        # ----------------------------------------------------

        while len(chosen) < 15:

            missing = next(
                (
                    p
                    for p in positions
                    if len(
                        [
                            z
                            for z in chosen
                            if z["position"] == p
                        ]
                    )
                    < needs[p]
                ),
                None,
            )

            if missing is None:
                break

            cand = sorted(
                pools[missing],
                key=lambda x:
                    (
                        x["price"],
                        -x["expected_gw_points"],
                    ),
            )

            added = False

            for x in cand:

                if x["id"] in chosen_ids:
                    continue

                if (
                    clubs.get(
                        x["team_id"],
                        0,
                    )
                    >= 3
                ):
                    continue

                if (
                    cost
                    + x["price"]
                    > budget + 1e-9
                ):
                    continue

                chosen.append(x)
                chosen_ids.add(x["id"])

                cost += x["price"]

                clubs[x["team_id"]] = (
                    clubs.get(
                        x["team_id"],
                        0,
                    )
                    + 1
                )

                added = True
                break

            if not added:
                return None

        if not is_valid(chosen):
            return None

        return chosen

    # --------------------------------------------------------
    # Local improvement
    # --------------------------------------------------------

    def improve(chosen):
        cost = sum(
            x["price"]
            for x in chosen
        )

        best_obj = squad_objective(
            chosen
        )[0]

        locked = set(
            locked_ids
        )

        improved = True
        loops = 0

        while (
            improved
            and loops < 100
        ):
            improved = False
            loops += 1

            current_ids = {
                x["id"]
                for x in chosen
            }

            for i, old in enumerate(
                list(chosen)
            ):

                # Locked players are never replaced.
                if old["id"] in locked:
                    continue

                pos = old["position"]

                candidates = sorted(
                    pools[pos],
                    key=lambda x:
                        (
                            x["expected_gw_points"]
                            + 0.30 * x["value"]
                            + 0.20 * x["fixture_next3"]
                        ),
                    reverse=True,
                )[:45]

                for new in candidates:

                    if (
                        new["id"]
                        in current_ids
                    ):
                        continue

                    new_cost = (
                        cost
                        - old["price"]
                        + new["price"]
                    )

                    if (
                        new_cost
                        > budget + 1e-9
                    ):
                        continue

                    trial = chosen.copy()
                    trial[i] = new

                    # Position count is preserved because replacement
                    # happens inside the same position.
                    club_counts = {}

                    for z in trial:
                        club_counts[
                            z["team_id"]
                        ] = (
                            club_counts.get(
                                z["team_id"],
                                0,
                            )
                            + 1
                        )

                    if (
                        max(
                            club_counts.values()
                        )
                        > 3
                    ):
                        continue

                    obj = squad_objective(
                        trial
                    )[0]

                    if (
                        obj
                        > best_obj + 1e-7
                    ):
                        chosen = trial
                        current_ids = {
                            x["id"]
                            for x in chosen
                        }

                        cost = new_cost
                        best_obj = obj

                        improved = True
                        break

                if improved:
                    break

        return chosen

    # --------------------------------------------------------
    # Search multiple seeds
    # --------------------------------------------------------

    best = None

    for mode in range(5):

        seed = make_seed(mode)

        if seed is None:
            continue

        seed = improve(seed)

        obj, xi, bench = (
            squad_objective(seed)
        )

        cost = sum(
            x["price"]
            for x in seed
        )

        if (
            cost <= budget + 1e-9
            and (
                best is None
                or obj > best[0]
            )
        ):
            best = (
                obj,
                cost,
                seed,
                xi,
                bench,
            )

    return best


# ============================================================
# BUILD A SQUAD AROUND USER'S PLAYERS
# ============================================================

def build_around_players(
    df,
    selected_player_ids,
    budget=100.0,
):
    """
    User-facing helper for the future Streamlit UI.

    Example:
        build_around_players(
            df,
            [355, 430, 123],
            100.0,
        )

    The selected players become locked and the optimizer fills
    the remaining squad automatically.
    """

    selected_player_ids = list(
        dict.fromkeys(
            selected_player_ids or []
        )
    )

    if not selected_player_ids:
        return select_squad(
            df,
            budget,
        )

    return select_squad(
        df,
        budget,
        locked_ids=selected_player_ids,
    )


# ============================================================
# OUTPUTS
# ============================================================

def save_outputs(
    df,
    squad_result,
    outdir,
):
    outdir.mkdir(
        parents=True,
        exist_ok=True,
    )

    df.sort_values(
        "transfer_score",
        ascending=False,
    ).to_csv(
        outdir / "players_v18.csv",
        index=False,
    )

    output_specs = [
        (
            "top_transfers_v18.csv",
            "transfer_score",
            None,
        ),
        (
            "top_captains_v18.csv",
            "captain_score",
            None,
        ),
        (
            "top_differentials_v18.csv",
            "differential_score",
            df.ownership <= 10,
        ),
        (
            "top_value_v18.csv",
            "value_score",
            None,
        ),
    ]

    for name, col, filt in output_specs:

        x = (
            df
            if filt is None
            else df[filt]
        )

        x.sort_values(
            col,
            ascending=False,
        ).head(25).to_csv(
            outdir / name,
            index=False,
        )

    if squad_result:

        _, cost, squad, xi, bench = (
            squad_result
        )

        pd.DataFrame(
            squad
        ).sort_values(
            [
                "position",
                "expected_gw_points",
            ],
            ascending=[
                True,
                False,
            ],
        ).to_csv(
            outdir / "best_squad_v18.csv",
            index=False,
        )

        pd.DataFrame(
            xi
        ).to_csv(
            outdir / "starting_xi_v18.csv",
            index=False,
        )

        pd.DataFrame(
            bench
        ).to_csv(
            outdir / "bench_v18.csv",
            index=False,
        )

        return cost, squad

    return None, []


def print_table(
    title,
    df,
    cols,
    n=20,
):
    print(
        "\n"
        + "=" * 100
    )

    print(title)

    print(
        "=" * 100
    )

    print(
        df[cols]
        .head(n)
        .to_string(
            index=False
        )
    )


# ============================================================
# SANITY CHECKS
# ============================================================

def run_sanity_checks(df):
    print("\nSANITY CHECK")

    print(
        "  Players:",
        len(df),
    )

    print(
        "  Expected GW points:",
        round(
            df.expected_gw_points.min(),
            2,
        ),
        "-",
        round(
            df.expected_gw_points.max(),
            2,
        ),
    )

    print(
        "  Expected minutes:",
        round(
            df.expected_minutes.min(),
            1,
        ),
        "-",
        round(
            df.expected_minutes.max(),
            1,
        ),
    )

    print(
        "  Fixed-minute bug:",
        (
            "PASS"
            if df.expected_minutes.nunique() > 5
            else "FAIL"
        ),
    )

    print(
        "  Extreme GW projection:",
        (
            "PASS"
            if df.expected_gw_points.max() <= 11
            else "CHECK"
        ),
    )

    print(
        "  xG/xA fields available:",
        (
            "YES"
            if (
                df.xg90.sum()
                + df.xa90.sum()
            ) > 0
            else "NO / FALLBACK"
        ),
    )

    captain_attack = df[
        df.position.isin(
            ["MID", "FWD"]
        )
    ].captain_score

    captain_def = df[
        df.position.isin(
            ["GKP", "DEF"]
        )
    ].captain_score

    if (
        len(captain_attack)
        and len(captain_def)
    ):
        print(
            "  Captain model:",
            (
                "PASS"
                if captain_attack.max()
                >= captain_def.max() * 0.90
                else "CHECK"
            ),
        )


# ============================================================
# MAIN
# ============================================================

def main():
    started = time.time()

    print(
        "FPL ANALYZER V1.8 – SMART FPL DECISION ENGINE"
    )

    print(
        "Live data + expected points + fixtures + "
        "captain model + squad optimizer + build-around support."
    )

    print(
        "Python:",
        __import__("sys").version.split(".")[0:2],
    )

    # --------------------------------------------------------
    # Load
    # --------------------------------------------------------

    data, teams, raw_players = load_fpl()
    fixtures = load_fixtures()

    print(
        "Live spillere:",
        len(raw_players),
    )

    # --------------------------------------------------------
    # Build model
    # --------------------------------------------------------

    df = build_players(
        raw_players,
        teams,
        fixtures,
    )

    df = assign_recommendations(
        df
    )

    run_sanity_checks(df)

    # --------------------------------------------------------
    # Transfers
    # --------------------------------------------------------

    transfer_cols = [
        "name",
        "team_name",
        "position",
        "price",
        "ownership",
        "expected_minutes",
        "expected_gw_points",
        "xg90",
        "xa90",
        "fixture_next3",
        "value",
        "transfer_score",
        "recommendation",
    ]

    print_table(
        "V1.8 TOP TRANSFERVALG",
        df.sort_values(
            "transfer_score",
            ascending=False,
        ),
        transfer_cols,
        20,
    )

    # --------------------------------------------------------
    # Captains
    # --------------------------------------------------------

    captain_cols = [
        "name",
        "team_name",
        "position",
        "price",
        "expected_minutes",
        "expected_gw_points",
        "xg90",
        "xa90",
        "fixture_next3",
        "captain_score",
    ]

    captain_pool = (
        df[
            df.expected_minutes >= 60
        ]
        .sort_values(
            [
                "captain_score",
                "expected_gw_points",
            ],
            ascending=False,
        )
    )

    print_table(
        "V1.8 TOPP KAPTEINER",
        captain_pool,
        captain_cols,
        10,
    )

    # --------------------------------------------------------
    # Differentials
    # --------------------------------------------------------

    diff_cols = [
        "name",
        "team_name",
        "position",
        "price",
        "ownership",
        "expected_minutes",
        "expected_gw_points",
        "xg90",
        "xa90",
        "fixture_next3",
        "differential_score",
    ]

    print_table(
        "V1.8 TOPP DIFFERENTIALS (<=10% OWNERSHIP)",
        df[
            df.ownership <= 10
        ].sort_values(
            "differential_score",
            ascending=False,
        ),
        diff_cols,
        20,
    )

    # --------------------------------------------------------
    # Value
    # --------------------------------------------------------

    print_table(
        "V1.8 BEST VALUE",
        df.sort_values(
            "value_score",
            ascending=False,
        ),
        transfer_cols,
        15,
    )

    # --------------------------------------------------------
    # Best squad
    # --------------------------------------------------------

    print(
        "\n"
        + "=" * 100
    )

    print(
        "BEST 15-MAN SQUAD "
        "(<= £100m, valid FPL structure)"
    )

    print(
        "=" * 100
    )

    result = select_squad(
        df,
        100.0,
    )

    if result:

        score, cost, squad, xi, bench = (
            result
        )

        print(
            f"Total cost: £{cost:.1f}m"
        )

        print(
            f"Squad objective: {score:.2f}"
        )

        print(
            "STARTING XI:"
        )

        print(
            pd.DataFrame(xi)[
                [
                    "name",
                    "team_name",
                    "position",
                    "price",
                    "expected_gw_points",
                ]
            ].to_string(
                index=False
            )
        )

        print(
            "\nBENCH:"
        )

        print(
            pd.DataFrame(bench)[
                [
                    "name",
                    "team_name",
                    "position",
                    "price",
                    "expected_gw_points",
                ]
            ].to_string(
                index=False
            )
        )

        captain = max(
            xi,
            key=lambda x:
                x["captain_score"],
        )

        vice_pool = [
            x
            for x in xi
            if x["id"]
            != captain["id"]
        ]

        vice = max(
            vice_pool,
            key=lambda x:
                x["captain_score"],
        )

        print(
            f"\nCAPTAIN: "
            f"{captain['name']} "
            f"({captain['position']})"
        )

        print(
            f"VICE-CAPTAIN: "
            f"{vice['name']} "
            f"({vice['position']})"
        )

    else:
        print(
            "Ingen gyldig tropp funnet."
        )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    outdir = (
        Path(__file__).resolve().parent
        / "data"
    )

    save_outputs(
        df,
        result,
        outdir,
    )

    print(
        "\n"
        + "=" * 100
    )

    print(
        "V1.8 FERDIG"
    )

    print(
        "Data lagret i:",
        outdir,
    )

    print(
        "Tid brukt:",
        round(
            time.time() - started,
            1,
        ),
        "sekunder",
    )

    print(
        "=" * 100
    )


if __name__ == "__main__":
    main()
