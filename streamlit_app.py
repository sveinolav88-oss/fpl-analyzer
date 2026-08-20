# Main Streamlit entrypoint. The full application lives in streamlit_app_v2.py.
source = open("streamlit_app_v2.py", encoding="utf-8").read()

# Use the fast bounded optimizer for both the normal Best Team calculation and
# "Build around my players". The previous beam was too large for Streamlit and
# could generate millions of Python objects on one button click.
source = source.replace(
    'from main import load_fpl, load_fixtures, build_players, assign_recommendations, select_squad, build_around_players',
    'from main import load_fpl, load_fixtures\nfrom fpl_model_v2 import build_players, assign_recommendations\nfrom fast_squad_optimizer import select_squad, build_around_players, _valid, _objective, _starting_xi',
)

# Use a calibrated scoring model. FPL ep_next remains a strong prior, but it
# is no longer double-discounted by the minutes model.
source = source.replace(
    'c4.metric(f"Forventede poeng GW{current_gw}", f"{top_player.expected_gw_points:.2f}")',
    'c4.metric(f"Beste spillerprognose GW{current_gw}", f"{top_player.expected_gw_points:.2f}")',
)
source = source.replace('6-GW projeksjon', '4-GW projeksjon')
source = source.replace('de neste 6 Gameweeks', 'de neste 4 Gameweeks')
source = source.replace('over 6 GW', 'over 4 GW')
source = source.replace('neste 6 GW', 'neste 4 GW')
source = source.replace('horizon=6', 'horizon=4')


source = source.replace(
    'cols=st.columns([1,2,1])\n        for i in range(2):\n            with cols[i+1 if i==0 else i]:',
    'cols=st.columns([1,1,1,1])\n        for i in range(2):\n            with cols[i+1]:'
)

# FPL picks can legitimately return 404 before the current Gameweek deadline.
source = source.replace(
    'from decision_engine import current_gameweek, load_manager, decision_summary',
    '''from decision_engine import current_gameweek, load_manager as _load_manager, decision_summary

def load_manager(entry_id, event):
    try:
        return _load_manager(entry_id, event)
    except Exception as exc:
        message = str(exc)
        if "HTTP 404" in message and "/picks/" in message:
            from decision_engine import _get
            entry = _get(f"/entry/{int(entry_id)}/")
            return entry, None
        raise'''
)
source = source.replace(
    'manager_ids=[int(x["element"]) for x in manager_picks.get("picks",[])][:15]',
    'manager_ids=[int(x["element"]) for x in manager_picks.get("picks",[])][:15] if manager_picks else []\n        if manager_picks is None:\n            st.sidebar.info("FPL-laget er funnet. FPL har ikke publisert spillerlisten for denne Gameweeken ennå. Den hentes automatisk når picks blir tilgjengelig.")'
)
source = source.replace(
    'st.sidebar.error(f"Fant ikke FPL-laget med ID {entry_id_text}. Sjekk at ID-en er riktig og at laget er registrert i FPL.")',
    'st.sidebar.error(f"Kunne ikke hente FPL-laget {entry_id_text}. {type(exc).__name__}: {exc}")'
)

# Use a 4-GW rolling horizon for transfer decisions.
source = source.replace('6-GW projeksjon', '4-GW projeksjon')
source = source.replace('de neste 6 Gameweeks', 'de neste 4 Gameweeks')
source = source.replace('horizon=6', 'horizon=4')
source = source.replace('6 GW projeksjon', '4 GW projeksjon')
source = source.replace('over 6 GW', 'over 4 GW')
source = source.replace('neste 6 GW', 'neste 4 GW')

# Never hide an unexpected fifth bench player.
source = source.replace(
    'def render_bench(bench):\n    cols=st.columns(4,gap="small")\n    for i,p in enumerate(bench[:4]):\n        with cols[i]: st.markdown(bench_card(p),unsafe_allow_html=True)',
    '''def render_bench(bench):
    if not bench:
        return
    cols=st.columns(min(4,len(bench)),gap="small")
    for i,p in enumerate(bench):
        with cols[i % len(cols)]: st.markdown(bench_card(p),unsafe_allow_html=True)
'''
)

# Add a hard UI-level squad audit.
source = source.replace(
    'score,cost,squad,xi,bench=result\n        a,b,c=st.columns(3);',
    '''score,cost,squad,xi,bench=result
        actual_cost=round(sum(float(x.get("price",0)) for x in squad),1)
        if len(squad)!=15 or actual_cost>budget+1e-9:
            st.error(f"⚠️ Ugyldig anbefalt tropp: {len(squad)} spillere · £{actual_cost:.1f}m. FPL krever 15 spillere og maks £{budget:.1f}m.")
            st.stop()
        a,b,c=st.columns(3);'''
)
source = source.replace(
    'score,cost,squad,_,_=stored; display_xi=build_display_xi(squad,selected_ids,formation)',
    '''score,cost,squad,_,_=stored
            actual_cost=round(sum(float(x.get("price",0)) for x in squad),1)
            if len(squad)!=15 or actual_cost>budget+1e-9:
                st.error(f"⚠️ Optimizer returnerte en ugyldig tropp: {len(squad)} spillere · £{actual_cost:.1f}m. Resultatet vises ikke.")
                st.stop()
            display_xi=build_display_xi(squad,selected_ids,formation)'''
)

# Transparent explanation of the exact optimizer result.
source = source.replace(
    'with tab2:\n    st.header("🏆 Beste 15-mannstropp")',
    '''def render_optimizer_explanation(df, squad, xi, bench, budget):
    squad_ids={int(x["id"]) for x in squad}
    budget_units=int(round(float(budget)*10))
    cost_units=sum(int(round(float(x.get("price",0))*10)) for x in squad)
    remaining_units=budget_units-cost_units
    xi_points=sum(float(x.get("expected_gw_points",0)) for x in xi)
    bench_points=sum(float(x.get("expected_gw_points",0)) for x in bench)
    availability=sum(max(0,min(1,float(x.get("expected_minutes",0))/90)) for x in bench)
    objective=xi_points + .18*bench_points + .05*availability

    st.markdown("### 🧠 Hvorfor valgte roboten dette laget?")
    m1,m2,m3,m4=st.columns(4)
    m1.metric("Forventede XI-poeng",f"{xi_points:.1f}")
    m2.metric("Benkens forventede poeng",f"{bench_points:.1f}")
    m3.metric("Budsjett brukt",f"£{cost_units/10:.1f}m")
    m4.metric("Budsjett igjen",f"£{remaining_units/10:.1f}m")
    st.info("Modellen prioriterer forventede GW-poeng i startelleveren. Benken gir en mindre sekundær score, og modellen kontrollerer samtidig budsjett, 15 spillere, posisjonskrav og maks. 3 spillere fra samme klubb.")

    upgrades=[]
    for old in squad:
        old_id=int(old["id"]); pos=old.get("position"); old_price=float(old.get("price",0))
        candidates=df[(df["position"]==pos) & (~df["id"].isin(squad_ids))].copy()
        candidates=candidates[(candidates["price"]>old_price) & (candidates["price"]<=old_price + remaining_units/10 + 1e-9)]
        candidates=candidates.sort_values("expected_gw_points",ascending=False).head(12)
        for _,cand in candidates.iterrows():
            trial=list(squad)
            old_index=next((i for i,p in enumerate(trial) if int(p["id"])==old_id),None)
            if old_index is None: continue
            trial[old_index]=cand.to_dict()
            if not _valid(trial,budget_units): continue
            trial_xi,_=_starting_xi(trial)
            delta=_objective(trial)-objective
            if delta>0.001:
                upgrades.append({
                    "Bytte":f"{old.get('name','?')} → {cand.get('name','?')}",
                    "Ekstra kostnad":f"£{float(cand.get('price',0))-old_price:.1f}m",
                    "Ny kostnad":f"£{sum(float(x.get('price',0)) for x in trial):.1f}m",
                    "Endring i modellscore":f"+{delta:.2f}",
                    "Forventede XI-poeng":f"{sum(float(x.get('expected_gw_points',0)) for x in trial_xi):.1f}",
                })
    if upgrades:
        upgrades=sorted(upgrades,key=lambda x:float(x["Endring i modellscore"].replace("+","")),reverse=True)[:8]
        st.markdown("#### 🔎 Nærmeste oppgraderinger")
        st.caption("Lovlige, dyrere én-spiller-bytter som er mulig med pengene som er igjen. Scoreøkningen vurderer hele troppen, ikke bare den nye spilleren.")
        st.dataframe(pd.DataFrame(upgrades),use_container_width=True,hide_index=True)
    else:
        st.success("Ingen testet, lovlig dyrere én-spiller-oppgradering med pengene som er igjen gir høyere totalscore. Ledig budsjett er derfor ikke automatisk et tegn på dårlig optimalisering.")

    with st.expander("Se hvordan modellen vurderer laget"):
        st.write(f"**Modellscore:** {objective:.2f}")
        st.write("**Primærfaktor:** forventede poeng i startelleveren.")
        st.write("**Sekundærfaktor:** 18 % av benkens forventede poeng + 5 % tilgjengelighet for benken.")
        st.write("**Harde regler:** 15 spillere · 2 GKP · 5 DEF · 5 MID · 3 FWD · maks 3 fra samme klubb · budsjettgrense.")
        st.write("**Viktig:** Pengene skal bare brukes dersom en lovlig kombinasjon gir høyere forventet totalscore.")

with tab2:
    st.header("🏆 Beste 15-mannstropp")'''
)
source = source.replace(
    'st.subheader("🪑 Benk"); render_bench(bench)',
    'st.subheader("🪑 Benk"); render_bench(bench)\n        render_optimizer_explanation(df,squad,xi,bench,budget)'
)

# Add a compact, consistent statistics panel below every completed pitch.
source = source.replace(
    '</style>',
    '''
.pitch-stats{margin:.35rem 0 1.2rem;padding:.9rem 1rem;border-radius:18px;border:1px solid rgba(255,255,255,.10);background:linear-gradient(135deg,rgba(31,41,55,.78),rgba(17,24,39,.92));box-shadow:0 8px 24px rgba(0,0,0,.14)}
.pitch-stats-title{font-size:.72rem;font-weight:850;letter-spacing:.10em;text-transform:uppercase;color:rgba(255,255,255,.60);margin-bottom:.55rem}.pitch-stat-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.55rem}.pitch-stat{padding:.55rem .65rem;border-radius:12px;background:rgba(255,255,255,.045);text-align:center}.pitch-stat .label{font-size:.67rem;color:rgba(255,255,255,.58)}.pitch-stat .value{font-size:1.02rem;font-weight:850;color:white;margin-top:.12rem}@media(max-width:800px){.pitch-stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>'''
)

# Keep the pitch itself aligned with the real football layout: attack at the
# top, defence below midfield, and the goalkeeper centered at the back/bottom.
old_pitch = '''def render_static_pitch(xi,formation,locked_ids=None,title="STARTING XI",key="best-pitch"):
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
'''
new_pitch = '''def render_pitch_line(players, locked_ids):
    players=list(players)
    if not players:
        return
    if len(players)==1:
        cols=st.columns([1,2,1],gap="small")
        targets=[cols[1]]
    else:
        cols=st.columns(len(players),gap="small")
        targets=cols
    for col,p in zip(targets,players):
        with col:
            st.markdown(f'<div class="pitch-slot">{player_card(p,p["id"] in locked_ids)}</div>',unsafe_allow_html=True)

def render_static_pitch(xi,formation,locked_ids=None,title="STARTING XI",key="best-pitch"):
    locked_ids=set(locked_ids or []); by={p:[] for p in ["GKP","DEF","MID","FWD"]}
    for p in xi: by[p["position"]].append(p)
    shape=formation_shape(formation)
    with st.container(key=key):
        st.markdown(f'<div class="pitch-formation">{esc(title)}</div>',unsafe_allow_html=True)
        # Football orientation: opponents' goal at the top, our goal at the bottom.
        render_pitch_line(by["FWD"][:shape["FWD"]],locked_ids)
        render_pitch_line(by["MID"][:shape["MID"]],locked_ids)
        render_pitch_line(by["DEF"][:shape["DEF"]],locked_ids)
        render_pitch_line(by["GKP"][:1],locked_ids)

def render_pitch_stats(xi,squad=None,bench=None,budget=None,cost=None,locked_ids=None):
    xi_points=sum(float(p.get("expected_gw_points",0)) for p in xi)
    squad_players=squad if squad is not None else xi
    squad_cost=sum(float(p.get("price",0)) for p in squad_players) if cost is None else float(cost)
    budget_left=(float(budget)-squad_cost) if budget is not None else None
    bench_points=sum(float(p.get("expected_gw_points",0)) for p in (bench or []))
    locked_count=len(set(locked_ids or []))
    title="Lagstatistikk" if not locked_count else "Lagstatistikk · låste valg"
    budget_text=f"£{budget_left:.1f}m" if budget_left is not None else "–"
    st.markdown(f"""<div class="pitch-stats"><div class="pitch-stats-title">{title}</div><div class="pitch-stat-grid"><div class="pitch-stat"><div class="label">Forventede XI-poeng</div><div class="value">{xi_points:.1f}</div></div><div class="pitch-stat"><div class="label">Benk forventet</div><div class="value">{bench_points:.1f}</div></div><div class="pitch-stat"><div class="label">Troppskostnad</div><div class="value">£{squad_cost:.1f}m</div></div><div class="pitch-stat"><div class="label">Budsjett igjen</div><div class="value">{budget_text}</div></div></div></div>""",unsafe_allow_html=True)
'''
source = source.replace(old_pitch,new_pitch)

# The empty build-around pitch uses the same orientation as the completed pitch.
old_build = '''    with st.container(key="build-pitch"):
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
'''
new_build = '''    with st.container(key="build-pitch"):
        st.markdown('<div class="pitch-formation">4-4-2 · TOM BANE</div>',unsafe_allow_html=True)
        # Attack at the top, defence below, goalkeeper centered at the back.
        for posn,n in [("FWD",2),("MID",4),("DEF",4)]:
            cols=st.columns(n,gap="small")
            for i,col in enumerate(cols):
                with col:
                    k=f"{posn}_{i}"; pid=slots[k]
                    if pid is None:
                        if st.button("＋",key=f"plus_{k}"): st.session_state.build_active_slot=k; st.rerun()
                    else:
                        st.markdown(player_card(PLAYER_LOOKUP[pid],True),unsafe_allow_html=True)
                        if st.button("✕ Fjern",key=f"remove_{k}"): st.session_state.build_pitch_slots[k]=None; st.rerun()
        g=st.columns([1,2,1])
        with g[1]:
            pid=slots["GKP_0"]
            if pid is None:
                if st.button("＋",key="plus_GKP_0"): st.session_state.build_active_slot="GKP_0"; st.rerun()
            else:
                st.markdown(player_card(PLAYER_LOOKUP[pid],True),unsafe_allow_html=True)
                if st.button("✕ Fjern",key="remove_GKP_0"): st.session_state.build_pitch_slots["GKP_0"]=None; st.rerun()
'''
source = source.replace(old_build,new_build)

# Add the statistics panel to the normal best-team view and build-around view.
source = source.replace(
    'render_optimizer_explanation(df,squad,xi,bench,budget)',
    'render_optimizer_explanation(df,squad,xi,bench,budget)\n        render_pitch_stats(xi,squad,bench,budget,cost)'
)
source = source.replace(
    'st.subheader("🪑 Benk"); render_bench(bench); st.subheader("🎯 Kaptein og visekaptein"); captain_cards(display_xi)',
    'st.subheader("🪑 Benk"); render_bench(bench); render_pitch_stats(display_xi,squad,bench,budget,cost,selected_ids); st.subheader("🎯 Kaptein og visekaptein"); captain_cards(display_xi)'
)

exec(source, globals())
