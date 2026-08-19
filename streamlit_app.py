# Main Streamlit entrypoint. The full application lives in streamlit_app_v2.py.
source = open("streamlit_app_v2.py", encoding="utf-8").read()
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
# Keep manager errors useful: the underlying FPL API status is much more
# informative than the old generic "ID is wrong" message.
source = source.replace(
    'st.sidebar.error(f"Fant ikke FPL-laget med ID {entry_id_text}. Sjekk at ID-en er riktig og at laget er registrert i FPL.")',
    'st.sidebar.error(f"Kunne ikke hente FPL-laget {entry_id_text}. {type(exc).__name__}: {exc}")'
)

# Use a 4-GW rolling horizon for transfer decisions. This keeps the engine
# focused on actionable near-term decisions while fresh FPL data can re-rank
# the team every Gameweek.
source = source.replace('6-GW projeksjon', '4-GW projeksjon')
source = source.replace('de neste 6 Gameweeks', 'de neste 4 Gameweeks')
source = source.replace('horizon=6', 'horizon=4')
source = source.replace('6 GW projeksjon', '4 GW projeksjon')
source = source.replace('over 6 GW', 'over 4 GW')
source = source.replace('neste 6 GW', 'neste 4 GW')

exec(source, globals())
