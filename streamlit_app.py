# Main Streamlit entrypoint. The full application lives in streamlit_app_v2.py.
source = open("streamlit_app_v2.py", encoding="utf-8").read()
source = source.replace(
    'cols=st.columns([1,2,1])\n        for i in range(2):\n            with cols[i+1 if i==0 else i]:',
    'cols=st.columns([1,1,1,1])\n        for i in range(2):\n            with cols[i+1]:'
)
# Keep manager errors useful: the underlying FPL API status is much more
# informative than the old generic "ID is wrong" message.
source = source.replace(
    'st.sidebar.error(f"Fant ikke FPL-laget med ID {entry_id_text}. Sjekk at ID-en er riktig og at laget er registrert i FPL.")',
    'st.sidebar.error(f"Kunne ikke hente FPL-laget {entry_id_text}. {type(exc).__name__}: {exc}")'
)
exec(source, globals())
