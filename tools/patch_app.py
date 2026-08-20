from pathlib import Path

p = Path("streamlit_app.py")
s = p.read_text(encoding="utf-8")
old = """source = source.replace(\n    'from main import load_fpl, load_fixtures, build_players, assign_recommendations, select_squad, build_around_players',\n    'from main import load_fpl, load_fixtures, build_players, assign_recommendations\\nfrom fast_squad_optimizer import select_squad, build_around_players, _valid, _objective, _starting_xi',\n)"""
new = """source = source.replace(\n    'from main import load_fpl, load_fixtures, build_players, assign_recommendations, select_squad, build_around_players',\n    'from main import load_fpl, load_fixtures\\nfrom fpl_model_v2 import build_players, assign_recommendations\\nfrom fast_squad_optimizer import select_squad, build_around_players, _valid, _objective, _starting_xi',\n)\n\n# Use a calibrated scoring model. FPL ep_next remains a strong prior, but it\n# is no longer double-discounted by the minutes model.\nsource = source.replace(\n    'c4.metric(f\"Forventede poeng GW{current_gw}\", f\"{top_player.expected_gw_points:.2f}\")',\n    'c4.metric(f\"Beste spillerprognose GW{current_gw}\", f\"{top_player.expected_gw_points:.2f}\")',\n)\nsource = source.replace('6-GW projeksjon', '4-GW projeksjon')\nsource = source.replace('de neste 6 Gameweeks', 'de neste 4 Gameweeks')\nsource = source.replace('over 6 GW', 'over 4 GW')\nsource = source.replace('neste 6 GW', 'neste 4 GW')\nsource = source.replace('horizon=6', 'horizon=4')\n"""
if old not in s:
    raise SystemExit("streamlit_app.py patch anchor not found")
p.write_text(s.replace(old, new), encoding="utf-8")
