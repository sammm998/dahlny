# Utvärdering (SPEC 11)

```
eval/
  projects/{namn}/input/      # förfrågningsunderlag – KONFIDENTIELLT, checkas aldrig in
  projects/{namn}/input/MANIFEST.json   # filnamn + sha256, checkas in
  projects/{namn}/expected/   # facit (JSON), checkas in
  synthetic/                  # syntetiska ritningar med exakt facit (fas 7)
  reports/                    # genererade rapporter (gitignorerade)
  run_eval.py                 # `make eval`
```

Förfrågningsunderlag checkas aldrig in, så indatafilerna för Bilaga A läggs dit lokalt (de följer med `vs-kalkyl-start.zip`):

```bash
cp 11_5_Teknisk_Beskrivning_VS.pdf 12_4_Ritningar_VS.pdf prixel_exempelrad_B202B.png tb_utdrag_PRB12.png \
   eval/projects/arjang_tvatthall/input/
```

`make eval` kontrollerar att filerna matchar `MANIFEST.json` (sha256) och skriver en rapport per projekt med
måtten i SPEC 11.2. Mått vars pipeline-steg inte finns ännu redovisas som "ej mätt (fas N)" – aldrig som 0 %.

När indata finns körs fas 1 på projektet och jämförs med `pages.json`. AI-anropen loggas i `ai_run`
(kräver databasen); `make eval ARGS=--no-ai` – eller `python eval/run_eval.py --no-ai` – kör bara de
deterministiska vägarna. `eval/tools/` innehåller mätskripten för ritningsmotorn.
