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
| 6–8 | delvis | A.4 88/88 exakt; skala verifierad på båda planerna; otilldelat 16,5 % / 16,2 % (inkl. tvetydigt) – mål 2 % ej nått, varje sträcka listad med orsak i `make eval`; A.5 6/11 exakt, 5 flaggade; A3-5, A3-6, A3-13 hittas; FÖRKLARINGAR + MATRIS FÖR ISOLERING lästa (T2L) |
| 6b | klar | `demo/markerad.pdf`: summering först, alla rör färgade per system × dimension, otilldelat/tvetydigt/utanför i egna färger, ritat som sidinnehåll (Adobe/Bluebeam); `mangdlista.xlsx` (rör, utanför, isolering, rördelar) |
| UI | klar (v1) | React-sida utan byggsteg (`frontend/index.html`, React/htm i `frontend/vendor/`) på `/ui`: projekt, TB-lista, ritning, mängdlista, avvikelser, matchning, förfrågningar, export; klick till källsidan med markering; korrigeringar → `correction` + projektets logg. Testad i Chromium. Uppladdning i UI och SSO: stubbar |
| 12 (demo) | klar | `make demo` kör Årjäng hela vägen → `demo/` (artikellista, avvikelser, mängdlista, markerad PDF, .eml, Prixel) |
| 9 | klar (väg A/B som bibliotek; inte inkopplad i demo/UI) | Syntetisk DXF exakt (7,0 m och 1,5 m, mm-enhet; okänt lager räknas inte; utan $INSUNITS avvisas), syntetisk IFC exakt (IfcPipeSegment + system + Qto-längd + DN); DWG kräver dwg2dxf/ODA (felmeddelande) |
| 10 | ej påbörjad | Kräver ett andra konsultprojekt med facit (ÖPPEN FRÅGA 7); korrigeringarna sparas redan (`correction`) |
| 11 | delvis | Skanning 200 dpi och simulerat foto: etiketter 88/88 exakt, 0 tysta fel; rörmeter 0 m – rastervektorisering saknas (`docs/raster_bilaga_a.md`) |

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

## Fas 6–8 – vad som finns

- Motorn (`claude/t5-labels`): S01 DN75-beslutet (`DEAD_END_LABEL_KEEPS_DN`), pilspetsar (`SMALL_CLOSED_FIGURES_ARE_NOT_PIPE`),
  lagret med tomt systemled (`GENERIC_SYSTEM_LAYER`, V-53-FE-_- på plan 0 mäts nu: 5,0 m, men etiketterna fäster
  inte än – se kvar), rörlistor, rördimensioner, systemmallar.
- dahlny: `app/drawings/context.py` (taggar per plan = största antal på något blad, schemats taggar, rörbeteckningar,
  granskningsfynd → RuleContext), `app/drawings/legend_tables.py` (T2L, celler kontrolleras mot T5),
  `app/drawings/estimates.py` (böjar, isolering ur TB-krav + matris). Adaptern tar `labels=` (T5-fil).
- `make eval` (med `VVS_ENGINE_CMD`) kör T5 + motorn en gång och sparar i `eval/reports/<projekt>/`.

## Kvar / nästa steg

- Otilldelat ≤ 2 %: plan 1 4,0 m + 2,75 m tvetydigt (W40/W – väntar på konsulten), plan 0 7,5 m varav 5,0 m i
  V-53-FE-_- (etiketter S02-P2 2,3 pt från linjen fäster inte – utred anknytningen för generaliserade familjer).
- Fas 10 (stilprofiler) och väg D/E:s rastervektorisering; se `docs/raster_bilaga_a.md`.

Nya ritningar (Higab): testade och delvis rättade, se `docs/nya_ritningar_higab.md` (otilldelat 76 %/62 %/97 %;
kvar: täta knippen, för stor rörgeometri, demonteringsblad i mängdningen, rasterbladet väg D).

## Slutläge 2026-11-03 (för nästa session)

**Mått SPEC 11.2 (Bilaga A, `make eval`):**
- TB-recall 100 %, precision 100 % (0 påhittade).
- RSK 28/28, art.nr 7/7, antal 28/28.
- Matchning 92,9 % rätt, 2 osäkra, 0 fel. Gränsen är 95 %.
- Etiketter 88/88.
- Otilldelat 16,5 % och 16,2 % mot gränsen 2 %.
- Skalan är verifierad.
- Symboler: 7/11 exakta, 4 flaggade.
- Rörmeter ±3 %: ej mätt, eftersom facit med manuell mätning saknas.

**AI:** 11,75 av 50 USD. Draft-PR: sammm998/Dahlvvvs#1. dahlny har bara en gren, så ingen PR är möjlig.

**Korpusgrinden (Dahlvvvs, gren `claude/t5-labels`, körs lokalt innan något slås ihop):**

```bash
python engine/tools/corpus.py run manifest.json /tmp/korpus_utan_t5 --jobs 4
python engine/tools/corpus.py gate /tmp/korpus_utan_t5/corpus.json engine/tests/data/corpus_baseline.json
python engine/tools/corpus.py run manifest.json /tmp/korpus_med_t5 --jobs 4 --labels
python engine/tools/corpus.py gate /tmp/korpus_med_t5/corpus.json engine/tests/data/corpus_baseline.json --only-read
```

Faller grinden utan T5 kan omgångens regler slås av en i taget med `--rule`, t.ex.
`pipeline.GENERIC_SYSTEM_LAYER=false` eller `pipes.ownership.DEAD_END_LABEL_KEEPS_DN=false`.

**Nästa steg i ordning:**
1. Otilldelat på plan 0. I lagret V-53-FE-_- fäster inte etiketterna (S02-P2 slutar 2,3 pt från linjen).
2. Knippesordning för täta KV/VV-knippen (Higab-bladen).
3. Matchningen ≥ 95 %: B101P och RA101 blir osäkra, med T6-score 0,93 och 0,90.
4. Fas 10: stilprofiler och korrigeringsåterföring. Kräver ett andra facitprojekt (ÖPPEN FRÅGA 7).
5. Väg D/E: rastervektorisering.
