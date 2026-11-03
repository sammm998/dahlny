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
| 3 | klar (granskningsvyn byggs med UI:t) | A.3: 10/10 av avvikelserna fram till fas 3 (nr 1–4, 7–10, 12); 17 regler registrerade, 12 enhetstester |
| 4 | klar | TESTDATA-register: 26/28 rätt utfall, 2 osäkra, 0 fel (92,9 %; 11.2 kräver ≥ 95 %, resten osäker); RSK-rader 6/6 (DoD); A3-11 hittas; Prixel Excel + urklipp |
| 5 | klar | Furhoffs-utkastet har B201B, B202B, TS501, 5 frågor och radonoptionen (DoD ok); T9-text kontrolleras mot underlaget; .eml + Excelbilaga; Graph/Gmail-stubbar; T10 |
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

## Fas 3 – vad som finns

- `app/rules/engine.py`: `@rule(id)`-register för alla 17 regler i SPEC 6.5, `RuleContext`, `run_rules`.
  Ordlistor och mönster i `config/rules.yaml`. Deterministiska: TB_SELF_CONTRADICTION (samma specifikationsord, olika
  mått; ofullständig mening = info), OPTION_REQUIRED, UNDEFINED_VALUE, DECIDE_WITH_CLIENT (bara produktval),
  MATERIAL_CODE_MISMATCH, TB_QTY_VS_DRAWING, DRAWING_ITEM_NOT_IN_TB, ritningskontrollerna. AI med validerade citat:
  TB_MENTIONED_NOT_ITEMIZED (T4), CONFLICTING_REQUIREMENTS (T3 v3, fältet `conflicts`).
- `app/evaluation/phase3.py` + fas 3-sektion i `make eval`.

## Fas 4 – vad som finns

- `app/articles/register.py`: import CSV/Excel med kolumnmappning (`config/articles.yaml`), avvisar rader med skäl,
  upsert till `article`. `app/articles/match.py`: RSK → leverantörens art.nr (+ fabrikat) → trigram (pg_trgm i
  databasen, samma algoritm i minnet) → T6 (prompt v2, väljer bara bland kandidater) → utfall; tillbehör som TB säger
  att produkten levereras med måste bekräftas (ACCESSORY_NOT_CONFIRMED → request).
- `app/export/prixel.py`: Excel, urklipp (tabbar), API-stub (ÖPPEN FRÅGA 1). Kolumner i `config/prixel.yaml`.
- `eval/projects/arjang_tvatthall/register/TESTDATA_artikelregister.csv` (påhittat) + `expected/matching.json`.

## Fas 5 – vad som finns

- `app/requests/supplier.py`: gruppering per leverantör, frågor ur avvikelserna, optioner separat, mall + T9 med
  deterministisk kontroll (varje beteckning, inga tal utan källa, krav ordagrant), `.eml` (X-Unsent, text + html,
  Excelbilaga). `app/requests/mailbox.py`: Graph- och Gmail-adaptrar, bara utkast, stubbar (ÖPPEN FRÅGA 3).
  `app/requests/replies.py`: T10, pris måste stå ordagrant i svaret. `app/tb/header.py`: projektnamn och beställare.
- `make eval` skriver utkasten till `eval/reports/<projekt>/forfragningar/`.

## Kvar / nästa steg

Fas 6–8: ritningsdelen (beslut S01 DN75, lagret V-53-FE-_-, pilspetsar, symboler A.5, legender, isolering).

Nya ritningar (Higab): testade och delvis rättade, se `docs/nya_ritningar_higab.md` (otilldelat 76 %/62 %/97 %;
kvar: täta knippen, för stor rörgeometri, demonteringsblad i mängdningen, rasterbladet väg D).
