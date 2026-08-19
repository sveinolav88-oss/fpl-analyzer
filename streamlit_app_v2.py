import html
from collections import Counter

import pandas as pd
import streamlit as st

from main import load_fpl, load_fixtures, build_players, assign_recommendations, select_squad, build_around_players
from pitch_builder import build_display_xi
from decision_engine import current_gameweek, load_manager, decision_summary

st.set_page_config(page_title="FPL Analyzer", page_icon="⚽", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.block-container{max-width:1500px;padding-top:1.2rem;padding-bottom:3rem}
.hero{padding:1.7rem 2rem;border-radius:20px;background:linear-gradient(135deg,#111827,#1f2937);color:white;margin-bottom:1.2rem;border:1px solid rgba(255,255,255,.08)}
.hero h1{margin:0;font-size:2.45rem;line-height:1.1}.hero p{margin:.5rem 0 0;opacity:.75}
.st-key-best-pitch,.st-key-built-pitch,.st-key-build-pitch{position:relative;overflow:hidden;margin:.6rem 0 1.25rem;padding:1.15rem .75rem 1rem;border-radius:26px;border:1px solid rgba(155,235,178,.24);background:#1f6b3d;background-image:url("data:image/svg+xml,%3Csvg xmlns='http%3A//www.w3.org/2000/svg' viewBox='0 0 1000 650' preserveAspectRatio='none'%3E%3Cg fill='none' stroke='white' stroke-opacity='.25' stroke-width='2'%3E%3Crect x='12' y='12' width='976' height='626'/%3E%3Cline x1='12' y1='325' x2='988' y2='325'/%3E%3Ccircle cx='500' cy='325' r='72'/%3E%3Cpath d='M350 12v133h300V12M350 638V505h300v133M425 12v58h150V12M425 638v-58h150v58'/%3E%3C/g%3E%3Cg fill='white' fill-opacity='.22'%3E%3Ccircle cx='500' cy='325' r='3'/%3E%3C/g%3E%3C/svg%3E");background-size:100% 100%;box-shadow:inset 0 0 70px rgba(0,0,0,.18),0 10px 35px rgba(0,0,0,.18)}
.pitch-formation{text-align:center;font-weight:850;letter-spacing:.12em;font-size:.68rem;color:rgba(236,255,241,.68);margin:0 0 .35rem}.pitch-slot{min-height:118px;display:flex;flex-direction:column;align-items:center;justify-content:flex-start}.pitch-empty{min-height:90px;display:flex;align-items:center;justify-content:center;color:rgba(236,255,241,.58)}
.player-card{text-align:center;min-height:112px;padding:.15rem .1rem .25rem}.player-card img,.player-avatar-fallback{width:72px;height:72px;object-fit:contain;border-radius:50%;border:3px solid rgba(255,255,255,.9);background:#20242d;display:block;margin:0 auto}.player-avatar-fallback{display:flex;align-items:center;justify-content:center;color:white;font-weight:850}.player-card .name{font-weight:850;font-size:.88rem;margin-top:.18rem;color:white;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.player-card .team{color:rgba(255,255,255,.72);font-size:.72rem}.player-card .meta{color:rgba(255,255,255,.82);font-size:.69rem}.locked-badge{display:inline-block;margin-top:.12rem;padding:.1rem .38rem;border-radius:999px;font-size:.62rem;background:rgba(239,94,86,.20);color:#ffd1cc}
.bench-card{padding:.65rem .45rem;border-radius:14px;border:1px solid rgba(255,255,255,.10);background:rgba(255,255,255,.045);text-align:center}.bench-card img,.bench-avatar-fallback{width:58px;height:58px;object-fit:contain;border-radius:50%;border:2px solid rgba(255,255,255,.7);display:block;margin:0 auto;background:#20242d}.bench-avatar-fallback{display:flex;align-items:center;justify-content:center;color:white;font-weight:800}.bench-card .name{font-weight:750;font-size:.82rem;margin-top:.2rem}.bench-card .meta{font-size:.7rem;opacity:.68}.captain-card{padding:1rem;border-radius:16px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.025);text-align:center;min-height:250px}.captain-title{font-size:.72rem;font-weight:850;letter-spacing:.12em;opacity:.65;margin-bottom:.5rem}
[class*="st-key-plus_"]{display:flex;justify-content:center;align-items:center;min-height:90px}[class*="st-key-plus_"] button{width:68px!important;min-width:68px!important;height:68px!important;min-height:68px!important;padding:0!important;margin:0 auto!important;border-radius:50%!important;border:2px solid rgba(220,255,228,.32)!important;background:rgba(8,35,22,.78)!important;color:white!important;font-size:1.45rem!important;line-height:1!important}[class*="st-key-plus_"] button:hover{border-color:rgba(235,255,240,.72)!important;background:rgba(8,35,22,.96)!important;transform:scale(1.06)}
.decision{padding:1rem 1.2rem;border-radius:18px;border:1px solid rgba(255,255,255,.10);background:rgba(255,255,255,.035);margin:.6rem 0}.decision h3{margin:.1rem 0 .35rem}.green{color:#9ff0b2}.yellow{color:#ffd67d}.red{color:#ff9991}.muted{opacity:.68}.chip-best{font-weight:800}.small{font-size:.82rem}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="hero"><h1>⚽ FPL Analyzer</h1><p>Live Fantasy Premier League analysis · Optimal squad · Transfers · Captains · Chips · Gameweek Decision Engine</p></div>', unsafe_allow_html=True)

@st.cache_data(ttl=900)
def get_analysis():
    data, teams, raw_players = load_fpl()
    fixtures = load_fixtures()
    df = assign_recommendations(build_players(raw_players, teams, fixtures))
    photos = {}
    for p in raw_players:
        photo = str(p.get("photo", "") or "").strip()
        photos[p.get("id")] = photo.rsplit(".", 1)[0] if photo else ""
    df["photo_code"] = df["id"].map(photos).fillna("")
    df["image_url"] = df["photo_code"].map(lambda x: f"https://resources.premierleague.com/premierleague25/photos/players/500x500/{x}.png" if x else "")
    return data, fixtures, df, teams

with st.spinner("Henter ferske FPL-data..."):
    try:
        data, fixtures, df, teams = get_analysis()
        data_loaded = True
    except Exception as exc:
        data_loaded = False
        st.error(f"Kunne ikke hente FPL-data: {exc}")

with st.sidebar:
    st.header("⚙️ Innstillinger")
    budget = st.number_input("Budsjett (£m)", min_value=80.0, max_value=110.0, value=100.0, step=0.5)
    ownership_limit = st.slider("Differential maks. eierskap (%)", 1, 30, 10)
    st.divider()
    st.subheader("🧠 Mitt FPL-lag")
    saved_entry = str(st.session_state.get("fpl_entry_id", ""))
    entry_text = st.text_input("FPL Team ID", value=saved_entry, placeholder="F.eks. 1234567", help="Bruk tallet i URL-en til FPL-laget ditt. Eksempel: /entry/1234567/")
    if st.button("📥 Hent mitt FPL-lag", use_container_width=True, type="primary"):
        cleaned = entry_text.strip()
        if not cleaned.isdigit() or int(cleaned) <= 0:
            st.error("Skriv inn en gyldig FPL Team ID, f.eks. 1234567.")
        else:
            st.session_state["fpl_entry_id"] = cleaned
            st.rerun()
    free_transfers_manual = st.number_input("Free transfers", min_value=1, max_value=5, value=1, step=1)
    bank_manual = st.number_input("Bank (£m)", min_value=0.0, max_value=20.0, value=0.0, step=0.1)
    if st.button("🔄 Oppdater FPL-data", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    st.divider()
    st.caption("Live data fra Fantasy Premier League API")
    st.caption("Data cache: 15 minutter")

if not data_loaded:
    st.stop()

current_gw = current_gameweek(data)
players_count = len(df)
avg_points = float(df.expected_gw_points.mean())
top_player = df.sort_values("expected_gw_points", ascending=False).iloc[0]

c1,c2,c3,c4=st.columns(4)
c1.metric("Spillere analysert", players_count)
c2.metric("Snitt forventede poeng", f"{avg_points:.2f}")
c3.metric("Beste projeksjon", str(top_player.name))
c4.metric(f"Forventede poeng GW{current_gw}", f"{top_player.expected_gw_points:.2f}")

def esc(v): return html.escape(str(v))
def initials(p):
    parts=[x for x in str(p.get("name","?")).replace("-"," ").split() if x]
    return "".join(x[0] for x in parts[:2]).upper() or "?"
def image_tag(p,size=72,bench=False):
    url=str(p.get("image_url","") or "").strip()
    cls="bench-avatar-fallback" if bench else "player-avatar-fallback"
    if url:
        fallback=initials(p)
        return f'<img src="{esc(url)}" width="{size}" height="{size}" loading="lazy" alt="{esc(p.get("name",""))}" onerror="this.outerHTML=\'<span class="{cls}">{fallback}</span>\'">'
    return f'<span class="{cls}">{esc(initials(p))}</span>'
def player_card(p,locked=False):
    badge='<div class="locked-badge">🔒 LÅST</div>' if locked else ''
    return f'<div class="player-card">{image_tag(p)}<div class="name">{esc(p.get("name","?"))}</div><div class="team">{esc(p.get("team_name","?"))}</div><div class="meta">£{float(p.get("price",0)):.1f}m · {float(p.get("expected_gw_points",0)):.2f} p</div>{badge}</div>'
def bench_card(p):
    return f'<div class="bench-card">{image_tag(p,58,True)}<div class="name">{esc(p.get("name","?"))}</div><div class="meta">{esc(p.get("team_name","?"))} · {esc(p.get("position","?"))}</div><div class="meta">£{float(p.get("price",0)):.1f}m · {float(p.get("expected_gw_points",0)):.2f}</div></div>'
FORMATIONS={"3-4-3":"3 forsvar · 4 midtbane · 3 angrep","3-5-2":"3 forsvar · 5 midtbane · 2 angrep","4-3-3":"4 forsvar · 3 midtbane · 3 angrep","4-4-2":"4 forsvar · 4 midtbane · 2 angrep","4-5-1":"4 forsvar · 5 midtbane · 1 angrep","5-2-3":"5 forsvar · 2 midtbane · 3 angrep","5-3-2":"5 forsvar · 3 midtbane · 2 angrep","5-4-1":"5 forsvar · 4 midtbane · 1 angrep"}
def infer_formation(xi):
    c=Counter(p["position"] for p in xi); k=f'{c.get("DEF",0)}-{c.get("MID",0)}-{c.get("FWD",0)}'; return k if k in FORMATIONS else "4-4-2"
def formation_shape(f):
    d,m,a=[int(x) for x in f.split("-")]; return {"GKP":1,"DEF":d,"MID":m,"FWD":a}
PLAYER_LOOKUP=df.set_index("id").to_dict("index")
def player_label(pid):
    p=PLAYER_LOOKUP.get(pid,{}); return f'{p.get("name","?")} · {p.get("team_name","?")} · £{float(p.get("price",0)):.1f}m'

def render_static_pitch(xi,formation,locked_ids=None,title="STARTING XI",key="best-pitch"):
    locked_ids=set(locked_ids or []); by={p:[] for p in ["GKP","DEF","MID","FWD"]}
    for p in xi: by[p["position"]].append(p)
    shape=formation_shape(formation)
    with st.container(key=key):
        st.markdown(f'<div class="pitch-formation">{esc(title)}</div>',unsafe_allow_html=True)
        g=st.columns([1,2,1])
        with g[1]:
            p=by["GKP"][:1]; st.markdown(f'<div class="pitch-slot">{player_card(p[0],p[0]["id"] in locked_ids) if p else ""}</div>',unsafe_allow_html=True)
        for pos in ["DEF","MID"]:
            cols=st.columns(4,gap="small")
            for i,col in enumerate(cols):
                with col:
                    p=by[pos][i] if i<len(by[pos]) and i<shape[pos] else None
                    st.markdown(f'<div class="pitch-slot">{player_card(p,p["id"] in locked_ids) if p else ""}</div>',unsafe_allow_html=True)
        f=by["FWD"][:shape["FWD"]]
        cols=st.columns([1,2,1] if len(f)==1 else [1,1,1])
        if len(f)==1:
            with cols[1]: st.markdown(f'<div class="pitch-slot">{player_card(f[0],f[0]["id"] in locked_ids)}</div>',unsafe_allow_html=True)
        else:
            for i,p in enumerate(f):
                with cols[i]: st.markdown(f'<div class="pitch-slot">{player_card(p,p["id"] in locked_ids)}</div>',unsafe_allow_html=True)

def render_bench(bench):
    cols=st.columns(4,gap="small")
    for i,p in enumerate(bench[:4]):
        with cols[i]: st.markdown(bench_card(p),unsafe_allow_html=True)

def captain_cards(xi):
    if len(xi)<2:return
    cap=max(xi,key=lambda x:x.get("captain_score",0)); vice=max([x for x in xi if x["id"]!=cap["id"]],key=lambda x:x.get("captain_score",0))
    a,b=st.columns(2)
    for col,title,p in [(a,"KAPTEIN",cap),(b,"VICE-CAPTAIN",vice)]:
        with col: st.markdown(f'<div class="captain-card"><div class="captain-title">{title}</div>{player_card(p)}<div>Forventet: <b>{float(p["expected_gw_points"]):.2f}</b> poeng</div></div>',unsafe_allow_html=True)

# Manager data: only query FPL when a valid Team ID has been explicitly saved.
manager_entry=None; manager_picks=None; manager_ids=[]; manager_bank=bank_manual
entry_id_text=str(st.session_state.get("fpl_entry_id", "")).strip()
if entry_id_text.isdigit() and int(entry_id_text)>0:
    try:
        manager_entry, manager_picks = load_manager(int(entry_id_text), current_gw)
        manager_ids=[int(x["element"]) for x in manager_picks.get("picks",[])][:15]
        if manager_entry.get("last_deadline_bank") is not None and bank_manual==0:
            manager_bank=float(manager_entry["last_deadline_bank"])/10.0
    except Exception as exc:
        st.sidebar.error(f"Fant ikke FPL-laget med ID {entry_id_text}. Sjekk at ID-en er riktig og at laget er registrert i FPL.")

if manager_ids:
    df["selling_price"]=df["price"]
    pick_map={int(x["element"]):x for x in manager_picks.get("picks",[])}
    df["selling_price"]=df.apply(lambda r: float(pick_map.get(int(r.id),{}).get("selling_price",r.price))/10.0 if pick_map.get(int(r.id),{}).get("selling_price") is not None and float(pick_map.get(int(r.id),{}).get("selling_price"))>20 else float(pick_map.get(int(r.id),{}).get("selling_price",r.price)),axis=1)
    team_df=df[df.id.isin(manager_ids)].copy()
    if manager_entry and manager_entry.get("last_deadline_bank") is not None and bank_manual==0:
        manager_bank=float(manager_entry["last_deadline_bank"])/10.0
else:
    team_df=pd.DataFrame()

# Navigation — Gameweek Plan is intentionally the first/default tab.
TABS=["🧠 Gameweek plan","🏆 Beste lag","🔄 Transfers","©️ Kapteiner","🔥 Differentials","💰 Best value","🧩 Bygg rundt mine spillere"]
tab1,tab2,tab3,tab4,tab5,tab6,tab7=st.tabs(TABS, default="🧠 Gameweek plan")

with tab1:
    st.header(f"🧠 Gameweek {current_gw} Decision Engine")
    st.caption("Målet er maksimal forventet totalpoeng over sesongen – ikke bare å finne den beste spilleren denne runden.")
    if not manager_ids:
        st.info("Legg inn FPL Team ID i sidepanelet og trykk «Hent mitt FPL-lag». Når laget er hentet, bruker Gameweek Plan ditt faktiske 15-mannslag.")
        st.markdown("**Motoren er klar til å bruke:** 6-GW projeksjon · transferkostnad · 1/2 FT · transfer timing · captain/vice · Wildcard · Free Hit · Bench Boost · Triple Captain.")
    else:
        with st.spinner("Simulerer de neste 6 Gameweeks..."):
            try:
                summary=decision_summary(df,fixtures,manager_ids,float(budget),float(manager_bank),int(free_transfers_manual),current_gw,horizon=6)
                best=summary["transfers"][0] if summary["transfers"] else None
                two=summary["two_transfers"]
                c1,c2,c3,c4=st.columns(4)
                c1.metric("GW-poeng nå",f'{summary["current"]["by_gw"].get(current_gw,0):.1f}')
                c2.metric("6 GW projeksjon",f'{summary["current"]["total"]:.1f}')
                c3.metric("Free transfers",int(free_transfers_manual))
                c4.metric("Bank",f'£{manager_bank:.1f}m')
                if best:
                    cls="green" if best["net_gain"]>0 else "yellow"
                    st.markdown(f'<div class="decision"><h3>🎯 BESTE TRANSFER: <span class="{cls}">{esc(best["out"])} → {esc(best["in"])}</span></h3><div>Forventet gevinst over 6 GW: <b>{best["projected_gain"]:+.2f}</b> · Transferkostnad: <b>-{best["hit"]}</b> · Netto: <b>{best["net_gain"]:+.2f}</b></div><div class="muted small">Motoren velger dette bare når forventet gevinst forsvarer transferen.</div></div>',unsafe_allow_html=True)
                else: st.info("Ingen realistisk transfer funnet med nåværende bank og lag.")
                if two:
                    st.markdown(f'<div class="decision"><h3>🔁 2 transfers</h3><div>{esc(two["first"]["out"])} → {esc(two["first"]["in"])} + {esc(two["second"]["out"])} → {esc(two["second"]["in"])}</div><div>Forventet ekstra: <b>{two["net_gain"]:+.2f}</b> over 6 GW.</div></div>',unsafe_allow_html=True)
                st.subheader("📈 Lagets projeksjon")
                proj_rows=[{"GW":gw,"Forventet XI":round(v,1)} for gw,v in summary["current"]["by_gw"].items()]
                st.dataframe(pd.DataFrame(proj_rows),use_container_width=True,hide_index=True)
                st.subheader("💡 Skal vi vente med transferen?")
                if best and best["net_gain"]<=0.5: st.warning("HOLD. Modellen mener at transferen ikke betaler seg nok akkurat nå. Vent og la neste GW-data komme inn.")
                elif best: st.success("TRANSFER. Modellen ser positiv nettoverdi etter transferkostnaden.")
                st.subheader("🧩 Chip planner")
                chip_df=summary["chips"].copy()
                for chip,col in [("TC","tc_value"),("BB","bb_value"),("FH","fh_value")]:
                    if len(chip_df):
                        r=chip_df.loc[chip_df[col].idxmax()]
                        st.markdown(f'**{chip}:** beste beregnede vindu er **GW{int(r.gw)}** · verdi **+{float(r[col]):.1f} poeng**')
                wc=summary["wildcard"]
                if wc: st.markdown(f'**Wildcard:** +{wc["gain"]:.1f} forventede poeng mot nåværende lag over de neste 6 GW.')
                st.dataframe(chip_df.rename(columns={"gw":"GW","tc_value":"TC-verdi","bb_value":"BB-verdi","fh_value":"Free Hit-verdi","double_teams":"DGW-lag","active_teams":"Lag med kamp"}),use_container_width=True,hide_index=True)
                st.caption("Chipverdiene er scenarioberegninger. Motoren skal oppdatere dem hver Gameweek når nye resultater, skader, minutter og underliggende FPL-data kommer inn.")
            except Exception as exc:
                st.error(f"Decision Engine feilet: {exc}")

with tab2:
    st.header("🏆 Beste 15-mannstropp")
    result=select_squad(df,budget)
    if result:
        score,cost,squad,xi,bench=result
        a,b,c=st.columns(3); a.metric("Troppskostnad",f"£{cost:.1f}m"); b.metric("Budsjett igjen",f"£{budget-cost:.1f}m"); c.metric("Forventede XI-poeng",f'{sum(float(x["expected_gw_points"]) for x in xi):.1f}')
        st.subheader("🏟️ Starting XI"); render_static_pitch(xi,infer_formation(xi),title="STARTING XI",key="best-pitch")
        st.subheader("🪑 Benk"); render_bench(bench)
        st.subheader("🎯 Kaptein og visekaptein"); captain_cards(xi)

with tab3:
    st.header("🔄 Beste transfermål")
    positions=["GKP","DEF","MID","FWD"]; pos=st.multiselect("Posisjon",positions,default=positions); mins=st.slider("Minimum forventede minutter",0,90,60,5)
    x=df[df.position.isin(pos)&(df.expected_minutes>=mins)].sort_values(["transfer_score","expected_gw_points"],ascending=False).head(30)
    cols=["name","team_name","position","price","ownership","expected_minutes","expected_gw_points","value","fixture_next3","transfer_score","recommendation"]
    st.dataframe(x[[c for c in cols if c in x.columns]],use_container_width=True,hide_index=True)

with tab4:
    st.header("©️ Kapteinguide")
    x=df[df.expected_minutes>=60].sort_values(["captain_score","expected_gw_points"],ascending=False).head(20)
    if len(x): st.success(f'🥇 Førstevalg: **{x.iloc[0]["name"]}** · {x.iloc[0]["expected_gw_points"]:.2f} forventede poeng')
    st.dataframe(x[[c for c in ["name","team_name","position","price","expected_minutes","expected_gw_points","fixture_next3","captain_score"] if c in x.columns]],use_container_width=True,hide_index=True)

with tab5:
    st.header("🔥 Differentials")
    x=df[(df.ownership<=ownership_limit)&(df.expected_minutes>=60)].sort_values(["differential_score","expected_gw_points"],ascending=False).head(30)
    st.dataframe(x[[c for c in ["name","team_name","position","price","ownership","expected_minutes","expected_gw_points","value","fixture_next3","differential_score"] if c in x.columns]],use_container_width=True,hide_index=True)

with tab6:
    st.header("💰 Best value")
    x=df[df.expected_minutes>=60].sort_values(["value","expected_gw_points"],ascending=False).head(30)
    st.dataframe(x[[c for c in ["name","team_name","position","price","ownership","expected_minutes","expected_gw_points","value","fixture_next3"] if c in x.columns]],use_container_width=True,hide_index=True)

with tab7:
    st.header("🧩 Bygg laget rundt mine spillere")
    st.caption("Start med en tom 4–4–2-bane. Trykk + på posisjonen du vil fylle. Listen filtreres automatisk til riktig posisjon.")
    formation="4-4-2"; shape=formation_shape(formation)
    valid=["GKP_0"]+[f"DEF_{i}" for i in range(4)]+[f"MID_{i}" for i in range(4)]+[f"FWD_{i}" for i in range(2)]
    if "build_pitch_slots" not in st.session_state: st.session_state.build_pitch_slots={k:None for k in valid}
    else:
        old=st.session_state.build_pitch_slots; st.session_state.build_pitch_slots={k:old.get(k) for k in valid}
    if "build_active_slot" not in st.session_state: st.session_state.build_active_slot=None
    slots=st.session_state.build_pitch_slots; selected_ids=[x for x in slots.values() if x is not None]; selected_set=set(selected_ids)
    if st.button("♻️ Tøm banen",key="clear_build_pitch"):
        st.session_state.build_pitch_slots={k:None for k in valid}; st.session_state.build_active_slot=None; st.session_state.pop("build_result",None); st.rerun()
    with st.container(key="build-pitch"):
        st.markdown('<div class="pitch-formation">4-4-2 · TOM BANE</div>',unsafe_allow_html=True)
        g=st.columns([1,2,1])
        with g[1]:
            pid=slots["GKP_0"]
            if pid is None:
                if st.button("＋",key="plus_GKP_0"): st.session_state.build_active_slot="GKP_0"; st.rerun()
            else:
                st.markdown(player_card(PLAYER_LOOKUP[pid],True),unsafe_allow_html=True)
                if st.button("✕ Fjern",key="remove_GKP_0"): st.session_state.build_pitch_slots["GKP_0"]=None; st.rerun()
        for posn,n in [("DEF",4),("MID",4)]:
            cols=st.columns(4)
            for i,col in enumerate(cols):
                with col:
                    k=f"{posn}_{i}"; pid=slots[k]
                    if pid is None:
                        if st.button("＋",key=f"plus_{k}"): st.session_state.build_active_slot=k; st.rerun()
                    else:
                        st.markdown(player_card(PLAYER_LOOKUP[pid],True),unsafe_allow_html=True)
                        if st.button("✕ Fjern",key=f"remove_{k}"): st.session_state.build_pitch_slots[k]=None; st.rerun()
        cols=st.columns([1,2,1])
        for i in range(2):
            with cols[i+1 if i==0 else i]:
                k=f"FWD_{i}"; pid=slots[k]
                if pid is None:
                    if st.button("＋",key=f"plus_{k}"): st.session_state.build_active_slot=k; st.rerun()
                else:
                    st.markdown(player_card(PLAYER_LOOKUP[pid],True),unsafe_allow_html=True)
                    if st.button("✕ Fjern",key=f"remove_{k}"): st.session_state.build_pitch_slots[k]=None; st.rerun()
    active=st.session_state.build_active_slot
    if active:
        posn=active.split("_")[0]; available=[pid for pid in df[df.position==posn].id.tolist() if pid not in selected_set]
        pick=st.selectbox(f"Velg {posn}",[0]+available,format_func=lambda pid:"Velg spiller..." if pid==0 else player_label(pid),key=f"pick_{active}")
        a,b=st.columns(2)
        with a:
            if st.button("Legg spiller på banen",type="primary",disabled=pick==0,use_container_width=True): st.session_state.build_pitch_slots[active]=pick; st.session_state.build_active_slot=None; st.session_state.pop("build_result",None); st.rerun()
        with b:
            if st.button("Avbryt",use_container_width=True): st.session_state.build_active_slot=None; st.rerun()
    if selected_ids:
        selected_df=df[df.id.isin(selected_ids)]; cost=float(selected_df.price.sum()); counts=Counter(selected_df.position); clubs=Counter(selected_df.team_id); reasons=[]
        if cost>budget: reasons.append(f"Valgte spillere koster £{cost:.1f}m, mer enn budsjettet £{budget:.1f}m.")
        if max(clubs.values(),default=0)>3: reasons.append("Mer enn 3 spillere fra samme klubb.")
        for p,n in {"GKP":2,"DEF":5,"MID":5,"FWD":3}.items():
            if counts.get(p,0)>n: reasons.append(f"For mange {p}-spillere.")
        a,b,c=st.columns(3); a.metric("Låste spillere",len(selected_ids)); b.metric("Kostnad låste",f"£{cost:.1f}m"); c.metric("Budsjett igjen",f"£{budget-cost:.1f}m")
        for r in reasons: st.warning(r)
        if st.button("🧩 Bygg laget rundt mine spillere",type="primary",use_container_width=True,disabled=bool(reasons)):
            result=build_around_players(df,selected_ids,budget)
            if result: st.session_state.build_result=result; st.rerun()
            else: st.error("Fant ikke en gyldig 15-mannstropp rundt valgene dine.")
        stored=st.session_state.get("build_result")
        if stored:
            score,cost,squad,_,_=stored; display_xi=build_display_xi(squad,selected_ids,formation)
            if display_xi:
                xi_ids={p["id"] for p in display_xi}; bench=[p for p in squad if p["id"] not in xi_ids]
                st.subheader("🏟️ Ditt lag"); render_static_pitch(display_xi,formation,selected_ids,title="4-4-2 · DITT LAG",key="built-pitch")
                st.subheader("🪑 Benk"); render_bench(bench); st.subheader("🎯 Kaptein og visekaptein"); captain_cards(display_xi)
    else: st.info("Banen er tom. Trykk + på en posisjon for å starte.")

st.divider(); st.caption("FPL Analyzer · Live FPL-data · Decision Engine bruker forventningsmodeller og er ikke en garanti for faktiske poeng.")
