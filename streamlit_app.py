import streamlit as st
import pandas as pd

from main import (
    load_fpl,
    load_fixtures,
    build_players,
    assign_recommendations,
    select_squad,
    build_around_players,
)

# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="FPL Analyzer",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# STYLE
# =========================================================

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1500px;
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }

    .hero {
        padding: 1.8rem 2rem;
        border-radius: 20px;
        background: linear-gradient(135deg, #111827, #1f2937);
        color: white;
        margin-bottom: 1.4rem;
        border: 1px solid rgba(255,255,255,0.08);
    }

    .hero h1 {
        margin: 0;
        font-size: 2.5rem;
        line-height: 1.1;
    }

    .hero p {
        margin: .5rem 0 0;
        opacity: .75;
        font-size: 1rem;
    }

    .section-card {
        padding: 1rem 1.2rem;
        border-radius: 16px;
        border: 1px solid rgba(128,128,128,.22);
        background: rgba(128,128,128,.04);
        margin-bottom: 1rem;
    }

    .player-name {
        font-weight: 750;
        font-size: 1.1rem;
    }

    .muted {
        opacity: .68;
        font-size: .86rem;
    }

    .recommend-buy {
        font-weight: 800;
    }

    div[data-testid="stMetric"] {
        padding: .55rem .2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# HEADER
# =========================================================

st.markdown(
    """
    <div class="hero">
        <h1>⚽ FPL Analyzer</h1>
        <p>
            Live Fantasy Premier League analysis · Optimal squad · Transfers ·
            Captains · Differentials · Value
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# DATA
# =========================================================

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
    except Exception as exc:
        data_loaded = False
        st.error(f"Kunne ikke hente FPL-data: {exc}")


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:
    st.header("⚙️ Innstillinger")

    budget = st.number_input(
        "Budsjett (£m)",
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
    st.caption("Data cache: 15 minutter")


if not data_loaded:
    st.stop()

# =========================================================
# TOP METRICS
# =========================================================

players_count = len(df)
avg_points = float(df["expected_gw_points"].mean())
top_player = df.sort_values("expected_gw_points", ascending=False).iloc[0]

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.metric("Spillere analysert", f"{players_count}")

with c2:
    st.metric("Snitt forventede poeng", f"{avg_points:.2f}")

with c3:
    st.metric("Beste projeksjon", str(top_player["name"]))

with c4:
    st.metric("Forventede poeng", f"{top_player['expected_gw_points']:.2f}")

# =========================================================
# TABS
# =========================================================

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    [
        "🏆 Beste lag",
        "🔄 Transfers",
        "©️ Kapteiner",
        "🔥 Differentials",
        "💰 Best value",
        "🧩 Bygg rundt mine spillere",
    ]
)

# =========================================================
# BEST SQUAD
# =========================================================

with tab1:
    st.header("🏆 Beste 15-mannstropp")
    st.caption(
        "Optimaliseres innenfor budsjett, FPL-struktur og klubbbegrensning."
    )

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
            xi_points = sum(float(x["expected_gw_points"]) for x in xi)
            st.metric("Forventede XI-poeng", f"{xi_points:.1f}")

        # Captain selection is deliberately based on captain_score,
        # not transfer score, value or ownership.
        cap = max(xi, key=lambda x: x["captain_score"])
        vice_pool = [x for x in xi if x["id"] != cap["id"]]
        vice = max(vice_pool, key=lambda x: x["captain_score"])

        st.subheader("🎯 Kaptein og visekaptein")

        c1, c2 = st.columns(2)

        with c1:
            st.markdown(
                f"""
                <div class="section-card">
                    <div class="muted">KAPTEIN</div>
                    <div class="player-name">
                        {cap["name"]} · {cap["position"]}
                    </div>
                    <div>
                        Forventet: {cap["expected_gw_points"]:.2f} poeng
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with c2:
            st.markdown(
                f"""
                <div class="section-card">
                    <div class="muted">VICE-CAPTAIN</div>
                    <div class="player-name">
                        {vice["name"]} · {vice["position"]}
                    </div>
                    <div>
                        Forventet: {vice["expected_gw_points"]:.2f} poeng
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.subheader("Starting XI")

        xi_df = pd.DataFrame(xi)
        xi_cols = [
            "name",
            "team_name",
            "position",
            "price",
            "expected_minutes",
            "expected_gw_points",
            "captain_score",
        ]
        xi_cols = [c for c in xi_cols if c in xi_df.columns]

        st.dataframe(
            xi_df[xi_cols],
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Bench")

        bench_df = pd.DataFrame(bench)
        bench_cols = [
            "name",
            "team_name",
            "position",
            "price",
            "expected_minutes",
            "expected_gw_points",
        ]
        bench_cols = [c for c in bench_cols if c in bench_df.columns]

        st.dataframe(
            bench_df[bench_cols],
            use_container_width=True,
            hide_index=True,
        )

        with st.expander("🔎 Vis optimaliseringsdetaljer"):
            st.write(f"Squad objective: **{score:.2f}**")
            st.write("Struktur: **2 GKP / 5 DEF / 5 MID / 3 FWD**")
            st.write("Maksimalt 3 spillere fra samme klubb.")

    else:
        st.error("Fant ingen gyldig FPL-tropp innenfor budsjettet.")

# =========================================================
# TRANSFERS
# =========================================================

with tab2:
    st.header("🔄 Beste transfermål")
    st.caption("Rangert etter modellens transfer-score.")

    positions = ["GKP", "DEF", "MID", "FWD"]

    position_filter = st.multiselect(
        "Posisjon",
        positions,
        default=positions,
    )

    min_minutes = st.slider(
        "Minimum forventede minutter",
        min_value=0,
        max_value=90,
        value=60,
        step=5,
    )

    transfer_df = df[
        df["position"].isin(position_filter)
        & (df["expected_minutes"] >= min_minutes)
    ].copy()

    transfer_df = transfer_df.sort_values(
        ["transfer_score", "expected_gw_points"],
        ascending=False,
    ).head(30)

    transfer_cols = [
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
    transfer_cols = [c for c in transfer_cols if c in transfer_df.columns]

    st.dataframe(
        transfer_df[transfer_cols],
        use_container_width=True,
        hide_index=True,
    )

# =========================================================
# CAPTAINS
# =========================================================

with tab3:
    st.header("©️ Kapteinguide")
    st.caption(
        "Kapteinvalget skal prioritere forventede poeng, spilletid og fixture. "
        "Pris og eierskap brukes ikke som kapteinssignaler."
    )

    captain_df = df[df["expected_minutes"] >= 60].copy()

    captain_df = captain_df.sort_values(
        ["captain_score", "expected_gw_points"],
        ascending=False,
    ).head(20)

    if len(captain_df):
        top_cap = captain_df.iloc[0]
        st.success(
            f"🥇 Førstevalg: **{top_cap['name']}** · "
            f"{top_cap['expected_gw_points']:.2f} forventede poeng"
        )

    captain_cols = [
        "name",
        "team_name",
        "position",
        "price",
        "expected_minutes",
        "expected_gw_points",
        "fixture_next3",
        "captain_score",
    ]
    captain_cols = [c for c in captain_cols if c in captain_df.columns]

    st.dataframe(
        captain_df[captain_cols],
        use_container_width=True,
        hide_index=True,
    )

# =========================================================
# DIFFERENTIALS
# =========================================================

with tab4:
    st.header("🔥 Differentials")
    st.caption(
        "Spillere med lavere eierskap og tilstrekkelig forventet spilletid."
    )

    differential_df = df[
        (df["ownership"] <= ownership_limit)
        & (df["expected_minutes"] >= 60)
    ].copy()

    differential_df = differential_df.sort_values(
        ["differential_score", "expected_gw_points"],
        ascending=False,
    ).head(30)

    differential_cols = [
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
    differential_cols = [
        c for c in differential_cols if c in differential_df.columns
    ]

    st.dataframe(
        differential_df[differential_cols],
        use_container_width=True,
        hide_index=True,
    )

# =========================================================
# VALUE
# =========================================================

with tab5:
    st.header("💰 Best value")
    st.caption("Forventede poeng per £m, slik modellen beregner value.")

    value_df = df[
        df["expected_minutes"] >= 60
    ].sort_values(
        ["value", "expected_gw_points"],
        ascending=False,
    ).head(30)

    value_cols = [
        "name",
        "team_name",
        "position",
        "price",
        "ownership",
        "expected_minutes",
        "expected_gw_points",
        "value",
        "fixture_next3",
    ]
    value_cols = [c for c in value_cols if c in value_df.columns]

    st.dataframe(
        value_df[value_cols],
        use_container_width=True,
        hide_index=True,
    )

# =========================================================
# BUILD AROUND MY PLAYERS
# =========================================================

with tab6:
    st.header("🧩 Bygg laget rundt mine spillere")
    st.caption(
        "Velg spillerne du absolutt vil ha. De låses, og modellen finner "
        "de beste resterende spillerne innenfor budsjett og FPL-reglene."
    )

    # Player IDs are used as the actual widget values. The label contains
    # enough context to make players easy to distinguish while selecting.
    player_lookup = (
        df.set_index("id")
        .to_dict("index")
    )

    player_ids = df["id"].tolist()

    def player_label(player_id):
        p = player_lookup.get(player_id, {})
        return (
            f"{p.get('name', '?')} · "
            f"{p.get('team_name', '?')} · "
            f"{p.get('position', '?')} · "
            f"£{p.get('price', 0):.1f}m"
        )

    selected_ids = st.multiselect(
        "🔒 Velg spillerne du vil bygge laget rundt",
        options=player_ids,
        format_func=player_label,
        key="build_around_players",
        help="Du kan velge hvem du vil. Modellen låser disse spillerne og optimaliserer resten.",
    )

    if selected_ids:
        selected_df = df[df["id"].isin(selected_ids)].copy()
        selected_cost = float(selected_df["price"].sum())
        remaining_budget = budget - selected_cost

        st.markdown("### 🔒 Dine låste spillere")

        selected_cols = [
            "name",
            "team_name",
            "position",
            "price",
            "expected_minutes",
            "expected_gw_points",
            "xgi90",
            "fixture_next3",
        ]
        selected_cols = [c for c in selected_cols if c in selected_df.columns]

        st.dataframe(
            selected_df[selected_cols].sort_values(
                ["position", "expected_gw_points"],
                ascending=[True, False],
            ),
            use_container_width=True,
            hide_index=True,
        )

        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Låste spillere", f"{len(selected_df)}")
        with m2:
            st.metric("Kostnad låste", f"£{selected_cost:.1f}m")
        with m3:
            st.metric("Budsjett igjen", f"£{remaining_budget:.1f}m")

        # Give immediate feedback before the optimizer runs.
        position_limits = {
            "GKP": 2,
            "DEF": 5,
            "MID": 5,
            "FWD": 3,
        }

        position_counts = selected_df["position"].value_counts().to_dict()
        club_counts = selected_df["team_id"].value_counts().to_dict()

        invalid_reasons = []

        if len(selected_df) > 15:
            invalid_reasons.append("Du kan maksimalt låse 15 spillere.")

        if selected_cost > budget + 1e-9:
            invalid_reasons.append(
                f"De låste spillerne koster £{selected_cost:.1f}m, "
                f"som er over budsjettet på £{budget:.1f}m."
            )

        for pos, limit in position_limits.items():
            count = position_counts.get(pos, 0)
            if count > limit:
                invalid_reasons.append(
                    f"Du har valgt {count} {pos}-spillere, men maksgrensen er {limit}."
                )

        if club_counts and max(club_counts.values()) > 3:
            invalid_reasons.append(
                "Du har valgt mer enn 3 spillere fra samme klubb."
            )

        if invalid_reasons:
            for reason in invalid_reasons:
                st.warning(reason)
        else:
            st.write(
                "Når du trykker på knappen under, beholder modellen disse spillerne "
                "og optimaliserer alle resterende plasser."
            )

        build_button = st.button(
            "🧩 Bygg laget rundt mine spillere",
            type="primary",
            use_container_width=True,
            disabled=bool(invalid_reasons),
        )

        if build_button:
            with st.spinner("Bygger laget rundt dine spillere..."):
                around_result = build_around_players(
                    df,
                    selected_ids,
                    budget,
                )

            if around_result:
                score, cost, squad, xi, bench = around_result
                locked_set = set(selected_ids)

                st.success(
                    "Laget er bygget rundt dine valgte spillere. "
                    "De låste spillerne er beholdt, og resten er optimalisert av modellen."
                )

                xi_points = sum(
                    float(x["expected_gw_points"])
                    for x in xi
                )

                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("Troppskostnad", f"£{cost:.1f}m")
                with m2:
                    st.metric("Budsjett igjen", f"£{budget - cost:.1f}m")
                with m3:
                    st.metric("Forventede XI-poeng", f"{xi_points:.1f}")

                # ------------------------------------------------
                # Starting XI
                # ------------------------------------------------
                st.subheader("🏆 Ditt lag")
                st.caption(
                    "🔒 = spiller du valgte selv · 🤖 = spiller modellen har valgt"
                )

                xi_display = pd.DataFrame(xi).copy()
                xi_display["valg"] = xi_display["id"].apply(
                    lambda x: "🔒 Låst" if x in locked_set else "🤖 Modell"
                )

                xi_cols = [
                    "valg",
                    "name",
                    "team_name",
                    "position",
                    "price",
                    "expected_minutes",
                    "expected_gw_points",
                    "value",
                    "xgi90",
                    "fixture_next3",
                ]
                xi_cols = [c for c in xi_cols if c in xi_display.columns]

                st.dataframe(
                    xi_display[xi_cols],
                    use_container_width=True,
                    hide_index=True,
                )

                # ------------------------------------------------
                # Bench
                # ------------------------------------------------
                st.subheader("Bench")

                bench_display = pd.DataFrame(bench).copy()
                bench_display["valg"] = bench_display["id"].apply(
                    lambda x: "🔒 Låst" if x in locked_set else "🤖 Modell"
                )

                bench_cols = [
                    "valg",
                    "name",
                    "team_name",
                    "position",
                    "price",
                    "expected_minutes",
                    "expected_gw_points",
                    "value",
                ]
                bench_cols = [c for c in bench_cols if c in bench_display.columns]

                st.dataframe(
                    bench_display[bench_cols],
                    use_container_width=True,
                    hide_index=True,
                )

                # ------------------------------------------------
                # Captain / vice-captain
                # ------------------------------------------------
                cap = max(
                    xi,
                    key=lambda x: x["captain_score"],
                )
                vice_pool = [
                    x for x in xi
                    if x["id"] != cap["id"]
                ]
                vice = max(
                    vice_pool,
                    key=lambda x: x["captain_score"],
                )

                st.subheader("🎯 Kaptein og visekaptein")

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(
                        f"""
                        <div class="section-card">
                            <div class="muted">KAPTEIN</div>
                            <div class="player-name">
                                {cap["name"]} · {cap["position"]}
                            </div>
                            <div>
                                Forventet: {cap["expected_gw_points"]:.2f} poeng
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                with c2:
                    st.markdown(
                        f"""
                        <div class="section-card">
                            <div class="muted">VICE-CAPTAIN</div>
                            <div class="player-name">
                                {vice["name"]} · {vice["position"]}
                            </div>
                            <div>
                                Forventet: {vice["expected_gw_points"]:.2f} poeng
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                with st.expander("🔎 Vis optimaliseringsdetaljer"):
                    st.write(f"Squad objective: **{score:.2f}**")
                    st.write("Struktur: **2 GKP / 5 DEF / 5 MID / 3 FWD**")
                    st.write("Maksimalt 3 spillere fra samme klubb.")
            else:
                st.error(
                    "Modellen fant ikke en gyldig 15-mannstropp rundt disse spillerne "
                    "innenfor budsjett og FPL-reglene. Prøv å låse færre spillere "
                    "eller velg en annen kombinasjon."
                )
    else:
        st.info(
            "Velg én eller flere spillere ovenfor. Du kan for eksempel låse "
            "Haaland + Bruno Fernandes + en valgfri spiller, og la modellen "
            "bygge resten av laget rundt dem."
        )

# =========================================================
# FOOTER
# =========================================================

st.divider()
st.caption(
    "FPL Analyzer · Live FPL-data · Analysemodell og anbefalinger er "
    "modellbaserte estimater, ikke garantier."
)
