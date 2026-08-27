"""Robust FPL decision layer used by the Streamlit app.

This module deliberately isolates optional scenarios so one malformed FPL field
cannot blank the entire Gameweek Plan. All arithmetic fields are normalised
before calculation; names such as 'Raya' can never be interpreted as numbers.
"""
from collections import Counter
from functools import lru_cache
import time

import pandas as pd
import requests

from fast_squad_optimizer import select_squad

API = "https://fantasy.premierleague.com/api"
TIMEOUT = 30
FORMATIONS = ((3,4,3),(3,5,2),(4,3,3),(4,4,2),(4,5,1),(5,2,3),(5,3,2),(5,4,1))

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 FPL Analyzer",
    "Accept": "application/json",
    "Referer": "https://fantasy.premierleague.com/",
})


def _get(path):
    last = None
    for attempt in range(4):
        try:
            r = SESSION.get(API + path, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429,500,502,503,504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"FPL API HTTP {r.status_code} på {path}")
        except requests.RequestException as exc:
            last = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last or RuntimeError("FPL API-feil")


def _entry_id(value):
    s = str(value or "").strip()
    if "/entry/" in s:
        s = s.split("/entry/",1)[1].split("/",1)[0]
    if not s.isdigit() or int(s) <= 0:
        raise ValueError("Ugyldig FPL Team ID")
    return int(s)


@lru_cache(maxsize=64)
def load_manager(entry_id, event):
    entry_id = _entry_id(entry_id)
    event = int(event)
    entry = _get(f"/entry/{entry_id}/")
    picks = _get(f"/entry/{entry_id}/event/{event}/picks/")
    return entry, picks


def current_gameweek(data):
    for e in data.get("events", []):
        if e.get("is_current"):
            return int(e["id"])
    for e in data.get("events", []):
        if e.get("is_next"):
            return int(e["id"])
    for e in data.get("events", []):
        if not e.get("finished"):
            return int(e["id"])
    return 38


def _num(value, default=0.0):
    try:
        if value is None:
            return float(default)
        x = float(value)
        return x if x == x else float(default)
    except (TypeError, ValueError):
        return float(default)


def _clean_df(df):
    out = df.copy()
    numeric = ["id","team_id","price","selling_price","expected_gw_points",
               "expected_minutes","minutes_probability","fixture_next3",
               "fixture_next5","value","value_score","transfer_score",
               "captain_score","ownership"]
    for col in numeric:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "id" in out.columns:
        out = out[out["id"].notna()].copy()
        out["id"] = out["id"].astype(int)
    if "team_id" in out.columns:
        out["team_id"] = out["team_id"].fillna(-1).astype(int)
    defaults = {"price":0.0,"expected_gw_points":0.0,"expected_minutes":0.0,
                "minutes_probability":0.7,"fixture_next3":0.5,"fixture_next5":0.5,
                "value":0.0,"value_score":0.0,"transfer_score":0.0,
                "captain_score":0.0,"ownership":0.0}
    for col, default in defaults.items():
        if col in out.columns:
            out[col] = out[col].fillna(default).astype(float)
    return out


def _fixture_map(fixtures):
    out={}
    for f in fixtures or []:
        event=f.get("event")
        if not event: continue
        for tid,home in ((f.get("team_h"),True),(f.get("team_a"),False)):
            if tid is not None:
                out.setdefault((int(tid),int(event)),[]).append((home,f))
    return out


def _quality(team_id,event,fmap):
    rows=fmap.get((int(team_id),int(event)),[])
    if not rows: return 0.0,0
    vals=[]
    for home,f in rows:
        key="team_h_difficulty" if home else "team_a_difficulty"
        vals.append(_num(f.get(key),3.0))
    return max(0.0,min(1.0,(5.0-sum(vals)/len(vals))/4.0)),len(rows)


def _matrix(df,fixtures,start_gw,horizon=4):
    df=_clean_df(df); fmap=_fixture_map(fixtures)
    events=list(range(int(start_gw),min(38,int(start_gw)+int(horizon)-1)+1))
    rows=[]
    for _,p in df.iterrows():
        base=_num(p.get("expected_gw_points")); current=max(.15,min(1.0,_num(p.get("fixture_next3"),.5)))
        row={"id":int(p["id"]),"name":str(p.get("name","?"))}
        for gw in events:
            q,count=_quality(p["team_id"],gw,fmap)
            if not count:
                val=0.0
            else:
                mult=(.86+.28*q)/(.86+.28*current)
                minutes=.92+.08*max(0.0,min(1.0,_num(p.get("minutes_probability"),.7)))
                val=base*mult*minutes
                if count>1: val*=1.0+.82*(count-1)
            row[gw]=round(max(0.0,val),3)
        rows.append(row)
    return pd.DataFrame(rows).set_index("id") if rows else pd.DataFrame()


def _legal_xi(squad, points):
    squad=_clean_df(squad)
    if squad.empty: return [],0.0
    clean={}
    for k,v in (points or {}).items():
        try: clean[int(k)]=_num(v)
        except Exception: pass
    groups={p: squad[squad.position.astype(str)==p].copy() for p in ("GKP","DEF","MID","FWD")}
    best=None
    for d,m,f in FORMATIONS:
        if len(groups["GKP"])<1 or len(groups["DEF"])<d or len(groups["MID"])<m or len(groups["FWD"])<f: continue
        chosen=[]
        for pos,n in (("GKP",1),("DEF",d),("MID",m),("FWD",f)):
            g=groups[pos].copy(); g["_score"]=g["id"].map(clean).fillna(0.0).astype(float)
            chosen.append(g.sort_values("_score",ascending=False).head(n))
        xi=pd.concat(chosen,ignore_index=True)
        score=_num(xi["_score"].sum())
        if best is None or score>best[0]: best=(score,xi)
    return (best[1].to_dict("records"),best[0]) if best else ([],0.0)


def _projection(ids,df,matrix,gameweeks):
    df=_clean_df(df); ids={int(x) for x in ids}; squad=df[df.id.isin(ids)].copy()
    total=0.0; by={}; xis={}
    for gw in gameweeks:
        if gw not in matrix.columns: continue
        xi,score=_legal_xi(squad,matrix[gw].to_dict()); by[gw]=_num(score); xis[gw]=xi; total+=_num(score)
    return {"total":total,"by_gw":by,"xi_by_gw":xis}


def _transfers(ids,df,matrix,bank,free_transfers,horizon):
    df=_clean_df(df); ids={int(x) for x in ids}; current=df[df.id.isin(ids)].copy(); gws=list(matrix.columns)[:horizon]
    baseline=_num(_projection(ids,df,matrix,gws)["total"]); pool=df.copy()
    if gws:
        vals=matrix[gws].apply(pd.to_numeric,errors="coerce").sum(axis=1).to_dict(); pool["horizon"]=pool.id.map(vals).fillna(0.0).astype(float)
    else: pool["horizon"]=0.0
    pool=pool.sort_values(["horizon","expected_gw_points"],ascending=False); out=[]
    for _,old in current.iterrows():
        sell=_num(old.get("selling_price",old.get("price"))); pos=str(old.get("position"))
        candidates=pool[(pool.position==pos)&(~pool.id.isin(ids))].head(24)
        for _,new in candidates.iterrows():
            buy=_num(new.get("price"))
            if buy>_num(bank)+sell+1e-9: continue
            new_ids=ids-{int(old.id)}|{int(new.id)}
            counts=Counter(int(x) for x in df[df.id.isin(new_ids)].team_id.tolist())
            if max(counts.values(),default=0)>3: continue
            proj=_num(_projection(new_ids,df,matrix,gws)["total"]); hit=0 if int(free_transfers)>=1 else 4
            out.append({"out_id":int(old.id),"out":str(old.get("name","?")),"in_id":int(new.id),"in":str(new.get("name","?")),"position":pos,"cost":buy-sell,"projected_gain":round(proj-baseline,2),"hit":hit,"net_gain":round(proj-baseline-hit,2),"new_total":round(proj,2)})
    return sorted(out,key=lambda x:(x["net_gain"],x["projected_gain"]),reverse=True)


def _chips(df,fixtures,ids,budget,matrix):
    rows=[]; df=_clean_df(df); ids={int(x) for x in ids}; squad=df[df.id.isin(ids)]; fmap=_fixture_map(fixtures)
    for gw in matrix.columns:
        points=matrix[gw].to_dict(); xi,xi_score=_legal_xi(squad,points); xi_ids={int(p["id"]) for p in xi}
        bench=squad[~squad.id.isin(xi_ids)].copy(); bench["_p"]=bench.id.map(points).fillna(0.0).astype(float)
        bb=_num(bench["_p"].sum()); cap=max([_num(points.get(i)) for i in ids] or [0.0])
        temp=df.copy(); temp["expected_gw_points"]=temp.id.map(points).fillna(0.0).astype(float)
        fh=select_squad(temp,_num(budget)); fh_value=0.0
        if fh:
            fh_value=sum(_num(points.get(int(p["id"]))) for p in fh[3])
        counts=[len(fmap.get((int(t),int(gw)),[])) for t in df.team_id.unique()]
        rows.append({"gw":int(gw),"tc_value":round(cap,2),"bb_value":round(bb,2),"fh_value":round(fh_value-_num(xi_score),2),"double_teams":sum(n>=2 for n in counts),"active_teams":sum(n>=1 for n in counts),"blank":sum(n>=1 for n in counts)<20,"double":any(n>=2 for n in counts)})
    return pd.DataFrame(rows)


def _wildcard(df,ids,budget,matrix,horizon):
    gws=list(matrix.columns)[:horizon]
    if not gws:return None
    current=_num(_projection(ids,df,matrix,gws)["total"]); scores=matrix[gws].apply(pd.to_numeric,errors="coerce").sum(axis=1).to_dict()
    temp=_clean_df(df); temp["expected_gw_points"]=temp.id.map(scores).fillna(0.0).astype(float)
    result=select_squad(temp,_num(budget))
    if not result:return None
    _,cost,squad,_,_=result; optimal=_num(_projection({int(p["id"]) for p in squad},df,matrix,gws)["total"])
    return {"gain":round(optimal-current,2),"current":round(current,2),"optimal":round(optimal,2),"cost":round(_num(cost),1),"ids":{int(p["id"]) for p in squad}}


def decision_summary(df,fixtures,squad_ids,budget,bank,free_transfers,start_gw,horizon=4):
    """Never fail the complete page because one optional scenario is malformed."""
    df=_clean_df(df); horizon=max(1,min(6,int(horizon or 4))); ids={int(x) for x in squad_ids}
    matrix=_matrix(df,fixtures,int(start_gw),horizon=horizon); gws=list(matrix.columns)[:horizon]
    current=_projection(ids,df,matrix,gws)
    try: transfers=_transfers(ids,df,matrix,_num(bank),int(free_transfers),horizon)
    except Exception: transfers=[]
    try: two=None
    except Exception: two=None
    try: chips=_chips(df,fixtures,ids,_num(budget),matrix)
    except Exception: chips=pd.DataFrame()
    try: wildcard=_wildcard(df,ids,_num(budget),matrix,horizon)
    except Exception: wildcard=None
    best=transfers[0] if transfers else None
    action="TRANSFER" if best and _num(best.get("net_gain"))>.5 else "HOLD"
    return {"matrix":matrix,"current":current,"transfers":transfers,"two_transfers":two,"chips":chips,"wildcard":wildcard,"best_action":action}
