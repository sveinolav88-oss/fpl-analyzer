"""V1.9 positional scoring test layer.

Keeps the V1.9 core model unchanged, but normalizes ranking components
within each FPL position so GKP/DEF/MID/FWD are compared against realistic
peers. This is a test layer; it does not replace main.py.
"""

import pandas as pd

from main_v1_9 import *  # noqa: F401,F403
from main_v1_9 import build_players as _build_players_v19

MODEL_VERSION = "V1.9-POS"


def _pct(series):
    if len(series) <= 1:
        return pd.Series([50.0] * len(series), index=series.index)
    return series.rank(pct=True, method="average") * 100.0


def build_players(raw, teams, fixtures):
    df = _build_players_v19(raw, teams, fixtures).copy()
    if df.empty:
        return df

    # Rebuild the ranking components within each position. This prevents a
    # strong midfielder from making a goalkeeper look artificially weak, and
    # makes "top 10" meaningful when the UI is filtered by position.
    groups = df.groupby("position", group_keys=False)

    for col, source in [
        ("points_pct", "expected_gw_points"),
        ("value_pct", "value"),
        ("fixture_pct", "fixture_next3"),
        ("minutes_pct", "minutes_probability"),
        ("xgi_pct", "xgi90"),
        ("form_pct", "form"),
    ]:
        df[col] = groups[source].transform(_pct)

    # Ownership is still globally comparable, but its impact remains capped.
    df["differential_pct"] = ((15.0 - df["ownership"]) / 15.0).clip(0.0, 1.0) * 100.0

    # Transfer score, position-aware.
    df["transfer_score"] = (
        0.35 * df["points_pct"]
        + 0.22 * df["value_pct"]
        + 0.15 * df["fixture_pct"]
        + 0.12 * df["minutes_pct"]
        + 0.08 * df["form_pct"]
        + 0.05 * df["xgi_pct"]
        + 0.03 * df["differential_pct"]
    )

    # Captain score uses the next fixture, also normalized among positional peers.
    next1_pct = groups["fixture_next1"].transform(_pct)
    df["captain_score"] = (
        0.62 * df["points_pct"]
        + 0.14 * df["minutes_pct"]
        + 0.10 * next1_pct
        + 0.09 * df["xgi_pct"]
        + 0.05 * df["form_pct"]
    )
    df.loc[df["position"].isin(["GKP", "DEF"]), "captain_score"] *= 0.94

    df["differential_score"] = (
        0.40 * df["points_pct"]
        + 0.20 * df["value_pct"]
        + 0.15 * df["xgi_pct"]
        + 0.10 * df["fixture_pct"]
        + 0.10 * df["minutes_pct"]
        + 0.05 * df["differential_pct"]
    )

    df["value_score"] = (
        0.55 * df["value_pct"]
        + 0.25 * df["points_pct"]
        + 0.10 * df["minutes_pct"]
        + 0.10 * df["fixture_pct"]
    )

    for col in ["transfer_score", "captain_score", "differential_score", "value_score"]:
        df[col] = df[col].round(2)

    return df


def run_position_tests(df):
    """Return the top 10 transfer candidates for every FPL position."""
    results = {}
    for pos in ["GKP", "DEF", "MID", "FWD"]:
        cols = [
            "name", "team_name", "position", "price", "expected_minutes",
            "expected_gw_points", "value", "fixture_next3", "xgi90",
            "transfer_score", "recommendation",
        ]
        results[pos] = (
            df[df["position"] == pos]
            .sort_values(["transfer_score", "expected_gw_points"], ascending=False)
            .head(10)[cols]
            .reset_index(drop=True)
        )
    return results


if __name__ == "__main__":
    data, teams, raw_players = load_fpl()
    fixtures = load_fixtures()
    df = assign_recommendations(build_players(raw_players, teams, fixtures))
    tests = run_position_tests(df)

    print(f"FPL ANALYZER {MODEL_VERSION}")
    for pos, table in tests.items():
        print("\n" + "=" * 110)
        print(f"TOP 10 {pos} – POSITION-AWARE TRANSFER SCORE")
        print("=" * 110)
        print(table.to_string(index=False))

    print("\nTOP 10 OVERALL CAPTAIN CANDIDATES")
    print(
        df[df["expected_minutes"] >= 60]
        .sort_values(["captain_score", "expected_gw_points"], ascending=False)
        .head(10)[["name", "team_name", "position", "expected_minutes", "expected_gw_points", "fixture_next1", "captain_score"]]
        .to_string(index=False)
    )
