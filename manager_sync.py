"""Robust FPL manager synchronisation for the Streamlit app.

The public FPL API can temporarily return 404 for the current event's picks
before that Gameweek is published.  In that case we deliberately fall back to
the latest available picks instead of treating the Team ID as invalid.
"""
from datetime import datetime, timezone


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _chip_events(history):
    out = {}
    for chip in (history or {}).get("chips", []) or []:
        try:
            event = int(chip.get("event"))
        except (TypeError, ValueError):
            continue
        out.setdefault(event, []).append(str(chip.get("name", "")))
    return out


def _free_transfers_for_event(history, target_event):
    """Calculate the free transfers available for target_event.

    FPL carries free transfers forward, with a five-transfer cap.  Wildcard
    and Free Hit activity should not consume the banked transfer count.
    """
    target_event = int(target_event)
    current = sorted((history or {}).get("current", []) or [], key=lambda r: _as_int(r.get("event")))
    chips = _chip_events(history)
    free = 1
    for row in current:
        gw = _as_int(row.get("event"))
        if gw <= 0 or gw >= target_event:
            continue
        transfers = max(0, _as_int(row.get("event_transfers")))
        active = {x.lower().replace(" ", "") for x in chips.get(gw, [])}
        if "wildcard" in active or "freehit" in active:
            transfers = 0
        free = min(5, max(0, free + 1 - transfers))
    return free


def sync_manager(entry_id, preferred_event, api):
    """Return (entry, picks, metadata) using the newest available team."""
    normalised = api._normalise_entry_id(entry_id)
    preferred_event = max(1, int(preferred_event))
    entry = api._get(f"/entry/{normalised}/")

    picks = None
    synced_event = None
    for event in range(preferred_event, 0, -1):
        try:
            candidate = api._get(f"/entry/{normalised}/event/{event}/picks/")
        except api.FPLAPIError as exc:
            if int(exc.status) == 404:
                continue
            raise
        if candidate and candidate.get("picks"):
            picks = candidate
            synced_event = event
            break

    history = {}
    try:
        history = api._get(f"/entry/{normalised}/history/") or {}
    except Exception:
        history = {}

    last_bank = _as_float(entry.get("last_deadline_bank")) / 10.0
    last_value = _as_float(entry.get("last_deadline_value")) / 10.0
    free_transfers = _free_transfers_for_event(history, preferred_event)
    chips = history.get("chips", []) or []

    meta = {
        "synced_event": synced_event,
        "requested_event": preferred_event,
        "free_transfers": free_transfers,
        "bank_m": last_bank,
        "team_value_m": last_value,
        "overall_points": entry.get("summary_overall_points"),
        "overall_rank": entry.get("summary_overall_rank"),
        "chips": chips,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    if picks is None:
        picks = {"picks": [], "_picks_not_published": True}
    picks["_sync"] = meta
    return entry, picks
