import html
from collections import Counter

import streamlit as st

# Run the maintained v2 application, but patch its data/model imports and
# replace the Gameweek Plan presentation with a proper manager dashboard.
source = open("streamlit_app_v2.py", encoding="utf-8").read()
source = source.replace(
    'from main import load_fpl, load_fixtures, build_players, assign_recommendations, select_squad, build_around_players',
    'from main import load_fpl, load_fixtures\nfrom fpl_model_v2 import build_players, assign_recommendations\nfrom fast_squad_optimizer import select_squad, build_around_players, _valid, _objective, _starting_xi',
)
source = source.replace(
    'from decision_engine_v2 import current_gameweek, load_manager, decision_summary',
    '''from decision_engine_v2 import current_gameweek, load_manager as _load_manager, decision_summary

def load_manager(entry_id, event):
    try:
        return _load_manager(entry_id, event)
    except Exception as exc:
        message = str(exc)
        if "HTTP 404" in message and "/picks/" in message:
            from decision_engine import _get
            entry = _get(f"/entry/{int(entry_id)}/")
            return entry, None
        raise'''
)
source = source.replace('6-GW projeksjon', '4-GW projeksjon')
source = source.replace('de neste 6 Gameweeks', 'de neste 4 Gameweeks')
source = source.replace('over 6 GW', 'over 4 GW')
source = source.replace('neste 6 GW', 'neste 4 GW')
source = source.replace('horizon=6', 'horizon=4')

# Keep the manager sync behaviour that already works: if current picks are not
# published, load the newest available event instead of failing the Team ID.
source = source.replace(
    'manager_ids=[int(x["element"]) for x in manager_picks.get("picks",[])][:15]',
    'manager_ids=[int(x["element"]) for x in manager_picks.get("picks",[])][:15] if manager_picks else []\n        if manager_picks is None:\n            st.sidebar.info("FPL-laget er funnet. FPL har ikke publisert spillerlisten for denne Gameweeken ennå. Den hentes automatisk når picks blir tilgjengelig.")'
)
source = source.replace(
    'st.sidebar.error(f"Fant ikke FPL-laget med ID {entry_id_text}. Sjekk at ID-en er riktig og at laget er registrert i FPL.")',
    'st.sidebar.error(f"Kunne ikke hente FPL-laget {entry_id_text}. {type(exc).__name__}: {exc}")'
)

# Replace only the Gameweek Plan tab. All other tools remain in v2.
tab_start = source.index('with tab1:')
tab_end = source.index('\nwith tab2:', tab_start)

new_tab = r'''with tab1:
    # ========================================================
    # MANAGER DASHBOARD
    # ========================================================
    st.markdown("""
    <style>
    .gw-hero{padding:1.15rem 1.35rem;border-radius:20px;background:linear-gradient(135deg,#111827,#1f2937);border:1px solid rgba(255,255,255,.08);margin:.2rem 0 1rem}
    .gw-hero h2{margin:0;font-size:1.8rem}.gw-hero p{margin:.3rem 0 0;opacity:.65}
    .stat-card{padding:1rem 1.05rem;border-radius:16px;background:linear-gradient(145deg,#111827,#182235);border:1px solid rgba(255,255,255,.08);min-height:104px;box-shadow:0 8px 22px rgba(0,0,0,.12)}
    .stat-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;opacity:.58;font-weight:800}.stat-value{font-size:1.75rem;font-weight:900;margin-top:.2rem}.stat-sub{font-size:.72rem;opacity:.58;margin-top:.1rem}
    .dash-panel{padding:1rem 1.05rem;border-radius:18px;background:rgba(17,24,39,.72);border:1px solid rgba(255,255,255,.08);box-shadow:0 8px 26px rgba(0,0,0,.12);margin-bottom:1rem}.dash-panel h3{margin:.05rem 0 .75rem}
    .manager-pitch{position:relative;overflow:hidden;padding:1rem .75rem 1.05rem;border-radius:22px;border:1px solid rgba(155,235,178,.25);background:#246d40;background-image:url("data:image/svg+xml,%3Csvg xmlns='http%3A//www.w3.org/2000/svg' viewBox='0 0 1000 650' preserveAspectRatio='none'%3E%3Cg fill='none' stroke='white' stroke-opacity='.23' stroke-width='2'%3E%3Crect x='12' y='12' width='976' height='626'/%3E%3Cline x1='12' y1='325' x2='988' y2='325'/%3E%3Ccircle cx='500' cy='325' r='72'/%3E%3Cpath d='M350 12v133h300V12M350 638V505h300v133M425 12v58h150V12M425 638v-58h150v58'/%3E%3C/g%3E%3Cg fill='white' fill-opacity='.2'%3E%3Ccircle cx='500' cy='325' r='3'/%3E%3C/g%3E%3C/svg%3E");background-size:100% 100%;box-shadow:inset 0 0 70px rgba(0,0,0,.16)}
    .pitch-title{text-align:center;font-size:.65rem;font-weight:900;letter-spacing:.13em;color:rgba(255,255,255,.65);margin-bottom:.25rem}.pitch-row{display:flex;justify-content:space-around;align-items:flex-start;gap:.25rem;min-height:112px}.pitch-player{text-align:center;flex:1;min-width:0}.pitch-player img,.pitch-fallback{width:58px;height:58px;object-fit:contain;border-radius:50%;border:2px solid rgba(255,255,255,.92);background:#20242d;margin:0 auto;display:block}.pitch-fallback{display:flex;align-items:center;justify-content:center;color:white;font-weight:900}.pitch-name{font-size:.76rem;font-weight:850;margin-top:.15rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.pitch-points{font-size:.69rem;opacity:.78}.badge-cap{display:inline-block;margin-left:.2rem;background:#171b24;color:#fff;border-radius:50%;width:18px;height:18px;line-height:18px;font-size:.62rem;font-weight:900}.badge-vice{display:inline-block;margin-left:.2rem;background:#374151;color:#fff;border-radius:50%;width:18px;height:18px;line-height:18px;font-size:.62rem;font-weight:900}.bench-strip{display:grid;grid-template-columns:repeat(4,1fr);gap:.55rem}.bench-item{padding:.6rem .35rem;border-radius:13px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.07);text-align:center}.bench-item img,.bench-item .pitch-fallback{width:48px;height:48px}.bench-name{font-size:.72rem;font-weight:800;margin-top:.15rem}.bench-meta{font-size:.64rem;opacity:.6}
    .score-good{color:#72e59a}.score-neutral{color:#f6d77b}.score-bad{color:#ff9187}.transfer-box{padding:.9rem 1rem;border-radius:14px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.08);margin:.55rem 0}.transfer-arrow{font-weight:900}.mini-list{display:flex;flex-direction:column;gap:.35rem}.mini-row{display:flex;justify-content:space-between;gap:.5rem;padding:.5rem .6rem;border-radius:10px;background:rgba(255,255,255,.035)}
    @media(max-width:800px){.bench-strip{grid-template-columns:repeat(2,1fr)}.pitch-row{min-height:96px}.pitch-player img,.pitch-fallback{width:48px;height:48px}}
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="gw-hero"><h2>🧠 Gameweek Decision Engine</h2><p>Din faktiske FPL-tropp · faktiske poeng · statistisk vurdering av neste trekk</p></div>', unsafe_allow_html=True)

    if not manager_ids or not manager_picks:
        st.info("Legg inn FPL Team ID i sidepanelet og trykk «Hent mitt FPL-lag». Når FPL har publisert picks, vises laget automatisk her.")
    else:
        picks = list(manager_picks.get("picks",[]) or [])
        pick_map = {int(x.get("element")): x for x in picks}
        # FPL's entry_history is the authoritative GW score. Do not replace it
        # with modelled expected points.
        history = manager_picks.get("entry_history",{}) or {}
        actual_points = history.get("points")
        if actual_points is None:
            actual_points = 0
            for pick in picks:
                pid=int(pick.get("element",0)); p=PLAYER_LOOKUP.get(pid,{})
                actual_points += int(pick.get("multiplier",1) or 1) * int(p.get("event_points",0) or 0)
        actual_points=float(actual_points)
        bench_points=float(history.get("points_on_bench",0) or 0)
        transfer_cost=float(history.get("event_transfers_cost",0) or 0)
        net_points=actual_points-transfer_cost

        # FPL positions 1-11 are the actual XI, 12-15 are bench order.
        ordered=sorted(picks,key=lambda x:int(x.get("position",99)))
        xi_picks=ordered[:11]; bench_picks=ordered[11:15]
        xi=[]; bench=[]
        for pick in xi_picks:
            pid=int(pick.get("element",0)); p=dict(PLAYER_LOOKUP.get(pid,{}))
            if p:
                p["is_captain"]=bool(pick.get("is_captain")); p["is_vice"]=bool(pick.get("is_vice_captain")); p["actual_points"]=float(p.get("event_points",0) or 0); xi.append(p)
        for pick in bench_picks:
            pid=int(pick.get("element",0)); p=dict(PLAYER_LOOKUP.get(pid,{}))
            if p:
                p["actual_points"]=float(p.get("event_points",0) or 0); bench.append(p)

        cap=next((p for p in xi if p.get("is_captain")),None)
        vice=next((p for p in xi if p.get("is_vice")),None)
        formation=f'{sum(p.get("position")=="DEF" for p in xi)}-{sum(p.get("position")=="MID" for p in xi)}-{sum(p.get("position")=="FWD" for p in xi)}'
        team_value=float(manager_entry.get("last_deadline_value",0) or 0)/10.0 if manager_entry else 0
        bank=float(manager_entry.get("last_deadline_bank",0) or 0)/10.0 if manager_entry else float(manager_bank)
        rank=manager_entry.get("summary_overall_rank") if manager_entry else None
        total=manager_entry.get("summary_overall_points") if manager_entry else None
        free_ft=int((manager_picks.get("_sync") or {}).get("free_transfers",free_transfers_manual))

        c1,c2,c3,c4,c5=st.columns(5)
        c1.markdown(f'<div class="stat-card"><div class="stat-label">GW{current_gw} poeng</div><div class="stat-value score-good">{actual_points:.0f}</div><div class="stat-sub">Faktisk FPL-score</div></div>',unsafe_allow_html=True)
        c2.markdown(f'<div class="stat-card"><div class="stat-label">Snitt</div><div class="stat-value">{(actual_points/current_gw):.1f}</div><div class="stat-sub">Sesongsnitt</div></div>',unsafe_allow_html=True)
        c3.markdown(f'<div class="stat-card"><div class="stat-label">Lagverdi</div><div class="stat-value">£{team_value:.1f}m</div><div class="stat-sub">Bank £{bank:.1f}m</div></div>',unsafe_allow_html=True)
        c4.markdown(f'<div class="stat-card"><div class="stat-label">Free transfers</div><div class="stat-value">{free_ft}</div><div class="stat-sub">Neste GW</div></div>',unsafe_allow_html=True)
        rank_text=f'{int(rank):,}' if rank is not None else 'Ikke tilgjengelig'
        total_text=f'{int(total):,}' if total is not None else '–'
        c5.markdown(f'<div class="stat-card"><div class="stat-label">Overall</div><div class="stat-value">{total_text}</div><div class="stat-sub">Rank {rank_text}</div></div>',unsafe_allow_html=True)

        left,right=st.columns([1.35,.9],gap="large")
        with left:
            st.markdown(f'<div class="dash-panel"><h3>🏟️ Laget mitt · GW{current_gw} <span style="float:right;opacity:.6;font-size:.75rem">{formation}</span></h3>',unsafe_allow_html=True)
            def pitch_player(p):
                url=str(p.get("image_url","") or "").strip(); name=html.escape(p.get("name","?")); pts=p.get("actual_points",0)
                if url:
                    avatar=f'<img src="{html.escape(url)}" alt="{name}" loading="lazy" onerror=\'this.style.display="none";this.nextElementSibling.style.display="flex"\'>'
                    avatar+=f'<span class="pitch-fallback" style="display:none">{html.escape(name[:2].upper())}</span>'
                else:
                    avatar=f'<span class="pitch-fallback">{html.escape(name[:2].upper())}</span>'
                badge='<span class="badge-cap">C</span>' if p.get("is_captain") else ('<span class="badge-vice">V</span>' if p.get("is_vice") else '')
                return f'<div class="pitch-player">{avatar}<div class="pitch-name">{name}{badge}</div><div class="pitch-points">{pts:.0f} p</div></div>'
            groups={"FWD":[],"MID":[],"DEF":[],"GKP":[]}
            for p in xi: groups[p.get("position")].append(p)
            st.markdown('<div class="manager-pitch"><div class="pitch-title">DIN STARTING XI</div>',unsafe_allow_html=True)
            for pos in ["FWD","MID","DEF","GKP"]:
                st.markdown('<div class="pitch-row">'+''.join(pitch_player(p) for p in groups[pos])+'</div>',unsafe_allow_html=True)
            st.markdown('</div>',unsafe_allow_html=True)
            st.markdown('<div style="height:.5rem"></div><b>🪑 Benk</b>',unsafe_allow_html=True)
            bench_html=''.join(f'<div class="bench-item">{pitch_player(p)}</div>' for p in bench)
            st.markdown(f'<div class="bench-strip">{bench_html}</div>',unsafe_allow_html=True)
            st.markdown('</div>',unsafe_allow_html=True)

        with right:
            st.markdown('<div class="dash-panel"><h3>📊 GW-poengfordeling</h3>',unsafe_allow_html=True)
            bypos=Counter()
            for p in xi: bypos[p.get("position")]+=float(p.get("actual_points",0))*(2 if p.get("is_captain") else 1)
            labels=[("Angrep",bypos["FWD"]),("Midtbane",bypos["MID"]),("Forsvar",bypos["DEF"]),("Keeper",bypos["GKP"])]
            for label,val in labels:
                pct=(val/actual_points*100) if actual_points else 0
                st.markdown(f'<div class="mini-row"><span>{label}</span><b>{val:.0f} p <span style="opacity:.55">({pct:.0f}%)</span></b></div>',unsafe_allow_html=True)
            st.markdown(f'<div style="text-align:center;font-size:2.2rem;font-weight:900;margin:.7rem 0">{actual_points:.0f}<div style="font-size:.7rem;opacity:.55;font-weight:700">TOTAL GW{current_gw}</div></div>',unsafe_allow_html=True)
            st.markdown('</div>',unsafe_allow_html=True)

            top=sorted(xi,key=lambda p:p.get("actual_points",0),reverse=True)[:5]
            st.markdown('<div class="dash-panel"><h3>🏆 Topp 5 poeng</h3>',unsafe_allow_html=True)
            for i,p in enumerate(top,1):
                extra=' ×2' if p.get("is_captain") else ''
                st.markdown(f'<div class="mini-row"><span>{i}. <b>{html.escape(p.get("name","?"))}</b></span><b>{float(p.get("actual_points",0)):.0f}{extra}</b></div>',unsafe_allow_html=True)
            st.markdown('</div>',unsafe_allow_html=True)

        # Next-GW recommendation engine: show modelled players, but keep actual
        # GW score completely separate from expected points.
        st.markdown(f'<div class="dash-panel"><h3>🎯 Gameweek {current_gw+1} · foreløpig plan</h3>',unsafe_allow_html=True)
        try:
            summary=decision_summary(df,fixtures,manager_ids,float(budget),float(bank),int(free_ft),current_gw,horizon=4)
            best=summary.get("transfers",[])[0] if summary.get("transfers") else None
            if best:
                st.markdown(f'<div class="transfer-box"><b>ANBEFALT BYTTE</b><div style="font-size:1.1rem;margin-top:.3rem"><span class="transfer-arrow">{html.escape(str(best.get("out","?")))}</span> → <span class="score-good">{html.escape(str(best.get("in","?")))}</span></div><div style="opacity:.7;margin-top:.3rem">Forventet gevinst over 4 GW: <b>{float(best.get("projected_gain",0)):+.2f}</b> · Hit: -{best.get("hit",0)} · Netto: <b>{float(best.get("net_gain",0)):+.2f}</b></div></div>',unsafe_allow_html=True)
            else:
                st.info("Ingen transfer gir tydelig positiv nettoverdi akkurat nå. HOLD er et gyldig modellresultat.")
            proj=summary.get("current",{}).get("by_gw",{})
            if proj:
                st.markdown('<div class="mini-list">'+''.join(f'<div class="mini-row"><span>GW{gw}</span><b>{float(val):.1f} forventede XI-poeng</b></div>' for gw,val in proj.items())+'</div>',unsafe_allow_html=True)
            st.caption("Dette er modellens forventninger — ikke faktiske poeng. Faktiske GW-poeng hentes direkte fra FPL og vises separat øverst.")
        except Exception as exc:
            st.warning(f"Neste GW-analyse kunne ikke beregnes akkurat nå: {exc}")
        st.markdown('</div>',unsafe_allow_html=True)

        # Explicit points audit: actual FPL score is never confused with the model.
        st.markdown('<div class="dash-panel"><h3>🔍 Poengkontroll</h3>',unsafe_allow_html=True)
        st.markdown(f'**Faktisk FPL-score:** {actual_points:.0f} poeng · **Transferkostnad:** -{transfer_cost:.0f} · **Netto:** {net_points:.0f} · **På benken:** {bench_points:.0f}')
        st.caption("FPLs egen entry_history.points er fasiten for Gameweek-score. Modellens expected_gw_points brukes kun til prognoser og beslutninger fremover.")
        st.markdown('</div>',unsafe_allow_html=True)
        st.caption(f"Sist synkronisert fra FPL · Gameweek {current_gw} · 4-GW beslutningshorisont")
'''
source = source[:tab_start] + new_tab + source[tab_end:]

# Fix the other pitch renderer as well: attack at the top, defence below
# midfield, and our goalkeeper centered at our goal.
old='''def render_static_pitch(xi,formation,locked_ids=None,title="STARTING XI",key="best-pitch"):
    locked_ids=set(locked_ids or []); by={p:[] for p in ["GKP","DEF","MID","FWD"]}
    for p in xi: by[p["position"]].append(p)
    shape=formation_shape(formation)
    with st.container(key=key):
        st.markdown(f'<div class="pitch-formation">{esc(title)}</div>',unsafe_allow_html=True)
        g=st.columns([1,2,1])
        with g[1]:
            p=by["GKP"][:1]; st.markdown(f'<div class="pitch-slot">{player_card(p[0],p[0]["id"] in locked_ids) if p else ""}</div>',unsafe_allow_html=True)
        for pos in ["DEF","MID"]:
            cols=st.columns(4,gap="small")
            for i,col in enumerate(cols):
                with col:
                    p=by[pos][i] if i<len(by[pos]) and i<shape[pos] else None
                    st.markdown(f'<div class="pitch-slot">{player_card(p,p["id"] in locked_ids) if p else ""}</div>',unsafe_allow_html=True)
        f=by["FWD"][:shape["FWD"]]
        cols=st.columns([1,2,1] if len(f)==1 else [1,1,1])
        if len(f)==1:
            with cols[1]: st.markdown(f'<div class="pitch-slot">{player_card(f[0],f[0]["id"] in locked_ids)}</div>',unsafe_allow_html=True)
        else:
            for i,p in enumerate(f):
                with cols[i]: st.markdown(f'<div class="pitch-slot">{player_card(p,p["id"] in locked_ids)}</div>',unsafe_allow_html=True)
'''
new='''def render_static_pitch(xi,formation,locked_ids=None,title="STARTING XI",key="best-pitch"):
    locked_ids=set(locked_ids or []); by={p:[] for p in ["GKP","DEF","MID","FWD"]}
    for p in xi: by[p["position"]].append(p)
    shape=formation_shape(formation)
    with st.container(key=key):
        st.markdown(f'<div class="pitch-formation">{esc(title)}</div>',unsafe_allow_html=True)
        for pos in ["FWD","MID","DEF"]:
            cols=st.columns(max(1,shape[pos]),gap="small")
            for i,col in enumerate(cols):
                with col:
                    p=by[pos][i] if i<len(by[pos]) else None
                    st.markdown(f'<div class="pitch-slot">{player_card(p,p["id"] in locked_ids) if p else ""}</div>',unsafe_allow_html=True)
        g=st.columns([1,2,1])
        with g[1]:
            p=by["GKP"][:1]; st.markdown(f'<div class="pitch-slot">{player_card(p[0],p[0]["id"] in locked_ids) if p else ""}</div>',unsafe_allow_html=True)
'''
source = source.replace(old,new)

exec(source, globals())
