# T5 etikettläsning mot vvs_engine – Bilaga A (2026-11-02)

**Läge:** T5 är byggd (`backend/app/drawings/labels.py`) men **visionbenet är inte kört** – `ANTHROPIC_API_KEY`
fanns inte i sessionens miljö. Det som är mätt här är T5:s OCR-ben (RapidOCR) och vvs_engine på de 88 etiketterna
i A.4. Siffrorna för hela T5 (vision + OCR + omläsning) och kostnaden fylls i när nyckeln finns.

Mätverktyg: `eval/tools/label_metrics.py` (definitionerna står i filens hjälptext).

| | Exakt | Flaggad | Felläst (hela, fel tecken) | Ofullständig (bara en del) | Saknas | Tid (3 blad) | AI-kostnad |
| --- | --- | --- | --- | --- | --- | --- | --- |
| vvs_engine (gren `claude/friendly-davinci-vuqjxl`) | **36** | 0 | 12 | 36 | 4 | ≈ 100 s | 0 |
| T5, bara OCR-benet | **79** | 7 | 0 | 0 | 2 | 287 s | 0 |
| T5, vision + OCR + omläsning | – | – | – | – | – | – | – |

Läs tabellen så här:
- **vvs_engine** har 48 tysta fel: läsningar som är fel eller avkortade men inte flaggade
  (`AV2O1-15`, `KVO1`, `VG+` utan siffror, `S02-P2-7`). Motorn flaggar bara tecken den inte känner igen alls (`?`).
- **T5 utan vision** läser 79 av 88 exakt och har inga tysta fel. Men varje etikett har då bara *en* läsare, så
  konfidensen har tak vid 0,75 och **alla** läsningar – även de 79 exakta – går till granskning. Det är först
  visionbenet som kan ge två oberoende läsningar som är överens (0,98) och därmed etiketter som klarar sig utan
  granskning.
- OCR-benets återstående fel: `KV01-K5-15` → `KV01-K5-1`, `VV01-K1-15-F` → `VV01-K1-1`, `KV01-K1-15-W` →
  `01-K1-15-W` (avkortade, alla flaggade), `CL+2550` → `CL+255Q`, `IHOPKOPPLING` → `OPKOPPLING`, och
  gradtecknet: `80°C` och `60°C` saknas.
- Mätningen jämför text per ritning (facit saknar positioner). Facit är ett urval: T5 läste 1 048 textrader på de
  tre bladen, så precision (påhittade etiketter) är inte mätt här.

## Hur T5 fungerar

1. Bitar på 1024 px i 300 dpi med 20 % överlapp (`tiles.*` i thresholds.yaml); tomma bitar hoppas över
   (Bilaga A: 242 av 324 bitar läses).
2. Vision (T5, `claude-opus-5-5`, schema enligt SPEC 7.4) och OCR (RapidOCR, även vriden 90° för lodrät text)
   läser varje bit oberoende. `tile_has_cut_text` → biten förstoras och läses om.
3. Dubbletter från överlappen slås ihop; vision- och OCR-läsningar paras ihop efter läge.
4. Lika tecken för tecken → 0,98. Olika → etiketten skärs ut i 600 dpi och läses om av T5R (`claude-fable-5-1`)
   med båda läsningarna som alternativ; väljer omläsningen en av dem säkert → 0,85, annars flaggad (< 0,8).
   En läsare → tak 0,75, flaggad.
5. Varje AI-anrop loggas i `ai_run`; kommandot summerar kostnaden för sina egna anrop.

Uppskattad kostnad för visionbenet på Bilaga A: 242 bitar med Opus 5.5 – i storleksordningen 10–25 USD
(bild + prompt ≈ 2–3 k tokens in, svar + tänkande 1–4 k tokens ut per bit), plus omläsningar. Mäts när det körs.

## Köra när nyckeln finns

```bash
cd backend && .venv/bin/python -m app.drawings.labels ../eval/projects/arjang_tvatthall/input/12_4_Ritningar_VS.pdf \
  --pages 2,3,4 --out /tmp/t5.json
python ../eval/tools/label_metrics.py ../eval/projects/arjang_tvatthall/expected/labels.json T5=/tmp/t5.json
```

## Förslag (preliminärt): T5:s etiketter in i motorns tilldelning

Redan OCR-benet slår motorns textläsning tydligt; förslaget gäller under förutsättning att hela T5 bekräftar det.
**Inget är byggt.**

- **Var:** motorn bygger sina textrader i `prepare_page` (`merge_lines(srows + vtext.rows)`) innan beteckningar,
  ledarlinjer, ankare och rörgraf. Det är den enda punkten där texten behöver bytas – allt efter använder radernas
  läge, lutning och understrykning, inte hur texten lästes.
- **Hur:** motorn får en extern etikettfil (`vvs-takeoff analyze … --labels t5.json`, eget `artifact_schema`).
  För varje motorrad som överlappar en T5-etikett byts *texten* ut men radens geometri och `provenance`
  (strecken som är text och inte ska bli rör) behålls. T5-etiketter utan motorrad blir nya rader; deras
  `provenance` är de glyfstora strecken inom etikettens låda.
- **Spårbarhet:** raden får `source="t5"` och T5:s `read_confidence`. En flaggad etikett (< 0,8) gör beteckningen
  `needs_review`, och rören den äger hamnar i REVIEW-nivån – en osäker läsning kan aldrig ge bekräftade meter.
- **Determinism:** etikettfilens hash ingår i motorns indatahash (`freeze-manifest.json`).
- **Mätning:** Årjäng (A.4 + mängder) och korpusgrinden före och efter, med T5 av/på.
