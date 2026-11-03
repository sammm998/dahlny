# Status – VS-Kalkyl

Läs detta först i en ny session. Fasordning enligt SPEC 13. Beslut som tagits utan användaren: `docs/DECISIONS.md`.
Grenar: dahlny `claude/friendly-davinci-vuqjxl`, Dahlvvvs `claude/t5-labels`. Ingenting slås ihop.

AI-budget för bygget: 50 USD, räknat på `ai_run` efter baslinjen – kör `backend/.venv/bin/python eval/tools/ai_spend.py`.
Postgres efter omstart av containern: `pg_ctlcluster 16 main start`. `make check` och `make eval` ska vara gröna.

| Fas | Status | Mått (Bilaga A) |
| --- | --- | --- |
| 0 | klar | `make check` grönt, AI loggas i `ai_run` |
| 1 | klar | 23/23 kontroller (sidtyp, ritningsnr, skala, uppdragsnr, förteckning, TITLEBLOCK_MISMATCH) |
| 2 | klar | 29/29 facitrader (28 + rör), 0 påhittade, RSK 28/28, art.nr 7/7, antal 28/28, golvränna hittad, generella krav 9/9; 0,33 USD |
| 3 | ej påbörjad | |
| 4 | ej påbörjad | |
| 5 | ej påbörjad | |
| 6–8 | delvis (motorn integrerad, se `docs/t5_bilaga_a.md`) | |
| 6b | ej påbörjad | |
| UI | ej påbörjad | |
| 9–12 | ej påbörjade | |

## Fas 2 – vad som finns

- `app/tb/layout.py` (kolumner ur KOD/TEXT/MÄNGD/ENHET, sidhuvud och sidfot bort), `app/tb/segment.py`
  (AMA-sektioner, objektbeteckningar i fetstil, AMA-kod med mängd), `app/tb/quantity.py` (mängdtext → läge).
- `app/tb/extract.py`: T3 per sektion (prompt `T3/v2`), validering mot källtext (RSK, art.nr, typ, citat, barnposters
  antal), T3G generella krav, T4 fullständighet → `TB_MENTIONED_NOT_ITEMIZED`. `app/tb/persist.py` sparar till
  SpecItem/ProjectRule/Deviation (ny kolumn `deviation.question`, migrering 0003).
- `app/evaluation/phase2.py` + `make eval` (fas 2-sektion och 11.2-måtten).

## Kvar / nästa steg

Fas 3: regelmotorn (SPEC 6.5) och A.3-avvikelserna.
