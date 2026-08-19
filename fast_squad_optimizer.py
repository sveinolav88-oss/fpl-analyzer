from collections import Counter
import pandas as pd

REQUIRED = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
ORDER = ["FWD", "MID", "DEF", "GKP"]


def _price_units(x):
    return int(round(float(x.get("price", 0.0)) * 10))


def _counts(players, key):
    return Counter(x.get(key) for x in players)


def _starting_xi(squad):
    groups = {
        p: sorted(
            [x for x in squad if x.get("position") == p],
            key=lambda x: float(x.get("expected_gw_points", 0)) + .12 * float(x.get("minutes_probability", .7)),
            reverse=True,
        ) for p in REQUIRED
    }
    formations = ((3,4,3),(3,5,2),(4,3,3),(4,4,2),(4,5,1),(5,2,3),(5,3,2),(5,4,1))
    best, best_pts = [], -1e9
    for d,m,f in formations:
        if len(groups["DEF"]) < d or len(groups["MID"]) < m or len(groups["FWD"]) < f:
            continue
        xi = groups["GKP"][:1] + groups["DEF"][:d] + groups["MID"][:m] + groups["FWD"][:f]
        pts = sum(float(x.get("expected_gw_points",0)) for x in xi)
        if pts > best_pts:
            best, best_pts = xi, pts
    return best, best_pts


def _objective(squad):
    xi, pts = _starting_xi(squad)
    if len(xi) != 11:
        return -1e9
    ids = {x.get("id") for x in xi}
    bench = [x for x in squad if x.get("id") not in ids]
    bench.sort(key=lambda x:(float(x.get("expected_gw_points",0)), float(x.get("minutes_probability",0))), reverse=True)
    return pts + .18 * sum(float(x.get("expected_gw_points",0)) for x in bench) + .05 * sum(max(0,min(1,float(x.get("expected_minutes",0))/90)) for x in bench)


def _rank(x):
    return (
        float(x.get("expected_gw_points",0)) +
        .28 * float(x.get("value",0)) +
        .18 * float(x.get("fixture_next3",0)) +
        .08 * float(x.get("minutes_probability",0))
    )


def _pools(df, locked):
    pools = {}
    for pos in REQUIRED:
        g = df[df.position == pos].copy()
        if g.empty:
            return None
        parts = [
            g.nlargest(22,"expected_gw_points"),
            g.nlargest(18,"value_score"),
            g.nlargest(14,"transfer_score"),
            g.nlargest(12,"fixture_next3"),
            g.nsmallest(28,"price"),
        ]
        c = pd.concat(parts).drop_duplicates("id")
        c = c[~c.id.isin(locked)]
        records = c.to_dict("records")
        records.sort(key=_rank, reverse=True)
        pools[pos] = records[:55]
    return pools


def _valid(squad, budget_units):
    if len(squad) != 15:
        return False
    if sum(_price_units(x) for x in squad) > budget_units:
        return False
    pc = _counts(squad,"position")
    if any(pc.get(p,0) != n for p,n in REQUIRED.items()):
        return False
    if max(_counts(squad,"team_id").values(), default=0) > 3:
        return False
    return True


def _improve_by_swaps(squad, pools, budget_units, locked_ids):
    locked_ids = {int(x) for x in locked_ids}
    current = list(squad)
    best_score = _objective(current)
    improved = True
    rounds = 0
    while improved and rounds < 4:
        improved = False
        rounds += 1
        current_ids = {int(x["id"]) for x in current}
        for pos in REQUIRED:
            candidates = pools[pos][:35]
            for idx, old in enumerate(list(current)):
                if old.get("position") != pos or int(old["id"]) in locked_ids:
                    continue
                for new in candidates:
                    nid = int(new["id"])
                    if nid in current_ids or nid in locked_ids:
                        continue
                    trial = list(current)
                    trial[idx] = new
                    if not _valid(trial, budget_units):
                        continue
                    score = _objective(trial)
                    cost = sum(_price_units(x) for x in trial)
                    old_cost = sum(_price_units(x) for x in current)
                    if score > best_score + 1e-9 or (abs(score-best_score) < 0.015 and cost > old_cost):
                        current = trial
                        current_ids = {int(x["id"]) for x in current}
                        best_score = score
                        improved = True
                        break
                if improved:
                    break
            if improved:
                break
    return current


def select_squad(df, budget=100.0, locked_ids=None):
    locked_ids = {int(x) for x in (locked_ids or [])}
    budget_units = int(round(float(budget) * 10))
    if df is None or len(df) == 0:
        return None
    by_id = {int(x["id"]): x for x in df.to_dict("records")}
    if locked_ids - set(by_id):
        return None
    locked = [by_id[x] for x in locked_ids]
    lc = _counts(locked,"position")
    if len(locked) > 15 or any(lc.get(p,0) > n for p,n in REQUIRED.items()) or max(_counts(locked,"team_id").values(),default=0) > 3:
        return None
    locked_cost = sum(_price_units(x) for x in locked)
    if locked_cost > budget_units:
        return None
    pools = _pools(df, locked_ids)
    if pools is None:
        return None
    remaining = {p: REQUIRED[p]-lc.get(p,0) for p in REQUIRED}
    if any(len(pools[p]) < n for p, n in remaining.items()):
        return None
    slots = [p for p in ORDER for _ in range(remaining[p])]
    cheapest = {p:min(_price_units(x) for x in pools[p]) for p in REQUIRED}
    suffix = [0]*(len(slots)+1)
    for i in range(len(slots)-1,-1,-1):
        suffix[i] = suffix[i+1] + cheapest[slots[i]]
    beam = [(locked, locked_cost, Counter(_counts(locked,"team_id")), 0.0)]
    for i,pos in enumerate(slots):
        states=[]
        floor=suffix[i+1]
        for players,cost,clubs,score in beam:
            used={int(x["id"]) for x in players}
            for x in pools[pos]:
                xid=int(x["id"])
                if xid in used:
                    continue
                team=x.get("team_id")
                if clubs.get(team,0)>=3:
                    continue
                nc=cost+_price_units(x)
                if nc > budget_units or nc+floor > budget_units:
                    continue
                cc=clubs.copy(); cc[team]+=1
                states.append((players+[x],nc,cc,score+_rank(x)))
        if not states:
            return None
        states.sort(key=lambda s:s[3], reverse=True)
        buckets={}; kept=[]
        bucket_size=max(5, budget_units//30)
        for s in states:
            b=s[1]//bucket_size
            if buckets.get(b,0)>=90:
                continue
            buckets[b]=buckets.get(b,0)+1
            kept.append(s)
            if len(kept)>=900:
                break
        beam=kept
    valid=[]
    for s in beam:
        squad=s[0]
        if _valid(squad,budget_units):
            valid.append(squad)
    if not valid:
        return None
    best=max(valid,key=_objective)
    best=_improve_by_swaps(best,pools,budget_units,locked_ids)
    if not _valid(best,budget_units):
        return None
    xi,_=_starting_xi(best)
    ids={int(x["id"]) for x in xi}
    bench=[x for x in best if int(x["id"]) not in ids]
    bench.sort(key=lambda x:(float(x.get("expected_gw_points",0)),float(x.get("minutes_probability",0))),reverse=True)
    total_units=sum(_price_units(x) for x in best)
    return (_objective(best),total_units/10.0,best,xi,bench)


def build_around_players(df, selected_player_ids, budget=100.0):
    return select_squad(df,budget=budget,locked_ids=selected_player_ids)
