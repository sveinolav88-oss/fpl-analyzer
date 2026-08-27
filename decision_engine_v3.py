"""Decision engine v3: fixture-aware, multi-GW FPL planning.

The transfer engine must not chase the previous Gameweek.  It evaluates the
actual upcoming fixtures, expected minutes, player quality, squad opportunity
cost, transfer cost and the value of saving a free transfer.
"""
from collections import Counter
import time
import pandas as pd

from decision_engine import _get, FPLAPIError, current_gameweek

API_CACHE_TTL = 300
_CACHE = {}
FORMATIONS = ((3,4,3),(3,5,2),(4,3,3),(4,4,2),(4,5,1),(5,2,3),(5,3,2),(5,4,1))


def num(v, default=0.0):
    try:
        if v is None or v == "": return float(default)
        x=float(v)
        return x if x == x else float(default)
    except (TypeError, ValueError):
        return float(default)


def clean(df):
    out=df.copy()
    numeric=["id","team_id","price","selling_price","expected_gw_points","expected_minutes","minutes_probability","fixture_next1","fixture_next3","fixture_next5","value","ownership","form","points_per_game"]
    for c in numeric:
        if c in out.columns: out[c]=pd.to_numeric(out[c],errors="coerce")
    if "id" in out.columns:
        out=out[out.id.notna()].copy(); out["id"]=out.id.astype(int)
    defaults={"price":0.0,"selling_price":0.0,"expected_gw_points":0.0,"expected_minutes":75.0,"minutes_probability":0.8,"fixture_next1":0.5,"fixture_next3":0.5,"fixture_next5":0.5,"value":0.0,"ownership":0.0,"form":0.0,"points_per_game":0.0}
    for c,d in defaults.items():
        if c in out.columns: out[c]=out[c].fillna(d).astype(float)
    return out


def _cached(key,path):
    now=time.time(); hit=_CACHE.get(key)
    if hit and now-hit[0] < API_CACHE_TTL: return hit[1]
    value=_get(path); _CACHE[key]=(now,value); return value


def load_manager(entry_id,event):
    entry_id=int(entry_id); event=int(event)
    entry=_cached(("entry",entry_id),f"/entry/{entry_id}/")
    picks=_cached(("picks",entry_id,event),f"/entry/{entry_id}/event/{event}/picks/")
    try: history=_cached(("history",entry_id),f"/entry/{entry_id}/history/")
    except Exception: history={}
    available=0
    chips={int(x.get("event",0)):str(x.get("name","")).lower() for x in history.get("chips",[]) or []}
    for row in sorted(history.get("current",[]) or [],key=lambda x:int(x.get("event",0) or 0)):
        gw=int(row.get("event",0) or 0)
        if gw>=event: break
        used=int(num(row.get("event_transfers"),0))
        if chips.get(gw) in {"wildcard","freehit"}: used=0
        available=max(0,min(5,available+1-used))
    picks=dict(picks or {})
    picks["_sync"]={"free_transfers":available,"current_gw":event,"target_gw":min(38,event+1),"updated_at":time.time()}
    return entry,picks


def fixture_map(fixtures):
    m={}
    for f in fixtures or []:
        ev=f.get("event")
        if ev is None: continue
        try: ev=int(ev)
        except Exception: continue
        for tid,home in ((f.get("team_h"),True),(f.get("team_a"),False)):
            if tid is not None:
                m.setdefault((int(tid),ev),[]).append((home,f))
    return m


def fixture_quality(team_id,gw,m):
    rows=m.get((int(team_id),int(gw)),[])
    if not rows: return 0.0,0
    vals=[]
    for home,f in rows:
        vals.append(num(f.get("team_h_difficulty" if home else "team_a_difficulty"),3))
    avg=sum(vals)/len(vals)
    return max(0,min(1,(5-avg)/4)),len(rows)


def fixture_multiplier(q,position):
    """Translate FPL FDR quality into a points multiplier.

    Defenders/keepers are more sensitive to fixture quality because clean
    sheets are a large part of their expected score.  Attackers still get a
    fixture boost, but less aggressively.  FDR itself is an official FPL
    planning signal and is updated as the season progresses.
    """
    q=max(0,min(1,num(q,.5)))
    if position in ("GKP","DEF"):
        return .78 + .44*q       # 0.78 .. 1.22
    return .88 + .24*q           # 0.88 .. 1.12


def horizon_weights(horizon):
    # The next GW matters most, but GW2-4 still materially affect a transfer.
    base=[1.00,.88,.76,.64]
    return base[:max(1,min(4,int(horizon)))]


def projection_matrix(df,fixtures,start_gw,horizon=4):
    """Project every player for every upcoming GW using that GW's fixture.

    Crucially, we remove the player's current-fixture multiplier from the
    one-GW model first, then apply the actual opponent FDR for each future GW.
    This prevents the engine from simply carrying a player's last/next-GW
    projection forward unchanged.
    """
    df=clean(df); fm=fixture_map(fixtures); start_gw=int(start_gw); horizon=max(1,min(4,int(horizon)))
    gws=list(range(start_gw,min(38,start_gw+horizon-1)+1)); rows=[]
    weights=horizon_weights(horizon)
    for _,p in df.iterrows():
        pos=str(p.get("position",""))
        expected=max(.2,num(p.get("expected_gw_points")))
        current_q=max(.15,min(1,num(p.get("fixture_next1"),.5)))
        current_mult=fixture_multiplier(current_q,pos)
        neutral=expected/max(current_mult,.5)
        mp=max(.05,min(1,num(p.get("minutes_probability"),.8)))
        minutes_factor=.82+.18*mp
        row={"id":int(p.id),"name":str(p.get("name","?"))}
        for gw in gws:
            q,count=fixture_quality(p.get("team_id",-1),gw,fm)
            if not count:
                row[gw]=0.0
                continue
            mult=fixture_multiplier(q,pos)
            per=neutral*mult*minutes_factor
            if count>1:
                # DGW is valuable but rotation risk prevents simply doubling.
                per*=.94
            row[gw]=round(max(0,per*count),3)
        rows.append(row)
    return pd.DataFrame(rows).set_index("id") if rows else pd.DataFrame()


def legal_xi(squad,points):
    squad=clean(squad)
    if squad.empty: return [],0.0,None
    pts={int(k):num(v) for k,v in (points or {}).items()}
    groups={pos:squad[squad.position.astype(str)==pos].copy() for pos in ("GKP","DEF","MID","FWD")}
    best=None
    for d,m,f in FORMATIONS:
        if len(groups["GKP"])<1 or len(groups["DEF"])<d or len(groups["MID"])<m or len(groups["FWD"])<f: continue
        chosen=[]
        for pos,n in (("GKP",1),("DEF",d),("MID",m),("FWD",f)):
            g=groups[pos].copy(); g["_p"]=g.id.map(pts).fillna(0.0).astype(float); chosen.append(g.sort_values("_p",ascending=False).head(n))
        xi=pd.concat(chosen,ignore_index=True); score=float(xi._p.sum())
        cap=max(xi.to_dict("records"),key=lambda x:pts.get(int(x["id"]),0))
        total=score+pts.get(int(cap["id"]),0)
        if best is None or total>best[0]: best=(total,xi,cap)
    return (best[1].to_dict("records"),best[0],best[2]) if best else ([],0.0,None)


def squad_projection(ids,df,matrix,gws):
    squad=clean(df[df.id.isin({int(x) for x in ids})].copy()); by={}; total=0.0; xis={}; caps={}
    for gw in gws:
        if gw not in matrix.columns: continue
        xi,score,cap=legal_xi(squad,matrix[gw].to_dict()); by[int(gw)]=round(score,3); xis[int(gw)]=xi; caps[int(gw)]=cap.get("name") if cap else None; total+=score
    return {"total":round(total,3),"by_gw":by,"xi_by_gw":xis,"captain_by_gw":caps}


def club_ok(ids,df):
    counts=Counter(int(x) for x in df[df.id.isin(set(ids))].team_id.tolist())
    return max(counts.values(),default=0)<=3


def fixture_run_summary(team_id,position,fixtures,start_gw,horizon=4):
    fm=fixture_map(fixtures); rows=[]
    for gw in range(int(start_gw),min(38,int(start_gw)+int(horizon)-1)+1):
        q,count=fixture_quality(team_id,gw,fm)
        rows.append({"gw":gw,"q":q,"count":count,"mult":fixture_multiplier(q,position) if count else 0.0})
    valid=[x for x in rows if x["count"]]
    weights=horizon_weights(len(rows))
    weighted=sum(x["q"]*weights[i] for i,x in enumerate(rows) if x["count"])/max(sum(weights[i] for i,x in enumerate(rows) if x["count"]),1e-9)
    return rows,weighted


def transfer_candidates(ids,df,matrix,bank,free_transfers,horizon=4,fixtures=None,start_gw=None):
    df=clean(df); ids={int(x) for x in ids}; gws=list(matrix.columns)[:horizon]
    if not gws: return []
    weights=horizon_weights(len(gws))
    base_proj=squad_projection(ids,df,matrix,gws)
    base=sum(base_proj["by_gw"].get(int(gw),0)*weights[i] for i,gw in enumerate(gws))
    pool=df.copy()
    pool["_h"]=0.0
    for i,gw in enumerate(gws):
        pool["_h"] += matrix[gw].fillna(0.0)*weights[i]
    results=[]; current=df[df.id.isin(ids)]
    for _,old in current.iterrows():
        pos=str(old.get("position","")); sell=num(old.get("selling_price",old.get("price")))
        candidates=pool[(pool.position.astype(str)==pos)&(~pool.id.isin(ids))].sort_values(["_h","expected_gw_points","minutes_probability"],ascending=False).head(50)
        for _,new in candidates.iterrows():
            buy=num(new.get("price"))
            if buy>num(bank)+sell+1e-9: continue
            new_ids=ids-{int(old.id)}|{int(new.id)}
            if not club_ok(new_ids,df): continue
            new_proj=squad_projection(new_ids,df,matrix,gws)
            projected=sum(new_proj["by_gw"].get(int(gw),0)*weights[i] for i,gw in enumerate(gws))
            gain=projected-base
            next_gain=num(matrix.loc[int(new.id),gws[0]],0)-num(matrix.loc[int(old.id),gws[0]],0)
            old_h=sum(num(matrix.loc[int(old.id),gw],0)*weights[i] for i,gw in enumerate(gws))
            new_h=sum(num(matrix.loc[int(new.id),gw],0)*weights[i] for i,gw in enumerate(gws))
            fixture_edge=0.0
            if fixtures is not None and start_gw is not None:
                _,old_q=fixture_run_summary(old.get("team_id"),pos,fixtures,start_gw,horizon)
                _,new_q=fixture_run_summary(new.get("team_id"),pos,fixtures,start_gw,horizon)
                fixture_edge=new_q-old_q
            fixture_delta=num(new.get("fixture_next3"))-num(old.get("fixture_next3"))
            minutes_delta=num(new.get("minutes_probability"))-num(old.get("minutes_probability"))
            hit=0 if int(free_transfers)>0 else 4
            results.append({
                "out_id":int(old.id),"out":str(old.get("name","?")),"in_id":int(new.id),"in":str(new.get("name","?")),"position":pos,
                "cost":round(buy-sell,1),"projected_gain":round(gain,3),"next_gw_delta":round(next_gain,3),
                "fixture_delta":round(fixture_delta,3),"fixture_run_edge":round(fixture_edge,3),"minutes_delta":round(minutes_delta,3),
                "out_4gw_points":round(old_h,2),"in_4gw_points":round(new_h,2),"hit":hit,"new_total":round(projected,3)
            })
    return sorted(results,key=lambda x:(x["projected_gain"],x["next_gw_delta"]),reverse=True)


def future_ft_value(ids,df,fixtures,bank,free_transfers,target_gw):
    if free_transfers>=5 or target_gw>=38: return 0.0
    m=projection_matrix(df,fixtures,target_gw+1,1)
    if m.empty: return 0.0
    candidates=transfer_candidates(ids,df,m,bank,1,1,fixtures,target_gw+1)
    gain=max([num(x.get("projected_gain")) for x in candidates] or [0])
    return round(max(0,min(3.5,gain*.60)),3)


def decision_summary(df,fixtures,squad_ids,budget,bank,free_transfers,start_gw,horizon=4):
    df=clean(df); ids={int(x) for x in squad_ids}; current_gw=int(start_gw); target_gw=min(38,current_gw+1); horizon=max(1,min(4,int(horizon or 4)))
    matrix=projection_matrix(df,fixtures,target_gw,horizon)
    gws=list(matrix.columns)[:horizon]
    if not gws:
        return {"matrix":matrix,"current":{"total":0,"by_gw":{},"xi_by_gw":{},"captain_by_gw":{}},"transfers":[],"two_transfers":None,"chips":pd.DataFrame(),"wildcard":None,"best_action":"HOLD","target_gw":target_gw,"decision":{"action":"HOLD","reason":"Ingen kommende fixtures tilgjengelig i FPL-data akkurat nå."}}
    current=squad_projection(ids,df,matrix,gws)
    transfers=transfer_candidates(ids,df,matrix,bank,free_transfers,horizon,fixtures,target_gw)
    future=future_ft_value(ids,df,fixtures,bank,int(free_transfers),target_gw)

    for x in transfers:
        x["future_ft_value"]=future
        # A transfer must win on the actual 4-GW squad projection. Fixture
        # quality is already inside that projection; it is used again only as
        # a small tie-breaker, never as a substitute for projected points.
        x["net_gain"]=round(num(x["projected_gain"])-num(x["hit"])-future,3)
        x["decision_score"]=round(
            x["net_gain"]
            + max(0,num(x["next_gw_delta"]))*.15
            + num(x["fixture_run_edge"])*.35
            + max(0,num(x["minutes_delta"]))* .25,
            3,
        )

    transfers.sort(key=lambda x:(x["decision_score"],x["net_gain"],x["projected_gain"]),reverse=True)
    best=transfers[0] if transfers else None

    # Stronger HOLD rule: do not recommend a transfer just because of one
    # explosive previous GW. The move must produce meaningful net value over
    # the forward horizon after accounting for the value of the free transfer.
    threshold=.90 if int(free_transfers)>0 else 4.90
    action="TRANSFER" if best and num(best["net_gain"])>=threshold and num(best["projected_gain"])>0.50 else "HOLD"

    reasons=[]
    if best:
        if best["next_gw_delta"]>0.15: reasons.append("bedre forventet poeng i neste GW")
        elif best["next_gw_delta"]<-0.25: reasons.append("svakere neste GW enn spilleren du selger")
        if best["fixture_run_edge"]>0.08: reasons.append("klart bedre fixture-run over horisonten")
        elif best["fixture_run_edge"]<-0.08: reasons.append("dårligere fixture-run over horisonten")
        if best["minutes_delta"]>0.08: reasons.append("bedre forventet spilletid")
        if future>0.5: reasons.append(f"å spare FT har beregnet verdi på ca. {future:.1f} poeng")
        if best["projected_gain"]<0.5: reasons.append("for liten 4-GW gevinst")
        if action=="HOLD": reasons.append("fordelen er for liten til å bruke transferen nå")
    else:
        reasons.append("Ingen lovlig og økonomisk transfer ble funnet med tydelig merverdi")

    confidence=.55 if not best else max(.55,min(.98,.55+max(0,num(best["net_gain"]))*0.10))
    decision={
        "action":action,"target_gw":target_gw,"out":best.get("out") if best else None,"in":best.get("in") if best else None,
        "projected_gain":num(best.get("projected_gain")) if best else 0.0,"net_gain":num(best.get("net_gain")) if best else 0.0,
        "future_ft_value":future,"threshold":threshold,"confidence":round(confidence,2),"reasons":reasons,
    }
    return {"matrix":matrix,"current":current,"transfers":transfers,"two_transfers":None,"chips":pd.DataFrame(),"wildcard":None,"best_action":action,"target_gw":target_gw,"decision":decision}
