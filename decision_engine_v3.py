"""Decision engine v3: robust, data-first FPL Gameweek planning.

The engine always returns a visible plan. It separates the current GW's
actual points from future expected points and evaluates transfer opportunity
cost, fixtures, minutes, budget and legal squad constraints.
"""
from collections import Counter
from functools import lru_cache
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


def _cached(key, path):
    now=time.time(); hit=_CACHE.get(key)
    if hit and now-hit[0] < API_CACHE_TTL: return hit[1]
    value=_get(path); _CACHE[key]=(now,value); return value


def load_manager(entry_id,event):
    entry_id=int(entry_id); event=int(event)
    entry=_cached(("entry",entry_id),f"/entry/{entry_id}/")
    picks=_cached(("picks",entry_id,event),f"/entry/{entry_id}/event/{event}/picks/")
    try: history=_cached(("history",entry_id),f"/entry/{entry_id}/history/")
    except Exception: history={}
    # Reconstruct banked FTs from official history. FPL caps the bank at five.
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
        except: continue
        for tid,home in ((f.get("team_h"),True),(f.get("team_a"),False)):
            if tid is not None: m.setdefault((int(tid),ev),[]).append((home,f))
    return m


def fixture_quality(team_id,gw,m):
    rows=m.get((int(team_id),int(gw)),[])
    if not rows: return 0.0,0
    vals=[]
    for home,f in rows:
        vals.append(num(f.get("team_h_difficulty" if home else "team_a_difficulty"),3))
    avg=sum(vals)/len(vals)
    return max(0,min(1,(5-avg)/4)),len(rows)


def projection_matrix(df,fixtures,start_gw,horizon=4):
    df=clean(df); fm=fixture_map(fixtures); start_gw=int(start_gw); horizon=max(1,min(4,int(horizon)))
    gws=list(range(start_gw,min(38,start_gw+horizon-1)+1)); rows=[]
    for _,p in df.iterrows():
        base=max(0.2,num(p.get("expected_gw_points")))
        mp=max(0.05,min(1,num(p.get("minutes_probability"),.8)))
        current_q=max(.15,min(1,num(p.get("fixture_next1"),.5)))
        row={"id":int(p.id),"name":str(p.get("name","?"))}
        for gw in gws:
            q,count=fixture_quality(p.get("team_id",-1),gw,fm)
            if not count: row[gw]=0.0; continue
            mult=(.90+.20*q)/(.90+.20*current_q)
            minutes=.72+.28*mp
            # Each fixture contributes independently; DGW is therefore two
            # fixture expectations, with a small rotation/90-minute discount.
            per=base*mult*minutes
            if count>1: per*=.94
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


def transfer_candidates(ids,df,matrix,bank,free_transfers,horizon=4):
    df=clean(df); ids={int(x) for x in ids}; gws=list(matrix.columns)[:horizon]
    if not gws: return []
    base=squad_projection(ids,df,matrix,gws)["total"]
    horizon_pts=matrix[gws].sum(axis=1).to_dict()
    pool=df.copy(); pool["_h"]=pool.id.map(horizon_pts).fillna(0.0).astype(float)
    results=[]
    current=df[df.id.isin(ids)]
    for _,old in current.iterrows():
        pos=str(old.get("position","")); sell=num(old.get("selling_price",old.get("price")))
        candidates=pool[(pool.position.astype(str)==pos)&(~pool.id.isin(ids))].sort_values(["_h","expected_gw_points","minutes_probability"],ascending=False).head(35)
        for _,new in candidates.iterrows():
            buy=num(new.get("price"))
            if buy>num(bank)+sell+1e-9: continue
            new_ids=ids-{int(old.id)}|{int(new.id)}
            if not club_ok(new_ids,df): continue
            projected=squad_projection(new_ids,df,matrix,gws)["total"]
            gain=projected-base
            next_gain=num(matrix.loc[int(new.id),gws[0]],0)-num(matrix.loc[int(old.id),gws[0]],0)
            fixture_delta=num(new.get("fixture_next3"))-num(old.get("fixture_next3"))
            minutes_delta=num(new.get("minutes_probability"))-num(old.get("minutes_probability"))
            hit=0 if int(free_transfers)>0 else 4
            results.append({"out_id":int(old.id),"out":str(old.get("name","?")),"in_id":int(new.id),"in":str(new.get("name","?")),"position":pos,"cost":round(buy-sell,1),"projected_gain":round(gain,3),"next_gw_delta":round(next_gain,3),"fixture_delta":round(fixture_delta,3),"minutes_delta":round(minutes_delta,3),"hit":hit,"new_total":round(projected,3)})
    return sorted(results,key=lambda x:(x["projected_gain"],x["next_gw_delta"]),reverse=True)


def future_ft_value(ids,df,fixtures,bank,free_transfers,target_gw):
    if free_transfers>=5 or target_gw>=38: return 0.0
    m=projection_matrix(df,fixtures,target_gw+1,1)
    if m.empty: return 0.0
    candidates=transfer_candidates(ids,df,m,bank,1,1)
    gain=max([num(x.get("projected_gain")) for x in candidates] or [0])
    return round(max(0,min(3.5,gain*.60)),3)


def decision_summary(df,fixtures,squad_ids,budget,bank,free_transfers,start_gw,horizon=4):
    df=clean(df); ids={int(x) for x in squad_ids}; current_gw=int(start_gw); target_gw=min(38,current_gw+1); horizon=max(1,min(4,int(horizon or 4)))
    matrix=projection_matrix(df,fixtures,target_gw,horizon)
    gws=list(matrix.columns)[:horizon]
    if not gws:
        return {"matrix":matrix,"current":{"total":0,"by_gw":{},"xi_by_gw":{},"captain_by_gw":{}},"transfers":[],"two_transfers":None,"chips":pd.DataFrame(),"wildcard":None,"best_action":"HOLD","target_gw":target_gw,"decision":{"action":"HOLD","reason":"Ingen kommende fixtures tilgjengelig i FPL-data akkurat nå."}}
    current=squad_projection(ids,df,matrix,gws)
    transfers=transfer_candidates(ids,df,matrix,bank,free_transfers,horizon)
    future=future_ft_value(ids,df,fixtures,bank,int(free_transfers),target_gw)
    for x in transfers:
        x["future_ft_value"]=future
        x["net_gain"]=round(num(x["projected_gain"])-num(x["hit"])-future,3)
        x["decision_score"]=round(x["net_gain"]+max(0,num(x["next_gw_delta"]))*.30+max(0,num(x["minutes_delta"]))*.35,3)
    transfers.sort(key=lambda x:(x["decision_score"],x["projected_gain"]),reverse=True)
    best=transfers[0] if transfers else None
    threshold=.75 if int(free_transfers)>0 else 4.75
    action="TRANSFER" if best and num(best["net_gain"])>=threshold else "HOLD"
    reasons=[]
    if best:
        if best["next_gw_delta"]>0.1: reasons.append("bedre forventet poeng i neste GW")
        if best["fixture_delta"]>0.08: reasons.append("bedre fixture-run")
        if best["minutes_delta"]>0.08: reasons.append("bedre forventet spilletid")
        if future>0.5: reasons.append(f"å spare FT har beregnet verdi på ca. {future:.1f} poeng")
        if action=="HOLD": reasons.append("fordelen er for liten til å bruke transferen nå")
    else:
        reasons.append("Ingen lovlig og økonomisk transfer ble funnet med tydelig merverdi")
    confidence=.55 if not best else max(.55,min(.98,.55+max(0,num(best["net_gain"]))*0.12))
    decision={"action":action,"target_gw":target_gw,"out":best.get("out") if best else None,"in":best.get("in") if best else None,"projected_gain":num(best.get("projected_gain")) if best else 0.0,"net_gain":num(best.get("net_gain")) if best else 0.0,"future_ft_value":future,"threshold":threshold,"confidence":round(confidence,2),"reasons":reasons}
    return {"matrix":matrix,"current":current,"transfers":transfers,"two_transfers":None,"chips":pd.DataFrame(),"wildcard":None,"best_action":action,"target_gw":target_gw,"decision":decision}
