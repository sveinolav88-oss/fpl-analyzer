import streamlit as st
import pandas as pd
import time

from main import (
load_fpl,
load_fixtures,
build_players,
assign_recommendations,
select_squad,
)

#---------------------------------------------------------
#PAGE CONFIG
#---------------------------------------------------------

st.set_page_config(
page_title="FPL Analyzer",
page_icon="⚽",
layout="wide",
initial_sidebar_state="expanded",
)

#---------------------------------------------------------

#CUSTOM CSS

#---------------------------------------------------------

st.markdown(
"""
<style>

.main {
    padding-top: 1rem;
}

.block-container {
    max-width: 1450px;
    padding-top: 2rem;
}

.hero {
    padding: 1.5rem 1.8rem;
    border-radius: 18px;
    background: linear-gradient(135deg, #111827, #1f2937);
    color: white;
    margin-bottom: 1.5rem;
}

.hero h1 {
    margin-bottom: 0.2rem;
    font-size: 2.4rem;
}

.hero p {
    margin: 0;
    opacity: 0.75;
    font-size: 1rem;
}

.card {
    padding: 1rem;
    border-radius: 14px;
    border: 1px solid rgba(128,128,128,0.25);
    background: rgba(128,128,128,0.05);
}

.player-name {
    font-weight: 700;
    font-size: 1.05rem;
}

.small-muted {
    opacity: 0.65;
    font-size: 0.85rem;
}

</style>
""",
unsafe_allow_html=True,

)

#---------------------------------------------------------
#HEADER
#---------------------------------------------------------

st.markdown(
"""
<div class="hero">
<h1>⚽ FPL Analyzer</h1>
<p>Live Fantasy Premier League analysis • Transfers • Captains • Differentials • Best XI</p>
</div>
""",
unsafe_allow_html=True,
)

#---------------------------------------------------------

#LOAD DATA

#---------------------------------------------------------

@st.cache_data(ttl=900)
def get_analysis():
    data, teams, raw_players = load_fpl()
    fixtures = load_fixtures()

    df = build_players(raw_players, teams, fixtures)
    df = assign_recommendations(df)

    return df, teams


with st.spinner("Henter ferske FPL-data..."):
    try:
        df, teams = get_analysis()
        data_loaded = True
    except Exception as e:
        data_loaded = False
        st.error(f"Kunne ikke hente FPL-data: {e}")

#---------------------------------------------------------

#SIDEBAR

#---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Innstillinger")

    budget = st.number_input(
        "Budsjett (€m)",
        min_value=80.0,
        max_value=100.0,
        value=100.0,
        step=0.5,
    )

    ownership_limit = st.slider(
        "Differential maks. eierskap (%)",
        min_value=1,
        max_value=20,
        value=10,
    )


st.divider()

if st.button("🔄 Oppdater FPL-data", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.divider()

st.caption("FPL Analyzer")
st.caption("Live data fra Fantasy Premier League API")

if not data_loaded:
    st.stop()

#---------------------------------------------------------

#TOP METRICS

#---------------------------------------------------------

players_count = len(df)
avg_points = df["expected_gw_points"].mean()
top_player = df.sort_values("expected_gw_points", ascending=False).iloc[0]

c1, c2, c3, c4 = st.columns(4)

with c1:
st.metric(
"Spillere analysert",
f"{players_count}",
)

with c2:
st.metric(
"Snitt forventede poeng",
f"{avg_points:.2f}",
)

with c3:
st.metric(
"Beste projeksjon",
f"{top_player['name']}",
)

with c4:
st.metric(
"Forventede poeng",
f"{top_player['expected_gw_points']:.2f}",
)

#---------------------------------------------------------

#TABS

#---------------------------------------------------------

tab1, tab2, tab3, tab4, tab5 = st.tabs(
[
"🏆 Beste lag",
"🔄 Transfers",
"©️ Kapteiner",
"🔥 Differentials",
"💰 Best value",
]
)

#=========================================================

#BEST SQUAD

#=========================================================

with tab1:

st.header("🏆 Beste 15-mannstropp")

with st.spinner("Optimaliserer troppen..."):
    result = select_squad(df, budget)

if result:

    score, cost, squad, xi, bench = result

    m1, m2, m3 = st.columns(3)

    with m1:
        st.metric("Troppskostnad", f"£{cost:.1f}m")

    with m2:
        st.metric("Budsjett igjen", f"£{budget - cost:.1f}m")

    with m3:
        st.metric("Forventede XI-poeng", f"{sum(x['expected_gw_points'] for x in xi):.1f}")

    st.subheader("Starting XI")

    xi_df = pd.DataFrame(xi)

    # Captain
    cap = max(xi, key=lambda x: x["captain_score"])

    vice_candidates = [
        x for x in xi
        if x["id"] != cap["id"]
    ]

    vice = max(
        vice_candidates,
        key=lambda x: x["captain_score"]
    )

    # Captain cards
    c1, c2 = st.columns(2)

    with c1:
        st.markdown(
            f"""
            <div class="card">
                <div class="small-muted">© KAPTEIN</div>
                <div class="player-name">
                    {cap['name']} ({cap['position']})
                </div>
                <div>
                    Forventet: {cap['expected_gw_points']:.2f} poeng
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown(
            f"""
            <div class="card">
                <div class="small-muted">VICE-CAPTAIN</div>
                <div class="player-name">
                    {vice['name']} ({vice['position']})
                </div>
                <div>
                    Forventet: {vice['expected_gw_points']:.2f} poeng
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("Starting XI")

    show_cols = [
        "name",
        "team_name",
        "position",
        "price",
        "expected_minutes",
        "expected_gw_points",
        "captain_score",
    ]

    st.dataframe(
        xi_df[show_cols],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Bench")

    bench_df = pd.DataFrame(bench)

    st.dataframe(
        bench_df[
            [
                "name",
                "team_name",
                "position",
                "price",
                "expected_minutes",
                "expected_gw_points",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

else:
    st.error("Fant ingen gyldig FPL-tropp.")

#=========================================================

#TRANSFERS

#=========================================================

with tab2:

st.header("🔄 Beste transfermål")

position_filter = st.multiselect(
    "Posisjon",
    ["GKP", "DEF", "MID", "FWD"],
    default=["GKP", "DEF", "MID", "FWD"],
)

transfer_df = df[
    df["position"].isin(position_filter)
].copy()

transfer_df = transfer_df.sort_values(
    "transfer_score",
    ascending=False,
).head(30)

st.dataframe(
    transfer_df[
        [
            "name",
            "team_name",
            "position",
            "price",
            "ownership",
            "expected_minutes",
            "expected_gw_points",
            "value",
            "fixture_next3",
            "transfer_score",
            "recommendation",
        ]
    ],
    use_container_width=True,
    hide_index=True,
)

#=========================================================

#CAPTAINS

#=========================================================

with tab3:

st.header("©️ Kapteinguide")

st.info(
    "Kapteinmodellen prioriterer forventede poeng, spilletid, "
    "posisjon og fixture. Eierskap og pris påvirker ikke kapteinvalget."
)

captain_df = df[
    df["expected_minutes"] >= 60
].copy()

captain_df = captain_df.sort_values(
    ["captain_score", "expected_gw_points"],
    ascending=False,
).head(20)

st.dataframe(
    captain_df[
        [
            "name",
            "team_name",
            "position",
            "price",
            "expected_minutes",
            "expected_gw_points",
            "fixture_next3",
            "captain_score",
        ]
    ],
    use_container_width=True,
    hide_index=True,
)

#=========================================================

#DIFFERENTIALS

#=========================================================

with tab4:

st.header("🔥 Differentials")

differential_df = df[
    (df["ownership"] <= ownership_limit)
    & (df["expected_minutes"] >= 60)
].copy()

differential_df = differential_df.sort_values(
    "differential_score",
    ascending=False,
).head(30)

st.dataframe(
    differential_df[
        [
            "name",
            "team_name",
            "position",
            "price",
            "ownership",
            "expected_minutes",
            "expected_gw_points",
            "value",
            "fixture_next3",
            "differential_score",
        ]
    ],
    use_container_width=True,
    hide_index=True,
)

#=========================================================

#BEST VALUE

#=========================================================

with tab5:

st.header("💰 Best value")

value_df = df[
    df["expected_minutes"] >= 60
].copy()

value_df = value_df.sort_values(
    "value",
    ascending=False,
).head(30)

st.dataframe(
    value_df[
        [
            "name",
            "team_name",
            "position",
            "price",
            "expected_minutes",
            "expected_gw_points",
            "value",
            "fixture_next3",
        ]
    ],
    use_container_width=True,
    hide_index=True,
)

#---------------------------------------------------------

#FOOTER

#---------------------------------------------------------

st.divider()

st.caption(
"FPL Analyzer • Live FPL data • Analysis model V1.7"
)
