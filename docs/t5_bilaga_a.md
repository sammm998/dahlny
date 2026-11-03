# T5 etikettläsning och vvs_engine – Bilaga A (2026-11-03)

Underlag: `12_4_Ritningar_VS.pdf`, blad 2–4 (W-50-1-1000 plan 1, W-53-1-0900 plan 0, W-50-8-1000 flödesschema),
facit A.4 (88 etiketter). Mätverktyg: `eval/tools/label_metrics.py` (etiketter) och
`eval/tools/engine_takeoff_compare.py` (motorns mängder före/efter).

**Rättelse av tidigare siffror:** `label_metrics` godtog flerordstext på två rader bara om varje *ord* var en egen
rad. `VVB 55 LITER` och `Monteras i golvränna` står på ritningen på två rader och lästes rätt (`VVB` över
`55 LITER`) men räknades som flaggade. Med rättningen är alla T5-varianter nedan 88/88 – "87/88" i tidigare
rapporter var mätverktygets fel, inte läsningens.

## 1. Etiketterna (A.4, 88 st)

| Variant | Exakt | Flaggad | Felläst | Ofullst. | Saknas | Tid (3 blad) | AI-kostnad | USD/blad |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| vvs_engine (streckläsning) | 37 | 0 | 12 | 35 | 4 | ≈ 100 s | 0 | 0 |
| T5 bara OCR | 81 | 5 | 0 | 0 | 2 | 287 s | 0 | 0 |
| v1 baslinje: Sonnet på varje bit, seriellt | **88** | 0 | 0 | 0 | 0 | 3 043 s | 5,00 | 1,67 |
| v2: OCR-grind + Haiku sorterar, Sonnet på svåra bitar | 88 | 0 | 0 | 0 | 0 | 1 367 s | 6,86 | 2,29 |
| v3: Haiku läser, Sonnet bara på oeniga utsnitt | 88 | 0 | 0 | 0 | 0 | 688 s | 2,57 | 0,86 |
| **Standard: Sonnet på varje bit, parallellt, en läsning per ställe** | **88** | 0 | 0 | 0 | 0 | **528 s** | **3,94** | 1,84 / 1,43 / 0,68 |

Kostnader i originalpris (cacheträffar räknade till sitt ursprungliga anrop). AI-kostnad för hela omgången
(från 18,47 USD vid omgångens start): **6,52 USD av 30**; totalt sedan 2026-11-02: 24,99 USD.

### Tysta fel utanför facit

Facit är ett urval (88 av ≈ 1 000 textrader). Jämförelsen mellan varianterna, och kontroll mot ritningen där de
skiljer sig, visar två slags tysta fel som facit inte fångar:

- **Fragment vid bitarnas kanter.** Text som skärs av en bits kant läses lika av båda läsarna och godkänns
  (`IATERIAL`, `VS21-` för `VS21-S4-20`, `S01-P2` för `S01-P2-110`). Godkända fragment inne i en längre läsning:
  v1 32, v3 165, **standard 0** – standarden tar bort ett fragment som ligger på samma ställe som en längre läsning
  vars text det är en del av (`one_label_per_place`, `tiles.dedupe_iou`).
- **Haiku och OCR gör samma fel (v3).** 531 etiketter godkändes på Haiku + OCR utan Sonnet. 522 av dem kunde
  jämföras med Sonnets läsning på samma ställe; 10 skiljer sig. Kontrollerat mot ritningen: Haiku och OCR läste
  båda `Z` i en axelbubbla där det står `2`, och `S01-P2` där det står `S01-P2-110` (båda 0,98, godkända). Övriga
  är fragment. **v3 blir därför inte standard**, trots 88/88 och lägst kostnad.

Standarden (`labels_routing: all`) läser båda ställena rätt.

### Hur standarden fungerar

1. Bitar à 1024 px i 300 dpi, 20 % överlapp. Varje bit med bläck läses av Sonnet 5.5 (T5) och av RapidOCR.
2. Avskuren text läses om förstorad om ingen grannbit har en hel läsning av den.
3. Lika läsning → 0,98. Olika → utsnitt i 600 dpi läses om av Sonnet (T5R); kan Sonnet inte avgöra eskaleras
   utsnittet till Opus 5.5. Opus läser aldrig hela bitar. En läsare → tak 0,75, granskas.
4. En läsning per ställe (fragment tas bort).
5. AI-anropen körs parallellt (`defaults.max_concurrency = 8`); rendering och OCR i ordning.
6. Tak per blad `labels_budget_usd_per_sheet` (1 USD är standard; mätningen här kördes med 5 USD per blad, eftersom
   träffsäkerheten går först – ett tätt blad kostar ≈ 1,8 USD). Kostnaden loggas per blad.

`labels_routing: tiles` och `labels` finns kvar för mätning.

## 2. T5-etiketterna i motorns tilldelning (`sammm998/Dahlvvvs`, gren `claude/t5-labels`)

Byggt enligt förslaget: `vvs-takeoff analyze PDF --out DIR --labels t5.json`
(`engine/vvs_engine/text/external_labels.py`).

- Varje T5-etikett tar de motorrader den täcker; texten byts, motorns läsriktning, texthöjd och streck
  (`provenance`) behålls. Har motorn redan läst samma text står dess rad kvar orörd.
- T5:s låda dras åt till de tecken-stora streck som ligger helt inne i den – en rörlinje eller understrykning
  genom lådan räknas inte. Etiketter utan bläck och utan motorrad används inte. Läsningar utan bokstäver och
  siffror (`=`, `-`) används inte: `=` mellan kod och beskrivning gjorde att bladets beteckningslista inte
  hittades.
- En flaggad etikett (< 0,8 eller `needs_review`): rören den namnger får `needs_review` +
  `EXTERNAL_LABEL_UNCERTAIN` och hamnar i REVIEW-nivån.
- Etikettfilens sha256 i frysmanifestet; `sheets/<n>/external-labels.json` per blad.
- Motorns svit: 1 377 gröna (utom samma miljöfel som på main, `test_image_dependencies`), varav 19 nya tester.

### Resultat (motorn utan och med T5-etiketterna)

| | Blad 1 – plan 1 | Blad 2 – plan 0 | Blad 3 – flödesschema |
| --- | --- | --- | --- |
| Otilldelad andel | 27,5 % → **6,6 %** | 27,0 % → **1,7 %** * | 100 % → 100 % (mäts inte) |
| Tvetydig andel | 0 % → 32,5 % | 3,2 % → 15,0 % | – |
| Bekräftade meter | 13,94 → 22,28 | 44,52 → 26,39 | 0 → 0 |
| Etiketter: ny text / nya / oförändrade / osäkra | 157 / 47 / 176 / 62 | 123 / 38 / 157 / 40 | 46 / 16 / 52 / 19 |

\* Nämnaren är de linjefamiljer motorn räknar som rör. Med T5-etiketterna föll S02-familjen bort (se nedan), så
1,7 % är inte jämförbart med 27,0 % – andelen ser bättre ut än mängden är.

Bekräftade meter per system × material × dimension (material ur bladets egen beteckningslista):

| Blad | System | Material | DN | Före | Efter |
| --- | --- | --- | --- | --- | --- |
| 1 | KV01 | K1 koppar, hårda | 15 | 0 | 12,66 |
| 1 | KV01 | K1 koppar, hårda | 28 | 0 | 1,20 |
| 1 | KV01 | K5 koppar, förkromade | 15 | 0 | 2,35 |
| 1 | VV01 | K1 koppar, hårda | 15 | 0 | 5,56 |
| 1 | VV01 | K5 koppar, förkromade | 15 | 0 | 0,51 |
| 1 | L9 | S13 Mapress / – | 28 / 22 / – | 13,94 | **0** |
| 2 | S01 | P2 PP-rör, markavlopp | 110 | 12,59 | 13,71 |
| 2 | S01 | P2 | 75 | 3,75 † | 0,52 |
| 2 | S01 | P2 | 7 ‡ | 0,52 | 0 |
| 2 | S02 | P2 | 110 | 14,85 | **0** |
| 2 | S02 | P2 | 7 ‡ | 0,65 | 0 |
| 2 | S03 | P2 | 110 | 12,16 | 12,16 |

† 2,63 m `S01-P2-75` + 1,12 m `S01-75-P` (skräpläsning). ‡ `S01-P2-7`/`S02-P2-7` var motorns avkortade läsning av
`…-75`; DN7 finns inte.

**Vinster:** vattensystemen KV01 och VV01 på plan 1 mäts för första gången, med material; skräpbeteckningarna
(`S01-P2-7`, `S01-75-P`) är borta; beteckningslistans material läses (`PP-RÖR, MARKAVLOPP` med rätt komma).

**Förluster – inte godtagbara som de är:**

- **S02 på plan 0 (15,5 m) mäts inte.** T5 läser höjdnoterna under rörnamnen hela (`VG+-563`, `VG+-570` …); motorn
  läste dem förut bara som `VG+`. Motorns grammatik tar `VG+-563` för en rörbeteckning (den känner igen `CL` som
  höjd men inte `VG`), så blocket `S02-P2-110` / `VG+-563` blir en bunt med två rader som ska ha två rör. Ledaren
  fäster inte (`NO_PIPE_ATTACHMENT`, före `VERIFIED_PIPE_ATTACHMENT`) och familjen `V-53-FE-_S02-` räknas inte som
  rör. Felet låg redan i motorns grammatik; det syntes inte förrän texten lästes rätt.
- **L9 på plan 1 (13,9 m) mäts inte.** L9-blocken har fortfarande en rad men fäster inte, och L9-familjen
  `V-52F-FE-_L9-` är inte med bland rörfamiljerna. Orsaken är **inte utredd**.

### Tvetydiga rör efter (och varför)

| Blad | Meter | Skäl | Kandidater |
| --- | --- | --- | --- |
| 1 | 6,63 | `AMBIGUOUS_FLOW_BEYOND_THE_LABELLED_RUNS` – röret fortsätter förbi de märkta sträckorna och ingen etikett säger vilken beteckning som gäller där | KV01-K1 DN15 |
| 1 | 2,75 | `AMBIGUOUS_DN_BOUNDARY` – var gränsen mellan två beteckningar går | KV01-K1-W40 DN15, KV01-K1-W DN15 |
| 2 | 2,25 | `AMBIGUOUS_FLOW_BEYOND_THE_LABELLED_RUNS` | S01-P2-(L) DN110 |
| 2 | 0,88 | `AMBIGUOUS_BRANCH` – en förgrening där båda dimensionerna kan fortsätta | S01-P2 DN110, S01-P2 DN75 |
| 2 | 0,79 | `AMBIGUOUS_BRANCH` | S01-P2-(L) DN110, S01-P2 DN75 |

Till det kommer L9 och S02 ovan, som inte är tvetydiga utan inte mätta alls.

## 3. Vad som behövs härnäst (inget byggt)

1. **Höjdnoter i motorns grammatik:** `VG±…` (vattengång) ska behandlas som `CL` – en not om var röret ligger,
   inte ett rör till (`rows_needing_a_pipe`). Det är en ny regel i motorn, och den bör prövas på fler projekt
   än Årjäng innan den läggs in.
2. **L9 på plan 1:** utred varför L9-ankarna slutade fästa.
3. Kör korpusgrinden (`tools/corpus.py`) med och utan `--labels` innan något slås ihop.
