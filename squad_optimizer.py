"""Robust FPL squad optimizer used by the Streamlit app.

This module deliberately keeps the UI independent from the older greedy
optimizer in main.py. It treats locked players as hard constraints and uses
a beam search with feasibility pruning before evaluating the final squads.
"""

from collections import Counter


def _pos_counts(squad):
    return Counter(x.get("position") for x in squad)


def _club_counts(squad):
    return Counter(x.get("team_id") for x in squad)


def _valid_squad(squad, budget):
    if len(squad) != 15:
        return False

    if sum(float(x.get("price", 0.0)) for x in squad) > budget + 1e-9:
        return False

    counts = _pos_counts(squad)
    if counts.get("GKP", 0) != 2:
        return False
    if counts.get("DEF", 0) != 5:
        return False
    if counts.get("MID", 0) != 5:
        return False
    if counts.get("FWD", 0) != 3:
        return False

    return max(_club_counts(squad).values(), default=0) <= 3


def _starting_xi(squad):
    """Return the highest projected legal XI from a 15-man squad."""
    groups = {
        "GKP": [x for x in squad if x.get("position") == "GKP"],
        "DEF": [x for x in squad if x.get("position") == "DEF"],
        "MID": [x for x in squad if x.get("position") == "MID"],
        "FWD": [x for x in squad if x.get("position") == "FWD"],
    }

    if not groups["GKP"]:
        return [], 0.0

    def weight(x):
        return float(x.get("expected_gw_points", 0.0)) + 0.12 * float(
            x.get("minutes_probability", 0.7)
        )

    formations = (
        (3, 4, 3), (3, 5, 2), (4, 3, 3), (4, 4, 2),
        (4, 5, 1), (5, 2, 3), (5, 3, 2), (5, 4, 1),
    )

    best_xi = []
    best_pts = -1e9

    for nd, nm, nf in formations:
        if len(groups["DEF"]) < nd or len(groups["MID"]) < nm or len(groups["FWD"]) < nf:
            continue

        xi = (
            sorted(groups["GKP"], key=weight, reverse=True)[:1]
            + sorted(groups["DEF"], key=weight, reverse=True)[:nd]
            + sorted(groups["MID"], key=weight, reverse=True)[:nm]
            + sorted(groups["FWD"], key=weight, reverse=True)[:nf]
        )
        pts = sum(float(x.get("expected_gw_points", 0.0)) for x in xi)
        if pts > best_pts:
            best_pts = pts
            best_xi = xi

    return best_xi, best_pts


def _objective(squad):
    xi, xi_pts = _starting_xi(squad)
    if len(xi) != 11:
        return -1e9

    xi_ids = {x.get("id") for x in xi}
    bench = [x for x in squad if x.get("id") not in xi_ids]
    bench.sort(
        key=lambda x: (
            float(x.get("expected_gw_points", 0.0)),
            float(x.get("minutes_probability", 0.0)),
        ),
        reverse=True,
    )

    bench_cover = sum(float(x.get("expected_gw_points", 0.0)) for x in bench) * 0.18
    minutes_cover = sum(
        max(0.0, min(1.0, float(x.get("expected_minutes", 0.0)) / 90.0))
        for x in bench
    ) * 0.05

    return xi_pts + bench_cover + minutes_cover


def _player_rank(x):
    """Ranking used only to keep the search compact; final choice uses _objective."""
    return (
        1.00 * float(x.get("expected_gw_points", 0.0))
        + 0.28 * float(x.get("value", 0.0))
        + 0.18 * float(x.get("fixture_next3", 0.0))
        + 0.08 * float(x.get("minutes_probability", 0.0))
    )


def _build_pools(df, locked_ids):
    pools = {}
    for pos, need in (("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        g = df[df["position"] == pos].copy()
        if g.empty:
            pools[pos] = []
            continue

        # Keep both premium players and cheap enablers. The old optimizer could
        # spend too much early and then fail even when a valid squad existed.
        frames = [
            g.nlargest(55, "expected_gw_points"),
            g.nlargest(45, "value_score"),
            g.nlargest(35, "transfer_score"),
            g.nlargest(25, "fixture_next3"),
            g.nsmallest(45, "price"),
        ]
        candidates = __import__("pandas").concat(frames).drop_duplicates("id")

        # Locked players are already in the base squad, so they should not be
        # offered as replacement candidates.
        candidates = candidates[~candidates["id"].isin(locked_ids)]
        pools[pos] = sorted(candidates.to_dict("records"), key=_player_rank, reverse=True)

    return pools


def select_squad(df, budget=100.0, locked_ids=None):
    """Find a valid, high-scoring 15-man squad while respecting locked players."""
    locked_ids = set(locked_ids or [])
    budget = float(budget)

    if df is None or len(df) == 0:
        return None

    by_id = {x["id"]: x for x in df.to_dict("records")}
    missing = locked_ids - set(by_id)
    if missing:
        return None

    locked = [by_id[x] for x in locked_ids]
    if len(locked) > 15:
        return None

    required = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    locked_counts = _pos_counts(locked)
    if any(locked_counts.get(pos, 0) > need for pos, need in required.items()):
        return None
    if max(_club_counts(locked).values(), default=0) > 3:
        return None

    locked_cost = sum(float(x.get("price", 0.0)) for x in locked)
    if locked_cost > budget + 1e-9:
        return None

    pools = _build_pools(df, locked_ids)

    # Add a small set of absolute cheapest players per position so feasibility
    # is preserved even when all premium candidates are too expensive.
    for pos, need in required.items():
        available = [x for x in pools[pos]]
        min_needed = need - locked_counts.get(pos, 0)
        if min_needed < 0:
            return None
        if len(available) < min_needed:
            return None

    # Build in positions with the tightest/most expensive slots first. This
    # makes the budget pruning much more effective.
    order = ["FWD", "MID", "DEF", "GKP"]
    slots = []
    for pos in order:
        remaining = required[pos] - locked_counts.get(pos, 0)
        slots.extend([pos] * remaining)

    # Beam state: (players, cost, clubs, score). We retain many states so a
    # cheap-but-lower-ranked combination is not discarded just because it can
    # unlock a better combination later.
    beam = [(locked, locked_cost, Counter(_club_counts(locked)), 0.0)]
    beam_width = 4500

    for slot_index, pos in enumerate(slots):
        candidates = pools[pos]
        next_slots = slots[slot_index + 1 :]

        # Precompute the cheapest available price per remaining position. This
        # is a safe lower bound for budget feasibility.
        cheap_by_pos = {}
        for rp in set(next_slots):
            vals = [float(x.get("price", 0.0)) for x in pools[rp]]
            cheap_by_pos[rp] = min(vals) if vals else 99.0

        states = []
        for players, cost, clubs, score in beam:
            used = {x.get("id") for x in players}
            for x in candidates:
                xid = x.get("id")
                if xid in used:
                    continue

                tid = x.get("team_id")
                if clubs.get(tid, 0) >= 3:
                    continue

                price = float(x.get("price", 0.0))
                new_cost = cost + price
                if new_cost > budget + 1e-9:
                    continue

                # Cheap lower bound for all remaining slots.
                lower_bound = sum(cheap_by_pos[p] for p in next_slots)
                if new_cost + lower_bound > budget + 1e-9:
                    continue

                new_clubs = clubs.copy()
                new_clubs[tid] += 1
                new_players = players + [x]
                inc = _player_rank(x)
                states.append((new_players, new_cost, new_clubs, score + inc))

        if not states:
            return None

        # Keep diversity across budget bands. A pure top-score beam can lose
        # the only affordable route to a valid 15-man squad.
        states.sort(key=lambda s: s[3], reverse=True)
        buckets = {}
        selected = []
        bucket_size = max(0.5, budget / 40.0)

        for state in states:
            b = int(state[1] / bucket_size)
            if buckets.get(b, 0) >= 140:
                continue
            buckets[b] = buckets.get(b, 0) + 1
            selected.append(state)
            if len(selected) >= beam_width:
                break

        beam = selected

    valid = [s[0] for s in beam if _valid_squad(s[0], budget)]
    if not valid:
        return None

    best_squad = max(valid, key=_objective)
    xi, xi_pts = _starting_xi(best_squad)
    xi_ids = {x.get("id") for x in xi}
    bench = [x for x in best_squad if x.get("id") not in xi_ids]
    bench.sort(
        key=lambda x: (
            float(x.get("expected_gw_points", 0.0)),
            float(x.get("minutes_probability", 0.0)),
        ),
        reverse=True,
    )

    return (
        _objective(best_squad),
        sum(float(x.get("price", 0.0)) for x in best_squad),
        best_squad,
        xi,
        bench,
    )


def build_around_players(df, selected_player_ids, budget=100.0):
    """Build the best squad around the user's explicitly locked players."""
    ids = list(dict.fromkeys(selected_player_ids or []))
    return select_squad(df, budget=budget, locked_ids=ids)
