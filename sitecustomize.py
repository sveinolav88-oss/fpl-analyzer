"""Runtime compatibility and FPL sync hooks for the Streamlit deployment.

This module is imported automatically by Python. It keeps the app resilient
when the public FPL API has not published the current Gameweek picks yet, and
adds a small source overlay so the UI uses the synced bank/free-transfer state
instead of asking the manager to type it in every Gameweek.
"""

from datetime import datetime, timezone
import builtins
import io

try:
    import decision_engine as _decision_engine
    from manager_sync import sync_manager as _sync_manager

    # Once a Gameweek deadline has passed, the useful planning target is the
    # following Gameweek. Before the deadline, keep analysing the current one.
    _original_current_gameweek = _decision_engine.current_gameweek

    def _smart_current_gameweek(data):
        events = data.get("events", []) or []
        current = next((e for e in events if e.get("is_current")), None)
        if current:
            deadline = current.get("deadline_time")
            try:
                dt = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
                if dt <= datetime.now(timezone.utc):
                    next_events = [e for e in events if int(e.get("id", 0)) > int(current.get("id", 0))]
                    if next_events:
                        next_event = next((e for e in next_events if e.get("is_next")), next_events[0])
                        return int(next_event["id"])
            except Exception:
                pass
        return _original_current_gameweek(data)

    _decision_engine.current_gameweek = _smart_current_gameweek

    # Automatic manager synchronisation. If the requested event is not
    # published yet, sync_manager falls back to the latest available event.
    def _safe_load_manager(entry_id, event):
        entry, picks = _sync_manager(entry_id, event, _decision_engine)
        meta = (picks or {}).get("_sync", {})
        used = set()
        for chip in meta.get("chips", []) or []:
            name = str(chip.get("name", "")).lower().replace(" ", "")
            if name == "triplecaptain":
                used.add("TC")
            elif name == "benchboost":
                used.add("BB")
            elif name == "freehit":
                used.add("FH")
        _decision_engine._SYNCED_CHIPS = used
        return entry, picks

    _decision_engine.load_manager = _safe_load_manager

    # Hide already-used one-shot chip values from the planner.
    _original_chip_windows = _decision_engine.chip_windows

    def _chip_windows_with_usage(*args, **kwargs):
        result = _original_chip_windows(*args, **kwargs)
        used = getattr(_decision_engine, "_SYNCED_CHIPS", set())
        if not used or result is None or len(result) == 0:
            return result
        mapping = {"TC": "tc_value", "BB": "bb_value", "FH": "fh_value"}
        for chip, col in mapping.items():
            if chip in used and col in result.columns:
                result[col] = -999.0
        return result

    _decision_engine.chip_windows = _chip_windows_with_usage

except Exception:
    # Never prevent Streamlit from starting because of a compatibility hook.
    pass


# The deployed entrypoint reads streamlit_app_v2.py as text before applying its
# normal optimisations. We use a narrow source overlay for the two manual
# finance fields and the manager-sync handoff. The underlying app remains the
# source of truth; this only changes how those values are populated.
_original_open = builtins.open


def _patched_open(file, mode="r", *args, **kwargs):
    try:
        path = str(file)
        is_v2 = path.replace("\\", "/").endswith("/streamlit_app_v2.py") or path == "streamlit_app_v2.py"
        text_mode = "b" not in mode and "r" in mode
    except Exception:
        is_v2 = False
        text_mode = False

    if not (is_v2 and text_mode):
        return _original_open(file, mode, *args, **kwargs)

    with _original_open(file, mode, *args, **kwargs) as fh:
        source = fh.read()

    source = source.replace(
        'free_transfers_manual = st.number_input("Free transfers", min_value=1, max_value=5, value=1, step=1)\n'
        '    bank_manual = st.number_input("Bank (£m)", min_value=0.0, max_value=20.0, value=0.0, step=0.1)',
        'free_transfers_manual = 1\n'
        '    bank_manual = 0.0\n'
        '    st.caption("Free transfers og bank synkroniseres automatisk fra FPL Team ID.")'
    )

    source = source.replace(
        'manager_entry=None; manager_picks=None; manager_ids=[]; manager_bank=bank_manual',
        'manager_entry=None; manager_picks=None; manager_ids=[]; manager_bank=bank_manual; manager_sync_meta={}'
    )

    source = source.replace(
        'manager_entry, manager_picks = load_manager(int(entry_id_text), current_gw)',
        'manager_entry, manager_picks = load_manager(int(entry_id_text), current_gw)\n'
        '        manager_sync_meta=(manager_picks or {}).get("_sync", {})\n'
        '        free_transfers_manual=int(manager_sync_meta.get("free_transfers", 1))\n'
        '        manager_bank=float(manager_sync_meta.get("bank_m", 0.0))'
    )

    source = source.replace(
        'manager_ids=[int(x["element"]) for x in manager_picks.get("picks",[])][:15]',
        'manager_ids=[int(x["element"]) for x in manager_picks.get("picks",[])][:15] if manager_picks else []\n'
        '        if manager_sync_meta:\n'
        '            synced_gw=manager_sync_meta.get("synced_event")\n'
        '            if manager_ids:\n'
        '                st.sidebar.success(f"✅ FPL synket · GW{synced_gw} · {free_transfers_manual} FT · £{manager_bank:.1f}m bank")\n'
        '                st.sidebar.caption(f"Analyserer nå GW{current_gw}. Laget hentes automatisk fra FPL når neste GW er publisert.")\n'
        '            elif manager_sync_meta.get("requested_event"):\n'
        '                _req_gw=manager_sync_meta.get("requested_event")\n'
        '                st.sidebar.info(f"FPL Team ID er funnet. Spillerlisten for GW{_req_gw} er ikke publisert ennå. Vi bruker siste tilgjengelige lag automatisk.")'
    )

    return io.StringIO(source)


builtins.open = _patched_open
