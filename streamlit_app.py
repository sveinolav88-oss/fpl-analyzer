import html
from collections import Counter

import pandas as pd
import streamlit as st

from main import (
    load_fpl,
    load_fixtures,
    build_players,
    assign_recommendations,
    select_squad,
    build_around_players,
)
from pitch_builder import build_display_xi


st.set_page_config(
    page_title="FPL Analyzer",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container { max-width: 1500px; padding-top: 1.2rem; padding-bottom: 3rem; }
    .hero { padding: 1.7rem 2rem; border-radius: 20px; background: linear-gradient(135deg,#111827,#1f2937); color:white; margin-bottom:1.2rem; border:1px solid rgba(255,255,255,.08); }
    .hero h1 { margin:0; font-size:2.45rem; line-height:1.1; }
    .hero p { margin:.5rem 0 0; opacity:.75; }
    .section-card { padding:1rem 1.2rem; border-radius:16px; border:1px solid rgba(128,128,128,.22); background:rgba(128,128,128,.04); margin-bottom:1rem; }

    /* V2 football-pitch design */
    .pitch-anchor { display:none; }
    div[data-testid="stVerticalBlock"]:has(.pitch-anchor) {
        position:relative;
        overflow:hidden;
        margin:.6rem 0 1.2rem;
        padding:1.25rem .9rem 1rem;
        border-radius:28px;
        border:1px solid rgba(155,235,178,.24);
        background:
          radial-gradient(circle at 50% 50%, rgba(255,255,255,.035) 0 7.5%, transparent 7.7% 100%),
          linear-gradient(90deg, transparent 49.8%, rgba(194,255,210,.20) 49.9%, rgba(194,255,210,.20) 50.1%, transparent 50.2%),
          linear-gradient(180deg, rgba(22,112,65,.94), rgba(10,73,43,.96));
        box-shadow: inset 0 0 70px rgba(0,0,0,.18), 0 10px 35px rgba(0,0,0,.18);
    }
    div[data-testid="stVerticalBlock"]:has(.pitch-anchor)::before {
        content:"";
        position:absolute;
        inset:10px;
        border:2px solid rgba(220,255,228,.20);
        border-radius:20px;
        pointer-events:none;
    }
    div[data-testid="stVerticalBlock"]:has(.pitch-anchor)::after {
        content:"";
        position:absolute;
        left:22%; right:22%; top:50%; height:23%;
        transform:translateY(-50%);
        border:2px solid rgba(220,255,228,.16);
        border-radius:4px;
        pointer-events:none;
    }
    .pitch-anchor ~ * { position:relative; z-index:1; }
    .pitch-title { text-align:center; font-weight:850; letter-spacing:.10em; font-size:.72rem; color:rgba(236,255,241,.72); margin:.45rem 0 .12rem; }
    .pitch-empty { text-align:center; color:rgba(236,255,241,.62); font-size:.73rem; margin-top:-.15rem; }
    .player-card { text-align:center; min-height:138px; padding:.35rem .2rem .45rem; }
    .player-card img { width:76px; height:76px; object-fit:cover; border-radius:50%; border:3px solid rgba(255,255,255,.88); background:#20242d; display:inline-block; }
    .player-card .name { font-weight:850; font-size:.92rem; margin-top:.2rem; color:white; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .player-card .team { color:rgba(255,255,255,.68); font-size:.75rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .player-card .meta { color:rgba(255,255,255,.78); font-size:.72rem; }
    .locked-badge { display:inline-block; margin-top:.15rem; padding:.12rem .42rem; border-radius:999px; font-size:.65rem; background:rgba(239,94,86,.20); color:#ffd1cc; }

    .bench-card { padding:.55rem; border-radius:14px; border:1px solid rgba(255,255,255,.08); background:rgba(255,255,255,.025); text-align:center; }
    .bench-card img { width:58px; height:58px; object-fit:cover; border-radius:50%; border:2px solid rgba(255,255,255,.7); display:inline-block; }
    .bench-card .name { font-weight:750; font-size:.82rem; margin-top:.2rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .bench-card .meta { font-size:.7rem; opacity:.68; }
    div[data-testid="stMetric"] { padding:.45rem .15rem; }

    /* Make pitch controls feel like FPL pitch buttons */
    div[data-testid="stVerticalBlock"]:has(.pitch-anchor) button {
        border-color:rgba(220,255,228,.25);
        background:rgba(4,45,26,.28);
        color:white;
        border-radius:12px;
    }
    div[data-testid="stVerticalBlock"]:has(.pitch-anchor) button:hover {
        border-color:rgba(220,255,228,.55);
        background:rgba(4,45,26,.45);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
      <h1>⚽ FPL Analyzer</h1>
      <p>Live Fantasy Premier League analysis · Optimal squad · Transfers · Captains · Differentials · Value</p>
    </div>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=900)
def get_analysis():
    _, teams, raw_players = load_fpl()
    fixtures = load_fixtures()
    df = build_players(raw_players, teams, fixtures)
    df = assign_recommendations(df)

    # FPL API's `photo` field is the player portrait identifier.
    # The previous implementation used `code`, which is not the portrait id.
    photos = {}
    for p in raw_players:
        photo = str(p.get("photo", "") or "").strip()
        photo = photo.rsplit(".", 1)[0] if photo else ""
        photos[p.get("id")] = photo

    df["photo_code"] = df["id"].map(photos).fillna("")
    df["image_url"] = df["photo_code"].map(
        lambda photo: (
            f"https://resources.premierleague.com/premierleague/photos/players/250x250/p{photo}.png"
            if photo else ""
        )
    )
    return df, teams


with st.spinner("Henter ferske FPL-data..."):
    try:
        df, teams = get_analysis()
        data_loaded = True
    except Exception as exc:
        data_loaded = False
        st.error(f"Kunne ikke hente FPL-data: {exc}")

with st.sidebar:
    st.header("⚙️ Innstillinger")
    budget = st.number_input("Budsjett (£m)", min_value=80.0, max_value=100.0, value=100.0, step=0.5)
    ownership_limit = st.slider("Differential maks. eierskap (%)", 1, 20, 10)
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

players_count = len(df)
avg_points = float(df["expected_gw_points"].mean())
top_player = df.sort_values("expected_gw_points", ascending=False).iloc[0]

c1, c2, c3, c4 = st.columns(4)
with c1: st.metric("Spillere analysert", f"{players_count}")
with c2: st.metric("Snitt forventede poeng", f"{avg_points:.2f}")
with c3: st.metric("Beste projeksjon", str(top_player["name"]))
with c4: st.metric("Forventede poeng", f"{top_player['expected_gw_points']:.2f}")


def esc(value):
    return html.escape(str(value))


def image_tag(p, size=76):
    url = p.get("image_url", "")
    photo = str(p.get("photo_code", "") or "")
    if not url and photo:
        url = f"https://resources.premierleague.com/premierleague/photos/players/250x250/p{photo}.png"
    if not url:
        return ""
    return f'<img src="{esc(url)}" width="{size}" height="{size}" loading="lazy" onerror="this.style.visibility=\'hidden\'">'


def player_card(p, locked=False):
    img = image_tag(p, 76)
    badge = '<div class="locked-badge">🔒 LÅST</div>' if locked else ''
    return f"""
    <div class="player-card">
      {img}
      <div class="name">{esc(p.get('name','?'))}</div>
      <div class="team">{esc(p.get('team_name','?'))}</div>
      <div class="meta">£{float(p.get('price',0)):.1f}m · {float(p.get('expected_gw_points',0)):.2f} p</div>
      {badge}
    </div>
    """


def bench_card(p, locked=False):
    img = image_tag(p, 58)
    badge = " · 🔒" if locked else ""
    return f"""
    <div class="bench-card">
      {img}
      <div class="name">{esc(p.get('name','?'))}</div>
      <div class="meta">{esc(p.get('team_name','?'))} · {esc(p.get('position','?'))}{badge}</div>
      <div class="meta">£{float(p.get('price',0)):.1f}m · {float(p.get('expected_gw_points',0)):.2f}</div>
    </div>
    """


def infer_formation(xi):
    counts = Counter(p["position"] for p in xi)
    key = f"{counts.get('DEF',0)}-{counts.get('MID',0)}-{counts.get('FWD',0)}"
    return key if key in FORMATIONS else "4-4-2"


def formation_shape(formation):
    d, m, f = (int(x) for x in formation.split("-"))
    return {"GKP":1, "DEF":d, "MID":m, "FWD":f}


FORMATIONS = {
    "3-4-3": "3 forsvar · 4 midtbane · 3 angrep",
    "3-5-2": "3 forsvar · 5 midtbane · 2 angrep",
    "4-3-3": "4 forsvar · 3 midtbane · 3 angrep",
    "4-4-2": "4 forsvar · 4 midtbane · 2 angrep",
    "4-5-1": "4 forsvar · 5 midtbane · 1 angrep",
    "5-2-3": "5 forsvar · 2 midtbane · 3 angrep",
    "5-3-2": "5 forsvar · 3 midtbane · 2 angrep",
    "5-4-1": "5 forsvar · 4 midtbane · 1 angrep",
}


def player_label(pid):
    p = PLAYER_LOOKUP.get(pid, {})
    return f"{p.get('name','?')} · {p.get('team_name','?')} · £{float(p.get('price',0)):.1f}m"


PLAYER_LOOKUP = df.set_index("id").to_dict("index")


def render_static_pitch(xi, formation, locked_ids=None, title="LAGOPPSTILLING"):
    locked_ids = set(locked_ids or [])
    by_pos = {pos: [] for pos in ["GKP", "DEF", "MID", "FWD"]}
    for p in xi:
        by_pos[p["position"]].append(p)

    shape = formation_shape(formation)
    with st.container():
        st.markdown('<span class="pitch-anchor"></span>', unsafe_allow_html=True)
        st.markdown(f'<div class="pitch-title">{title}</div>', unsafe_allow_html=True)
        for pos, label in [("GKP","KEEPER"),("DEF","FORSVAR"),("MID","MIDTBANE"),("FWD","ANGREP")]:
            st.markdown(f'<div class="pitch-title">{label}</div>', unsafe_allow_html=True)
            players = by_pos[pos][:shape[pos]]
            cols = st.columns(max(1, shape[pos]), gap="small")
            for i, col in enumerate(cols):
                with col:
                    if i < len(players):
                        p = players[i]
                        st.markdown(player_card(p, p.get("id") in locked_ids), unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="pitch-empty">—</div>', unsafe_allow_html=True)


def render_bench(bench, locked_ids=None):
    locked_ids = set(locked_ids or [])
    cols = st.columns(4, gap="small")
    for i, p in enumerate(bench[:4]):
        with cols[i]:
            st.markdown(bench_card(p, p.get("id") in locked_ids), unsafe_allow_html=True)


def captain_cards(xi):
    if len(xi) < 2:
        return
    cap = max(xi, key=lambda x: x["captain_score"])
    vice = max([x for x in xi if x["id"] != cap["id"]], key=lambda x: x["captain_score"])
    c1, c2 = st.columns(2)
    for col, title, p in [(c1,"KAPTEIN",cap),(c2,"VICE-CAPTAIN",vice)]:
        with col:
            st.markdown(
                f'<div class="section-card"><div class="pitch-title">{title}</div>{player_card(p)}<div style="text-align:center">Forventet: <b>{float(p["expected_gw_points"]):.2f}</b> poeng</div></div>',
                unsafe_allow_html=True,
            )


tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🏆 Beste lag", "🔄 Transfers", "©️ Kapteiner", "🔥 Differentials", "💰 Best value", "🧩 Bygg rundt mine spillere"
])

with tab1:
    st.header("🏆 Beste 15-mannstropp")
    st.caption("Optimaliseres innenfor budsjett, FPL-struktur og klubbbegrensning.")
    result = select_squad(df, budget)
    if result:
        score, cost, squad, xi, bench = result
        m1, m2, m3 = st.columns(3)
        m1.metric("Troppskostnad", f"£{cost:.1f}m")
        m2.metric("Budsjett igjen", f"£{budget-cost:.1f}m")
        m3.metric("Forventede XI-poeng", f"{sum(float(x['expected_gw_points']) for x in xi):.1f}")
        st.subheader("🏟️ Starting XI")
        render_static_pitch(xi, infer_formation(xi), title="STARTING XI")
        st.subheader("🪑 Benk")
        render_bench(bench)
        st.subheader("🎯 Kaptein og visekaptein")
        captain_cards(xi)
        with st.expander("🔎 Vis optimaliseringsdetaljer"):
            st.write(f"Squad objective: **{score:.2f}**")
            st.write("Struktur: **2 GKP / 5 DEF / 5 MID / 3 FWD**")
            st.write("Maksimalt 3 spillere fra samme klubb.")
    else:
        st.error("Fant ingen gyldig FPL-tropp innenfor budsjettet.")

with tab2:
    st.header("🔄 Beste transfermål")
    positions = ["GKP","DEF","MID","FWD"]
    position_filter = st.multiselect("Posisjon", positions, default=positions)
    min_minutes = st.slider("Minimum forventede minutter", 0, 90, 60, 5)
    x = df[df["position"].isin(position_filter) & (df["expected_minutes"] >= min_minutes)].copy()
    x = x.sort_values(["transfer_score","expected_gw_points"], ascending=False).head(30)
    cols = ["name","team_name","position","price","ownership","expected_minutes","expected_gw_points","value","fixture_next3","transfer_score","recommendation"]
    st.dataframe(x[[c for c in cols if c in x.columns]], use_container_width=True, hide_index=True)

with tab3:
    st.header("©️ Kapteinguide")
    x = df[df["expected_minutes"] >= 60].sort_values(["captain_score","expected_gw_points"], ascending=False).head(20)
    if len(x):
        st.success(f"🥇 Førstevalg: **{x.iloc[0]['name']}** · {x.iloc[0]['expected_gw_points']:.2f} forventede poeng")
    cols = ["name","team_name","position","price","expected_minutes","expected_gw_points","fixture_next3","captain_score"]
    st.dataframe(x[[c for c in cols if c in x.columns]], use_container_width=True, hide_index=True)

with tab4:
    st.header("🔥 Differentials")
    x = df[(df["ownership"] <= ownership_limit) & (df["expected_minutes"] >= 60)].sort_values(["differential_score","expected_gw_points"], ascending=False).head(30)
    cols = ["name","team_name","position","price","ownership","expected_minutes","expected_gw_points","value","fixture_next3","differential_score"]
    st.dataframe(x[[c for c in cols if c in x.columns]], use_container_width=True, hide_index=True)

with tab5:
    st.header("💰 Best value")
    x = df[df["expected_minutes"] >= 60].sort_values(["value","expected_gw_points"], ascending=False).head(30)
    cols = ["name","team_name","position","price","ownership","expected_minutes","expected_gw_points","value","fixture_next3"]
    st.dataframe(x[[c for c in cols if c in x.columns]], use_container_width=True, hide_index=True)

with tab6:
    st.header("🧩 Bygg laget rundt mine spillere")
    st.caption("Start med en tom bane. Trykk **＋** på akkurat den posisjonen du vil fylle, velg spilleren, og la modellen bygge resten av troppen rundt valgene dine.")
    st.info("Utgangspunkt: **4–4–2**. Banen starter alltid tom, og hvert **＋** åpner kun spillere fra den aktuelle posisjonen.")

    formation = "4-4-2"
    shape = formation_shape(formation)
    valid_slots = ["GKP_0"] + [f"DEF_{i}" for i in range(shape["DEF"])] + [f"MID_{i}" for i in range(shape["MID"])] + [f"FWD_{i}" for i in range(shape["FWD"])]

    if "build_pitch_slots" not in st.session_state:
        st.session_state.build_pitch_slots = {k: None for k in valid_slots}
    else:
        old = st.session_state.build_pitch_slots
        st.session_state.build_pitch_slots = {k: old.get(k) for k in valid_slots}
    if "build_active_slot" not in st.session_state:
        st.session_state.build_active_slot = None

    slots = st.session_state.build_pitch_slots
    selected_ids = [pid for pid in slots.values() if pid is not None]
    selected_set = set(selected_ids)

    if st.button("♻️ Tøm banen", key="clear_build_pitch"):
        st.session_state.build_pitch_slots = {k: None for k in valid_slots}
        st.session_state.build_active_slot = None
        st.session_state.pop("build_result", None)
        st.rerun()

    with st.container():
        st.markdown('<span class="pitch-anchor"></span>', unsafe_allow_html=True)
        st.markdown(f'<div class="pitch-title">{formation} · TOM BANE</div>', unsafe_allow_html=True)
        for pos, label in [("GKP","KEEPER"),("DEF","FORSVAR"),("MID","MIDTBANE"),("FWD","ANGREP")]:
            st.markdown(f'<div class="pitch-title">{label}</div>', unsafe_allow_html=True)
            row_keys = [k for k in valid_slots if k.startswith(pos + "_")]
            cols = st.columns(len(row_keys), gap="small")
            for i, key in enumerate(row_keys):
                with cols[i]:
                    pid = slots.get(key)
                    if pid is None:
                        if st.button("＋", key=f"plus_{key}", use_container_width=True):
                            st.session_state.build_active_slot = key
                            st.rerun()
                        st.markdown('<div class="pitch-empty">Trykk + for å velge</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(player_card(PLAYER_LOOKUP[pid], locked=True), unsafe_allow_html=True)
                        if st.button("✕ Fjern", key=f"remove_{key}", use_container_width=True):
                            st.session_state.build_pitch_slots[key] = None
                            st.session_state.build_active_slot = None
                            st.session_state.pop("build_result", None)
                            st.rerun()

    active = st.session_state.build_active_slot
    if active:
        pos = active.split("_")[0]
        available = [pid for pid in df[df["position"] == pos]["id"].tolist() if pid not in selected_set]
        st.markdown(f"### ➕ Velg spiller til {pos}")
        pick = st.selectbox("Spiller", [0] + available, format_func=lambda pid: "Velg spiller..." if pid == 0 else player_label(pid), key=f"pick_{active}")
        a, b = st.columns([1,1])
        with a:
            if st.button("Legg spiller på banen", type="primary", use_container_width=True, disabled=(pick == 0)):
                st.session_state.build_pitch_slots[active] = pick
                st.session_state.build_active_slot = None
                st.session_state.pop("build_result", None)
                st.rerun()
        with b:
            if st.button("Avbryt", use_container_width=True):
                st.session_state.build_active_slot = None
                st.rerun()

    if selected_ids:
        selected_df = df[df["id"].isin(selected_ids)].copy()
        selected_cost = float(selected_df["price"].sum())
        counts = Counter(selected_df["position"])
        clubs = Counter(selected_df["team_id"])
        reasons = []
        if selected_cost > budget: reasons.append(f"Valgte spillere koster £{selected_cost:.1f}m, mer enn budsjettet på £{budget:.1f}m.")
        if max(clubs.values(), default=0) > 3: reasons.append("Du har valgt mer enn 3 spillere fra samme klubb.")
        for pos, limit in {"GKP":2,"DEF":5,"MID":5,"FWD":3}.items():
            if counts.get(pos,0) > limit: reasons.append(f"For mange {pos}-spillere.")

        m1, m2, m3 = st.columns(3)
        m1.metric("Låste spillere", len(selected_ids))
        m2.metric("Kostnad låste", f"£{selected_cost:.1f}m")
        m3.metric("Budsjett igjen", f"£{budget-selected_cost:.1f}m")
        if reasons:
            for reason in reasons: st.warning(reason)

        signature = tuple(sorted(selected_ids))
        build_button = st.button("🧩 Bygg laget rundt mine spillere", type="primary", use_container_width=True, disabled=bool(reasons))
        if build_button:
            with st.spinner("Bygger laget rundt dine spillere..."):
                result = build_around_players(df, selected_ids, budget)
            if result:
                st.session_state.build_result = result
                st.session_state.build_result_signature = signature
                st.rerun()
            else:
                st.error("Modellen fant ikke en gyldig 15-mannstropp rundt disse spillerne innenfor budsjett og FPL-reglene.")

        stored = st.session_state.get("build_result")
        if stored and st.session_state.get("build_result_signature") == signature:
            score, cost, squad, _, _ = stored
            display_xi = build_display_xi(squad, selected_ids, formation)
            if display_xi is None:
                st.warning("Modellen fant troppen, men den valgte formasjonen har ikke plass til alle låste spillere.")
            else:
                xi_ids = {p["id"] for p in display_xi}
                bench = sorted([p for p in squad if p["id"] not in xi_ids], key=lambda p: (p["expected_gw_points"], p.get("minutes_probability",0)), reverse=True)[:4]
                st.success("Laget er bygget rundt spillerne på banen. 🔒 = dine valg · 🤖 = modellens valg.")
                mm1, mm2, mm3 = st.columns(3)
                mm1.metric("Troppskostnad", f"£{cost:.1f}m")
                mm2.metric("Budsjett igjen", f"£{budget-cost:.1f}m")
                mm3.metric("Forventede XI-poeng", f"{sum(float(p['expected_gw_points']) for p in display_xi):.1f}")
                st.subheader("🏟️ Ditt lag")
                render_static_pitch(display_xi, formation, selected_ids, title=f"{formation} · DITT LAG")
                st.subheader("🪑 Benk")
                render_bench(bench, selected_ids)
                st.subheader("🎯 Kaptein og visekaptein")
                captain_cards(display_xi)
                with st.expander("🔎 Vis optimaliseringsdetaljer"):
                    st.write(f"Squad objective: **{score:.2f}**")
                    st.write("15-mannstroppen er fortsatt optimalisert etter FPL-reglene, mens dine valgte spillere holdes låst.")
    else:
        st.info("Banen er tom. Trykk **＋** på en posisjon for å starte.")

st.divider()
st.caption("FPL Analyzer · Live FPL-data · Analysemodell og anbefalinger er modellbaserte estimater, ikke garantier.")