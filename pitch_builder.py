from collections import defaultdict


def formation_shape(formation):
    d, m, f = (int(x) for x in formation.split("-"))
    return {"GKP": 1, "DEF": d, "MID": m, "FWD": f}


def build_display_xi(squad, locked_ids, formation):
    """Create a position-aware XI for the build-around pitch.

    Locked players are prioritised into the chosen formation. Remaining
    positions are filled by the strongest players from the optimized squad.
    This is a display/UX layer; the underlying optimizer still produces the
    full legal 15-man squad.
    """
    shape = formation_shape(formation)
    locked_ids = set(locked_ids or [])
    by_pos = defaultdict(list)
    for p in squad:
        by_pos[p["position"]].append(p)

    chosen = []
    chosen_ids = set()

    for pos, count in shape.items():
        locked = [p for p in by_pos[pos] if p["id"] in locked_ids]
        if len(locked) > count:
            return None
        for p in locked:
            chosen.append(p)
            chosen_ids.add(p["id"])

    for pos, count in shape.items():
        remaining = count - sum(1 for p in chosen if p["position"] == pos)
        candidates = sorted(
            [p for p in by_pos[pos] if p["id"] not in chosen_ids],
            key=lambda p: (
                p.get("expected_gw_points", 0),
                p.get("minutes_probability", 0),
            ),
            reverse=True,
        )
        for p in candidates[:remaining]:
            chosen.append(p)
            chosen_ids.add(p["id"])

    if len(chosen) != 11:
        return None

    order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    return sorted(chosen, key=lambda p: order.get(p["position"], 9))
