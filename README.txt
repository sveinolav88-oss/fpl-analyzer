FPL ANALYZER V1.3.0

INSTALLASJON
1. Åpne CMD i denne mappen.
2. Kjør:
   pip install -r requirements.txt
3. Kjør:
   python -u main.py

V1.3 bruker FPL live-data og fixtures direkte fra FPL API.

FUNKSJONER
- Realistisk expected minutes (ikke automatisk 90 for alle)
- Expected GW points
- Transfer score
- Captain score
- Differential score
- Value score
- Fixture signal for neste 3 og 6 kamper
- BUY / WATCH / AVOID
- Gyldig 15-manns squad optimizer:
  2 GK / 5 DEF / 5 MID / 3 FWD
  maks 3 spillere fra samme klubb
  maks £100m

OUTPUT
data/player_rankings.csv
data/captain_rankings.csv
data/differentials.csv
data/value_rankings.csv
data/best_squad.csv

PRESEASON (valgfritt)
Opprett data/preseason.csv med:
player_id,minutes,starts,goals,assists,shots,xg,xa,notes

NB:
Dette er en beslutningsmodell, ikke en garanti for fremtidige FPL-poeng.
