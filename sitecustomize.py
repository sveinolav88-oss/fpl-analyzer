"""Small runtime compatibility patch for the Streamlit deployment.

Python imports sitecustomize automatically during normal interpreter startup.
The FPL API can return HTTP 404 for /entry/<id>/event/<gw>/picks/ before the
current Gameweek's picks have been published. That is a valid temporary state,
not an invalid Team ID. Patch decision_engine.load_manager so the app can keep
running and simply treat picks as unavailable until the endpoint exists.
"""

try:
    import decision_engine as _decision_engine

    _original_load_manager = _decision_engine.load_manager

    def _safe_load_manager(entry_id, event):
        try:
            return _original_load_manager(entry_id, event)
        except _decision_engine.FPLAPIError as exc:
            if int(exc.status) == 404 and "/picks/" in str(exc.path):
                normalised = _decision_engine._normalise_entry_id(entry_id)
                entry = _decision_engine._get(f"/entry/{normalised}/")
                return entry, {"picks": [], "_picks_not_published": True}
            raise

    _decision_engine.load_manager = _safe_load_manager
except Exception:
    # Never prevent Streamlit from starting because of this compatibility hook.
    pass
