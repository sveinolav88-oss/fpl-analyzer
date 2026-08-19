# Main Streamlit entrypoint. The full application lives in streamlit_app_v2.py.
source = open("streamlit_app_v2.py", encoding="utf-8").read()

# Use the fast bounded optimizer for both the normal Best Team calculation and
# "Build around my players". The previous beam was too large for Streamlit and
# could generate millions of Python objects on one button click.
source = source.replace(
    'from main import load_fpl, load_fixtures, build_players, assign_recommendations, select_squad, build_around_players',
    'from main import load_fpl, load_fixtures, build_players, assign_recommendations\nfrom fast_squad_optimizer import select_squad, build_around_players',
)

source = source.replace(
    'cols=st.columns([1,2,1])\n        for i in range(2):\n            with cols[i+1 if i==0 else i]:',
    'cols=st.columns([1,1,1,1])\n        for i in range(2):\n            with cols[i+1]:'
)

# FPL picks can legitimately return 404 before the current Gameweek deadline.
# Keep the manager itself loadable so the app can use the ID and automatically
# pick up the squad once FPL publishes the GW picks endpoint.
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

# Never hide an unexpected fifth bench player. A legal FPL squad has exactly
# 11 starters + 4 bench players. Showing all items makes any UI/formation
# mismatch immediately visible instead of making the squad look under-budget.
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

# Add a hard UI-level squad audit so the displayed recommendation can never
# silently disagree with the FPL budget rules.
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

exec(source, globals())
