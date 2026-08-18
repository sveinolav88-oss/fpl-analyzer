import streamlit as st
import pandas as pd

from main_v1_9_positional import load_fpl, load_fixtures, build_players, assign_recommendations, run_position_tests, select_squad

st.set_page_config(page_title="FPL Analyzer – V1.9 Test", layout="wide")
st.title("🧪 FPL Analyzer – V1.9 Test")
st.caption("Live test of the position-aware V1.9 model. This page does not modify the main app.")

if st.button("▶️ Kjør V1.9-test", type="primary"):
    with st.spinner("Henter live FPL-data og kjører modellen..."):
        data, teams, raw_players = load_fpl()
        fixtures = load_fixtures()
        df = assign_recommendations(build_players(raw_players, teams, fixtures))

    st.success(f"Test ferdig – {len(df)} spillere analysert.")

    st.subheader("🏆 Topp 10 per posisjon")
    results = run_position_tests(df)
    tabs = st.tabs(["GKP", "DEF", "MID", "FWD"])
    for tab, pos in zip(tabs, ["GKP", "DEF", "MID", "FWD"]):
        with tab:
            st.dataframe(results[pos], use_container_width=True, hide_index=True)

    st.subheader("🎯 Topp 10 captain-kandidater")
    captains = (
        df[df["expected_minutes"] >= 60]
        .sort_values(["captain_score", "expected_gw_points"], ascending=False)
        .head(10)
    )
    st.dataframe(
        captains[["name", "team_name", "position", "price", "expected_minutes", "expected_gw_points", "fixture_next1", "captain_score"]],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("🏅 Beste 15-mannslag")
    result = select_squad(df, 100.0)
    if result:
        objective, cost, squad, xi, bench = result
        st.write(f"**Kostnad:** £{cost:.1f}m  |  **Modellscore:** {objective:.2f}")
        squad_df = pd.DataFrame(squad)
        st.dataframe(
            squad_df[["name", "team_name", "position", "price", "expected_minutes", "expected_gw_points", "transfer_score"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.error("Modellen fant ikke et gyldig £100m-lag.")

    st.subheader("💎 Beste differentials")
    diffs = (
        df[df["ownership"] <= 10]
        .sort_values("differential_score", ascending=False)
        .head(15)
    )
    st.dataframe(
        diffs[["name", "team_name", "position", "price", "ownership", "expected_gw_points", "xgi90", "differential_score"]],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("Trykk på **Kjør V1.9-test** for å hente live data og kjøre analysen.")
