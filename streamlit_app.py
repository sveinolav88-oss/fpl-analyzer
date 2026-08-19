# Main Streamlit entrypoint. The full application lives in streamlit_app_v2.py.
source = open("streamlit_app_v2.py", encoding="utf-8").read()

# Use the fast bounded optimizer for both the normal Best Team calculation and
# "Build around my players". The previous beam was too large for Streamlit and
# could generate millions of Python objects on one button click.
source = source.replace(
    'from main import load_fpl, load_fixtures, build_players, assign_recommendations, select_squad, build_around_players',
    'from main import load_fpl, load_fixtures, build_players, assign_recommendations\nfrom fast_squad_optimizer import select_squad, build_around_players, _valid, _objective, _starting_xi',
)

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
            idx=next((i for i,p in enumerate(trial) if int(p["id"])==old_id),None)
            if idx is None: continue
            trial[idx]=cand.to_dict()
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

exec(source, globals())
