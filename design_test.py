import html
import streamlit as st
import pandas as pd

from main import (
    load_fpl,
    load_fixtures,
    build_players,
    assign_recommendations,
    select_squad,
)

st.set_page_config(
    page_title="FPL Analyzer – V2 Design Test",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# VISUAL DESIGN TEST
# ============================================================

st.markdown(
    """
    <style>
    .block-container { max-width: 1500px; padding-top: 1.2rem; padding-bottom: 3rem; }
    .hero {
        padding: 1.35rem 1.6rem;
        border-radius: 22px;
        background: linear-gradient(135deg, #111827 0%, #182235 55%, #202b3f 100%);
        border: 1px solid rgba(255,255,255,.08);
        margin-bottom: 1.1rem;
    }
    .hero-title { font-size: 2.15rem; font-weight: 850; margin: 0; }
    .hero-sub { margin-top: .35rem; opacity: .68; font-size: .95rem; }
    .metric-card {
        background: rgba(255,255,255,.035);
        border: 1px solid rgba(255,255,255,.08);
        border-radius: 16px;
        padding: 1rem 1.1rem;
        min-height: 92px;
    }
    .metric-label { font-size: .75rem; text-transform: uppercase; letter-spacing: .08em; opacity: .55; }
    .metric-value { font-size: 1.55rem; font-weight: 800; margin-top: .2rem; }
    .pitch-wrap {
        border-radius: 24px;
        padding: 18px;
        background: linear-gradient(180deg, #173f31, #0e2f26);
        border: 1px solid rgba(255,255,255,.10);
        box-shadow: 0 20px 50px rgba(0,0,0,.28);
        margin: .6rem 0 1.3rem;
    }
    .pitch {
        position: relative;
        min-height: 650px;
        border-radius: 18px;
        overflow: hidden;
        background:
            repeating-linear-gradient(0deg, rgba(255,255,255,.025) 0 72px, rgba(255,255,255,.045) 72px 144px),
            linear-gradient(90deg, rgba(255,255,255,.025) 0 50%, transparent 50% 100%);
        border: 2px solid rgba(255,255,255,.28);
    }
    .pitch:before {
        content: "";
        position: absolute;
        left: 50%; top: 0; bottom: 0;
        width: 1px; background: rgba(255,255,255,.24);
    }
    .pitch:after {
        content: "";
        position: absolute;
        left: 50%; top: 50%; width: 110px; height: 110px;
        transform: translate(-50%,-50%);
        border: 1px solid rgba(255,255,255,.24); border-radius: 50%;
    }
    .pitch-row { display: flex; justify-content: space-evenly; align-items: center; position: absolute; left: 1%; right: 1%; z-index: 2; }
    .row-gkp { bottom: 3%; }
    .row-def { bottom: 23%; }
    .row-mid { bottom: 46%; }
    .row-fwd { bottom: 70%; }
    .player-card {
        width: 112px;
        text-align: center;
        color: white;
        font-size: .78rem;
        filter: drop-shadow(0 7px 8px rgba(0,0,0,.3));
    }
    .player-photo {
        width: 68px; height: 68px; object-fit: contain;
        border-radius: 50%; background: rgba(255,255,255,.10);
        border: 2px solid rgba(255,255,255,.75);
    }
    .player-badge {
        margin: -8px auto 0; width: 94px;
        padding: 5px 6px 6px; border-radius: 9px;
        background: rgba(10,17,28,.93); border: 1px solid rgba(255,255,255,.14);
    }
    .player-card .pname { font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .player-card .pmeta { opacity: .62; font-size: .68rem; }
    .captain { position: relative; }
    .captain .cap-mark {
        position: absolute; right: 6px; top: 0; background: #f0b90b; color: #111;
        width: 22px; height: 22px; line-height: 22px; border-radius: 50%; font-weight: 900; font-size: .72rem;
    }
    .vice .cap-mark { background: #d8dee9; }
    .bench-wrap {
        border-radius: 20px;
        padding: 16px 18px 18px;
        background: rgba(255,255,255,.025);
        border: 1px solid rgba(255,255,255,.08);
        margin: .3rem 0 1.2rem;
    }
    .bench-title { font-size: 1.05rem; font-weight: 800; margin-bottom: .8rem; }
    .bench-row {
        display: flex;
        justify-content: space-evenly;
        align-items: flex-start;
        gap: 10px;
        overflow-x: auto;
        padding: 4px 2px 2px;
    }
    .bench-row .player-card { flex: 0 0 112px; }
    .section-head { display:flex; align-items:baseline; gap:.6rem; margin-top:.4rem; }
    .section-head h2 { margin:0; }
    .section-sub { opacity:.55; font-size:.85rem; }
    .locked-card {
        border: 1px solid rgba(239,95,88,.35); background: rgba(239,95,88,.06);
        border-radius: 15px; padding: .85rem 1rem; margin-bottom: .5rem;
    }
    .pill { display:inline-block; padding:.2rem .5rem; border-radius:999px; background:rgba(255,255,255,.07); font-size:.72rem; margin-right:.25rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def photo_url(photo):
    if not photo:
        return ""
    stem = str(photo).rsplit(".", 1)[0]
    return f"https://resources.premierleague.com/premierleague/photos/players/250x250/p{stem}.png"


def safe_img(url):
    if url:
        return url
    return "https://resources.premierleague.com/premierleague/badges/50/t1.png"


def player_card(p, role=None):
    name = html.escape(str(p.get("name", "?")))
    team = html.escape(str(p.get("team_name", "?")))
    points = float(p.get("expected_gw_points", 0))
    price = float(p.get("price", 0))
    mark = ""
    extra = ""
    if role == "C":
        mark = '<span class="cap-mark">C</span>'
        extra = " captain"
    elif role == "VC":
        mark = '<span class="cap-mark">V</span>'
        extra = " vice"
    return f'''
    <div class="player-card{extra}">
      <div style="position:relative;display:inline-block;">
        {mark}<img class="player-photo" src="{safe_img(photo_url(p.get("photo")))}">
      </div>
      <div class="player-badge">
        <div class="pname">{name}</div>
        <div class="pmeta">{team} · £{price:.1f}m</div>
        <div style="font-weight:800;margin-top:2px;">{points:.2f} pts</div>
      </div>
    </div>'''


def render_pitch(xi, cap, vice):
    rows = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in xi:
        rows.setdefault(p["position"], []).append(p)
    for key in rows:
        rows[key] = sorted(rows[key], key=lambda x: x["expected_gw_points"], reverse=True)

    def row(position, cls):
        cards = []
        for p in rows.get(position, []):
            role = "C" if p["id"] == cap["id"] else ("VC" if p["id"] == vice["id"] else None)
            cards.append(player_card(p, role))
        return f'<div class="pitch-row {cls}">' + "".join(cards) + "</div>"

    return f'''
    <div class="pitch-wrap">
      <div class="pitch">
        {row("FWD", "row-fwd")}
        {row("MID", "row-mid")}
        {row("DEF", "row-def")}
        {row("GKP", "row-gkp")}
      </div>
    </div>'''


def render_bench(bench):
    cards = []
    for p in bench:
        cards.append(player_card(p))
    return f'''
    <div class="bench-wrap">
      <div class="bench-title">🪑 Benk <span class="section-sub">· førstevalg vises først</span></div>
      <div class="bench-row">{"".join(cards)}</div>
    </div>'''


@st.cache_data(ttl=900)
def get_analysis():
    data, teams, raw_players = load_fpl()
    fixtures = load_fixtures()
    df = build_players(raw_players, teams, fixtures)
    df = assign_recommendations(df)
    photos = {p.get("id"): p.get("photo") for p in raw_players}
    df["photo"] = df["id"].map(photos)
    return df, teams

with st.sidebar:
    st.header("⚙️ Innstillinger")
    budget = st.number_input("Budsjett (£m)", min_value=80.0, max_value=100.0, value=100.0, step=0.5)
    ownership_limit = st.slider("Differential maks. eierskap (%)", 1, 20, 10)
    st.divider()
    if st.button("🔄 Oppdater FPL-data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption("V2 Design Test")
    st.caption("Funksjonaliteten er den samme – dette er kun en visuell test.")

st.markdown('''
<div class="hero">
  <div class="hero-title">⚽ FPL Analyzer</div>
  <div class="hero-sub">V2 Design Test · Live FPL-data · Optimal squad · Transfers · Captains · Differentials · Value</div>
</div>''', unsafe_allow_html=True)

with st.spinner("Henter ferske FPL-data..."):
    try:
        df, teams = get_analysis()
    except Exception as exc:
        st.error(f"Kunne ikke hente FPL-data: {exc}")
        st.stop()

players_count = len(df)
avg_points = float(df["expected_gw_points"].mean())
top_player = df.sort_values("expected_gw_points", ascending=False).iloc[0]

m1, m2, m3, m4 = st.columns(4)
metric_data = [
    (m1, "SPILLERE ANALYSERT", f"{players_count}"),
    (m2, "SNITT FORVENTEDE POENG", f"{avg_points:.2f}"),
    (m3, "BESTE PROJEKSJON", str(top_player["name"])),
    (m4, "FORVENTEDE POENG", f"{top_player['expected_gw_points']:.2f}"),
]
for col, label, value in metric_data:
    with col:
        st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🏆 Beste lag", "🔄 Transfers", "©️ Kapteiner", "🔥 Differentials", "💰 Best value", "🧩 Bygg rundt mine spillere"])

# ============================================================
# BEST SQUAD – VISUAL TEST
# ============================================================
with tab1:
    st.markdown('<div class="section-head"><h2>🏆 Beste lag</h2><span class="section-sub">Modellen bygger den beste XI-en innenfor budsjett og FPL-regler</span></div>', unsafe_allow_html=True)
    result = select_squad(df, budget)
    if not result:
        st.error("Fant ingen gyldig FPL-tropp innenfor budsjettet.")
    else:
        score, cost, squad, xi, bench = result
        cap = max(xi, key=lambda x: x["captain_score"])
        vice = max([x for x in xi if x["id"] != cap["id"]], key=lambda x: x["captain_score"])
        xi_points = sum(float(x["expected_gw_points"]) for x in xi)
        a, b, c = st.columns(3)
        with a: st.metric("Troppskostnad", f"£{cost:.1f}m")
        with b: st.metric("Budsjett igjen", f"£{budget-cost:.1f}m")
        with c: st.metric("Forventede XI-poeng", f"{xi_points:.1f}")

        # Først banen, deretter benken, deretter kaptein/visekaptein.
        st.markdown(render_pitch(xi, cap, vice), unsafe_allow_html=True)
        st.markdown(render_bench(bench), unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f'<div class="locked-card"><b>👑 Kaptein</b><br><span style="font-size:1.2rem;font-weight:800;">{html.escape(cap["name"])}</span><br><span class="pill">{cap["team_name"]}</span><span class="pill">{cap["expected_gw_points"]:.2f} forventede poeng</span></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="locked-card"><b>◉ Visekaptein</b><br><span style="font-size:1.2rem;font-weight:800;">{html.escape(vice["name"])}</span><br><span class="pill">{vice["team_name"]}</span><span class="pill">{vice["expected_gw_points"]:.2f} forventede poeng</span></div>', unsafe_allow_html=True)

        with st.expander("🔎 Vis optimaliseringsdetaljer"):
            st.write(f"Squad objective: **{score:.2f}**")
            st.write("Struktur: **2 GKP / 5 DEF / 5 MID / 3 FWD**")
            st.write("Maksimalt 3 spillere fra samme klubb.")

# ============================================================
# TRANSFERS
# ============================================================
with tab2:
    st.markdown('<div class="section-head"><h2>🔄 Beste transfermål</h2><span class="section-sub">Rangert etter transfer-score</span></div>', unsafe_allow_html=True)
    positions = ["GKP", "DEF", "MID", "FWD"]
    position_filter = st.multiselect("Posisjon", positions, default=positions, key="design_transfer_pos")
    min_minutes = st.slider("Minimum forventede minutter", 0, 90, 60, 5, key="design_transfer_min")
    t = df[df["position"].isin(position_filter) & (df["expected_minutes"] >= min_minutes)].copy().sort_values(["transfer_score","expected_gw_points"], ascending=False).head(30)
    cols = ["name","team_name","position","price","ownership","expected_minutes","expected_gw_points","value","fixture_next3","transfer_score","recommendation"]
    st.dataframe(t[[c for c in cols if c in t.columns]], use_container_width=True, hide_index=True)

# ============================================================
# CAPTAINS
# ============================================================
with tab3:
    st.markdown('<div class="section-head"><h2>©️ Kapteinguide</h2><span class="section-sub">Forventede poeng + spilletid + fixture</span></div>', unsafe_allow_html=True)
    cdf = df[df["expected_minutes"] >= 60].copy().sort_values(["captain_score","expected_gw_points"], ascending=False).head(20)
    if len(cdf):
        top = cdf.iloc[0]
        st.success(f"🥇 Førstevalg: **{top['name']}** · {top['expected_gw_points']:.2f} forventede poeng")
    cols = ["name","team_name","position","price","expected_minutes","expected_gw_points","fixture_next3","captain_score"]
    st.dataframe(cdf[[c for c in cols if c in cdf.columns]], use_container_width=True, hide_index=True)

# ============================================================
# DIFFERENTIALS
# ============================================================
with tab4:
    st.markdown('<div class="section-head"><h2>🔥 Differentials</h2><span class="section-sub">Lavere eierskap med god modellverdi</span></div>', unsafe_allow_html=True)
    ddf = df[(df["ownership"] <= ownership_limit) & (df["expected_minutes"] >= 60)].copy().sort_values(["differential_score","expected_gw_points"], ascending=False).head(30)
    cols = ["name","team_name","position","price","ownership","expected_minutes","expected_gw_points","value","fixture_next3","differential_score"]
    st.dataframe(ddf[[c for c in cols if c in ddf.columns]], use_container_width=True, hide_index=True)

# ============================================================
# VALUE
# ============================================================
with tab5:
    st.markdown('<div class="section-head"><h2>💰 Best value</h2><span class="section-sub">Forventede poeng per £m</span></div>', unsafe_allow_html=True)
    vdf = df[df["expected_minutes"] >= 60].copy().sort_values(["value","expected_gw_points"], ascending=False).head(30)
    cols = ["name","team_name","position","price","ownership","expected_minutes","expected_gw_points","value","fixture_next3"]
    st.dataframe(vdf[[c for c in cols if c in vdf.columns]], use_container_width=True, hide_index=True)

# ============================================================
# BUILD AROUND MY PLAYERS – VISUAL TEST
# ============================================================
with tab6:
    st.markdown('<div class="section-head"><h2>🧩 Bygg laget rundt mine spillere</h2><span class="section-sub">Lås dine spillere – modellen optimaliserer resten</span></div>', unsafe_allow_html=True)
    lookup = df.set_index("id").to_dict("index")
    ids = df["id"].tolist()

    def label(pid):
        p = lookup.get(pid, {})
        return f'{p.get("name","?")} · {p.get("team_name","?")} · {p.get("position","?")} · £{p.get("price",0):.1f}m'

    selected = st.multiselect("🔒 Velg spillerne du absolutt vil ha", ids, format_func=label, key="design_locked")
    if selected:
        locked = df[df["id"].isin(selected)].copy()
        cost_locked = float(locked["price"].sum())
        remain = budget - cost_locked
        st.markdown(f'<div class="metric-card"><div class="metric-label">LÅSTE SPILLERE</div><div class="metric-value">{len(selected)} &nbsp; · &nbsp; £{cost_locked:.1f}m brukt &nbsp; · &nbsp; £{remain:.1f}m igjen</div></div>', unsafe_allow_html=True)
        for _, p in locked.iterrows():
            st.markdown(f'<div class="locked-card">🔒 <b>{html.escape(str(p["name"]))}</b> · {p["team_name"]} · {p["position"]} · £{p["price"]:.1f}m · {p["expected_gw_points"]:.2f} forventede poeng</div>', unsafe_allow_html=True)
        if st.button("🧩 Bygg laget rundt mine spillere", type="primary", use_container_width=True, key="design_build"):
            with st.spinner("Bygger laget rundt dine spillere..."):
                result = select_squad(df, budget, locked_ids=selected)
            if not result:
                st.error("Fant ingen gyldig tropp med disse låste spillerne. Sjekk budsjett, posisjoner og maks. 3 spillere fra samme klubb.")
            else:
                score, cost, squad, xi, bench = result
                cap = max(xi, key=lambda x: x["captain_score"])
                vice = max([x for x in xi if x["id"] != cap["id"]], key=lambda x: x["captain_score"])
                st.success("Laget er bygget rundt dine valgte spillere.")
                st.markdown(render_pitch(xi, cap, vice), unsafe_allow_html=True)
                st.markdown(render_bench(bench), unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f'<div class="locked-card"><b>👑 Kaptein</b><br><span style="font-size:1.2rem;font-weight:800;">{html.escape(cap["name"])}</span><br><span class="pill">{cap["team_name"]}</span><span class="pill">{cap["expected_gw_points"]:.2f} forventede poeng</span></div>', unsafe_allow_html=True)
                with c2:
                    st.markdown(f'<div class="locked-card"><b>◉ Visekaptein</b><br><span style="font-size:1.2rem;font-weight:800;">{html.escape(vice["name"])}</span><br><span class="pill">{vice["team_name"]}</span><span class="pill">{vice["expected_gw_points"]:.2f} forventede poeng</span></div>', unsafe_allow_html=True)
                a,b,c = st.columns(3)
                with a: st.metric("Troppskostnad", f"£{cost:.1f}m")
                with b: st.metric("Budsjett igjen", f"£{budget-cost:.1f}m")
                with c: st.metric("Forventede XI-poeng", f"{sum(x['expected_gw_points'] for x in xi):.1f}")
                st.dataframe(pd.DataFrame(squad)[["name","team_name","position","price","expected_gw_points"]], use_container_width=True, hide_index=True)
    else:
        st.info("Velg én eller flere spillere ovenfor. De blir låst før modellen bygger resten av laget.")

st.markdown('<div style="text-align:center;opacity:.4;margin-top:2rem;font-size:.8rem;">FPL Analyzer · V2 Design Test · Ingen endringer i hovedappen</div>', unsafe_allow_html=True)
