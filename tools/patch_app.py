from pathlib import Path

p = Path("streamlit_app.py")
s = p.read_text(encoding="utf-8")
old = """source = source.replace(\n    'from main import load_fpl, load_fixtures, build_players, assign_recommendations, select_squad, build_around_players',\n    'from main import load_fpl, load_fixtures, build_players, assign_recommendations\\nfrom fast_squad_optimizer import select_squad, build_around_players, _valid, _objective, _starting_xi',\n)"""
new = """source = source.replace(\n    'from main import load_fpl, load_fixtures, build_players, assign_recommendations, select_squad, build_around_players',\n    'from main import load_fpl, load_fixtures\\nfrom fpl_model_v2 import build_players, assign_recommendations\\nfrom fast_squad_optimizer import select_squad, build_around_players, _valid, _objective, _starting_xi',\n)\n\n# Calibrated model wiring. FPL ep_next remains a strong prior, but it is no\n# longer double-discounted by the minutes model.\nsource = source.replace(\n    'c4.metric(f\"Forventede poeng GW{current_gw}\", f\"{top_player.expected_gw_points:.2f}\")',\n    'c4.metric(f\"Beste spillerprognose GW{current_gw}\", f\"{top_player.expected_gw_points:.2f}\")',\n)\nsource = source.replace('6-GW projeksjon', '4-GW projeksjon')\nsource = source.replace('de neste 6 Gameweeks', 'de neste 4 Gameweeks')\nsource = source.replace('over 6 GW', 'over 4 GW')\nsource = source.replace('neste 6 GW', 'neste 4 GW')\nsource = source.replace('horizon=6', 'horizon=4')\n"""
if old in s:
    s = s.replace(old, new, 1)

# Show the metric that actually matters for FPL: XI expectation plus the
# captain's extra points. This is deliberately separate from raw XI points.
anchor = 'st.subheader("🎯 Kaptein og visekaptein"); captain_cards(xi)'
replacement = '''st.subheader("🎯 Kaptein og visekaptein"); captain_cards(xi)
        _cap=max(xi,key=lambda x:float(x.get("captain_score",0))) if xi else None
        _xi_pts=sum(float(x.get("expected_gw_points",0)) for x in xi)
        _cap_pts=float(_cap.get("expected_gw_points",0)) if _cap else 0.0
        _fpl_expected=_xi_pts+_cap_pts
        _bench_pts=sum(float(x.get("expected_gw_points",0)) for x in bench)
        st.markdown("### 📊 FPL-prognose")
        q1,q2,q3,q4=st.columns(4)
        q1.metric("Forventede XI-poeng",f"{_xi_pts:.1f}")
        q2.metric("Kapteinseffekt",f"+{_cap_pts:.1f}")
        q3.metric("Forventet FPL-score",f"{_fpl_expected:.1f}")
        q4.metric("Forventet benk",f"{_bench_pts:.1f}")
        st.caption("Forventet FPL-score = forventede poeng fra startelleveren + kapteinens ekstra poeng. Dette er en modellert forventning, ikke en garanti.")'''
if anchor in s and 'Forventet FPL-score' not in s:
    s = s.replace(anchor, replacement, 1)

p.write_text(s, encoding="utf-8")
