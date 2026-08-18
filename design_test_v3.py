import html
import streamlit as st
import pandas as pd

from main import load_fpl, load_fixtures, build_players, assign_recommendations, select_squad

st.set_page_config(page_title="FPL Analyzer – V2.1 Design Test", page_icon="⚽", layout="wide")

st.markdown("""
<style>
.block-container{max-width:1500px;padding-top:1.2rem;padding-bottom:3rem}
.hero{padding:1.35rem 1.6rem;border-radius:22px;background:linear-gradient(135deg,#111827,#182235 55%,#202b3f);border:1px solid rgba(255,255,255,.08);margin-bottom:1.1rem}
.hero-title{font-size:2.15rem;font-weight:850}.hero-sub{margin-top:.35rem;opacity:.68;font-size:.95rem}
.pitch-wrap{border-radius:24px;padding:18px;background:linear-gradient(180deg,#173f31,#0e2f26);border:1px solid rgba(255,255,255,.1);box-shadow:0 20px 50px rgba(0,0,0,.28);margin:.6rem 0 1.3rem}
.pitch{position:relative;min-height:650px;border-radius:18px;overflow:hidden;background:repeating-linear-gradient(0deg,rgba(255,255,255,.025) 0 72px,rgba(255,255,255,.045) 72px 144px),linear-gradient(90deg,rgba(255,255,255,.025) 0 50%,transparent 50% 100%);border:2px solid rgba(255,255,255,.28)}
.pitch:before{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(255,255,255,.24)}
.pitch:after{content:"";position:absolute;left:50%;top:50%;width:110px;height:110px;transform:translate(-50%,-50%);border:1px solid rgba(255,255,255,.24);border-radius:50%}
.pitch-zone{position:relative;z-index:2;display:flex;justify-content:space-evenly;align-items:center;padding:12px 2%;min-height:130px}
.pitch-zone-label{text-align:center;color:rgba(255,255,255,.45);font-size:.7rem;text-transform:uppercase;letter-spacing:.12em;margin-bottom:3px}
.slot{width:112px;text-align:center;color:white}
.slot-plus{width:68px;height:68px;border-radius:50%;border:2px dashed rgba(255,255,255,.55);background:rgba(255,255,255,.08);color:white;font-size:2rem;line-height:60px;margin:auto;cursor:pointer}
.slot-name{font-size:.72rem;font-weight:700;margin-top:5px}.slot-pos{font-size:.65rem;opacity:.55}
.player-photo{width:68px;height:68px;object-fit:contain;border-radius:50%;background:rgba(255,255,255,.1);border:2px solid rgba(255,255,255,.75)}
.player-badge{margin:-8px auto 0;width:94px;padding:5px 6px 6px;border-radius:9px;background:rgba(10,17,28,.93);border:1px solid rgba(255,255,255,.14);color:white}
.pname{font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.pmeta{opacity:.62;font-size:.68rem}.pill{display:inline-block;padding:.2rem .5rem;border-radius:999px;background:rgba(255,255,255,.07);font-size:.72rem;margin-right:.25rem}
.locked{border:1px solid rgba(239,95,88,.35);background:rgba(239,95,88,.06);border-radius:15px;padding:.75rem 1rem;margin-bottom:.5rem}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=900)
def get_analysis():
    data, teams, raw_players = load_fpl()
    fixtures = load_fixtures()
    df = assign_recommendations(build_players(raw_players, teams, fixtures))
    photos = {p.get("id"): p.get("photo") for p in raw_players}
    df["photo"] = df["id"].map(photos)
    return df, teams

def photo_url(photo):
    if not photo: return ""
    stem=str(photo).rsplit(".",1)[0]
    return f"https://resources.premierleague.com/premierleague/photos/players/250x250/p{stem}.png"

def player_html(p):
    return f'''<div class="slot"><img class="player-photo" src="{photo_url(p.get('photo'))}"><div class="player-badge"><div class="pname">{html.escape(str(p.get('name','?')))}</div><div class="pmeta">{html.escape(str(p.get('team_name','?')))} · £{float(p.get('price',0)):.1f}m</div><div style="font-weight:800">{float(p.get('expected_gw_points',0)):.2f} pts</div></div></div>'''

with st.sidebar:
    st.header("⚙️ Innstillinger")
    budget=st.number_input("Budsjett (£m)",80.0,100.0,100.0,.5)
    if st.button("🔄 Oppdater FPL-data",use_container_width=True): st.cache_data.clear(); st.rerun()

st.markdown('<div class="hero"><div class="hero-title">⚽ FPL Analyzer</div><div class="hero-sub">V2.1 Design Test · Tom bane · Posisjonsstyrte spillervalg</div></div>',unsafe_allow_html=True)

with st.spinner("Henter ferske FPL-data..."):
    try: df,teams=get_analysis()
    except Exception as exc: st.error(f"Kunne ikke hente FPL-data: {exc}"); st.stop()

st.markdown("## 🧩 Bygg laget rundt mine spillere")
st.caption("Start med en helt tom bane. Trykk + på plassen du ønsker å fylle. Spillerlisten filtreres automatisk til riktig posisjon.")

# Formation is selected first. The pitch starts completely empty.
formation=st.selectbox("Formasjon",["3-4-3","3-5-2","4-3-3","4-4-2","4-5-1","5-3-2","5-4-1"],index=2)
d,m,f=map(int,formation.split('-'))
slot_counts={"GKP":1,"DEF":d,"MID":m,"FWD":f}

# Store one selected player id per visual slot.
for pos,count in slot_counts.items():
    for i in range(count):
        st.session_state.setdefault(f"slot_{pos}_{i}",None)

lookup=df.set_index("id").to_dict("index")
used_ids={v for k,v in st.session_state.items() if k.startswith("slot_") and v is not None}

# Each slot has a visible +/player card. Clicking the button reveals ONLY that position's selector.
for pos,label in [("FWD","SPISSER"),("MID","MIDTBANE"),("DEF","FORSVAR"),("GKP","KEEPER")]:
    count=slot_counts[pos]
    st.markdown(f'<div class="pitch-zone-label">{label}</div>',unsafe_allow_html=True)
    cols=st.columns(count)
    for i,col in enumerate(cols):
        key=f"slot_{pos}_{i}"
        with col:
            pid=st.session_state.get(key)
            if pid is None:
                if st.button("+",key=f"plus_{pos}_{i}",help=f"Velg {label.lower()}"):
                    st.session_state[f"open_{pos}_{i}"]=True
                st.markdown(f'<div style="text-align:center;opacity:.55;font-size:.7rem">{label.title()} {i+1}</div>',unsafe_allow_html=True)
            else:
                p=lookup[pid]
                st.markdown(player_html(p),unsafe_allow_html=True)
                if st.button("Bytt",key=f"change_{pos}_{i}"):
                    st.session_state[f"open_{pos}_{i}"]=True
            if st.session_state.get(f"open_{pos}_{i}",False):
                candidates=df[(df["position"]==pos) & (~df["id"].isin(used_ids-{pid} if pid else used_ids))].sort_values("expected_gw_points",ascending=False)
                options=[None]+candidates["id"].tolist()
                def fmt(x):
                    if x is None: return "Velg spiller..."
                    p=lookup[x]; return f"{p['name']} · {p['team_name']} · £{p['price']:.1f}m"
                choice=st.selectbox(f"Velg {label.lower()}",options,format_func=fmt,key=f"select_{pos}_{i}")
                if choice is not None:
                    st.session_state[key]=int(choice)
                    st.session_state[f"open_{pos}_{i}"]=False
                    st.rerun()

# Visual pitch wrapper around the interactive slot rows.
st.markdown("<div class='pitch-wrap'><div class='pitch'>",unsafe_allow_html=True)
st.markdown("</div></div>",unsafe_allow_html=True)

selected_ids=[st.session_state[f"slot_{pos}_{i}"] for pos,count in slot_counts.items() for i in range(count) if st.session_state.get(f"slot_{pos}_{i}") is not None]
selected_ids=list(dict.fromkeys(selected_ids))
selected=df[df["id"].isin(selected_ids)]
cost=float(selected["price"].sum()) if len(selected) else 0
st.markdown(f'<div class="metric-card"><div class="metric-label">VALGTE SPILLERE</div><div class="metric-value">{len(selected_ids)} · £{cost:.1f}m brukt · £{budget-cost:.1f}m igjen</div></div>',unsafe_allow_html=True)

if selected_ids:
    st.markdown("### 🔒 Dine valgte spillere")
    for _,p in selected.iterrows():
        st.markdown(f'<div class="locked">🔒 <b>{html.escape(str(p["name"]))}</b> · {p["team_name"]} · {p["position"]} · £{p["price"]:.1f}m</div>',unsafe_allow_html=True)

if st.button("🧩 Bygg laget rundt mine spillere",type="primary",use_container_width=True,disabled=not selected_ids):
    with st.spinner("Optimaliserer resten av laget..."):
        result=select_squad(df,budget,locked_ids=selected_ids)
    if not result:
        st.error("Fant ingen gyldig tropp med disse valgte spillerne. Prøv en annen kombinasjon eller formasjon.")
    else:
        score,cost,squad,xi,bench=result
        st.success("Laget er bygget rundt dine valgte spillere.")
        st.write("**Modellen fyller nå resten av troppen basert på V1.9-analysen.**")
        st.dataframe(pd.DataFrame(squad)[["name","team_name","position","price","expected_gw_points"]],use_container_width=True,hide_index=True)

st.caption("V2.1 Design Test · Hovedappen er ikke endret.")
