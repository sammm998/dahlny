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

## 3. Omgång 2 (2026-11-03): höjdnoter, rörfamiljer och staplade etiketter

Gren `claude/t5-labels` i Dahlvvvs, commit `b588c3d`. Motorns svit: 1 421 gröna (utom miljötestet
`test_image_dependencies`, som på main). Ingen PR, ingen sammanslagning – korpusgrinden körs lokalt först.

### Vad som ändrades i motorn

- **Höjdnoter är aldrig rör** (svensk standardnotation, SPEC Bilaga B): `CL` och `VG` följt av en höjd, med
  tecknet `+`, `-`, `+-`, `-+`, `±` eller inget. `is_height_note`, `is_code_like` säger nej, radrollen blir
  `elevation`. En höjd med tecknet `+-`/`±` (tecknet enligt konsulten) bärs utan enhet, så ingen lodrät längd
  räknas ur den. Enhetstester för varianterna.
- **Ett lager som bär bladets systemkod är en rörfamilj.** Förut godkändes ett rörlager bara om någon ledare
  råkade rösta på det. S02:s lager på plan 0 fick aldrig någon egen röst (ledarna slutar på streck som
  textläsaren tagit som tecken) och kom in bara via en grannpennas namnmall; L9:s lager på plan 1 fick sin enda
  röst från en linje mellan två textblock. När T5 läste texten vid linjens andra ände (`ANSL. TRYCKLUFT`,
  `AV203-20`) gick linjen till det blocket, och hela L9-lagret föll bort. Nu: ett lager vars namn bär
  systemkoden för en av bladets egna rörbeteckningar (`V-53-FE-_S02-` ↔ `S02-P2-110`, `V-52F-FE-_L9-` ↔ `L9`),
  som ser ut som rör och ritas kraftigare än bladets skrivpenna, är en rörfamilj. Textlagret med samma kod
  (`V-53--T-_S02`, 0,72 pt) är en skrivpenna och tas inte.
- **Staplade etiketter:** T5 levererar `L9` / `28` / `22` som tre rader, inte sammanslaget; motorn gör en enhet
  av dem med DN från dimensionsraderna, och ledaren går till stigarsymbolen. Det staplade var inte felet – det
  var att L9-lagrets enda röst hängde på en linje vars ägare inte går att avgöra ur geometrin. Rättat generellt
  genom regeln ovan, inte genom att flytta linjen.
- Lokal regression (`data/local_facit/t5_labels.json`, checkas inte in): S01/S02/S03 på plan 0 och L9/KV01 på
  plan 1 ska vara rörfamiljer och få meter med etikettfilen; ingen höjdnot får bli rörbeteckning.

### Resultat: före (motorn utan T5) → nya regler utan T5 → nya regler med T5

| | Blad 1 – plan 1 | Blad 2 – plan 0 | Blad 3 – flödesschema |
| --- | --- | --- | --- |
| Otilldelad andel | 27,5 % → 74,7 % → **11,4 %** | 27,0 % → 26,2 % → **19,3 %** | 100 % (mäts inte) |
| Tvetydig andel | 0 % → 0 % → 15,8 % | 3,2 % → 3,2 % → 8,2 % | – |
| Bekräftade meter | 13,94 → 14,60 → **40,66** | 44,52 → 44,52 → **41,89** | 0 |
| Otilldelade meter | 3,55 → 29,01 → 4,83 | 14,32 → 13,72 → 9,26 | – |

Mellankolumnen visar regeln om systemlager utan T5: på plan 1 blir KV- och VV-lagren rörfamiljer, men utan T5
kan motorn inte läsa deras etiketter, så 29 m rör syns men står otilldelade. Bekräftade meter ändras knappt.
Regeln gäller alla ritningar, inte bara Årjäng – därför korpusgrinden.

Bekräftade meter per system × material × dimension (efter, med T5):

| Blad | System | Material | DN | Före | Efter |
| --- | --- | --- | --- | --- | --- |
| 1 | KV01 | K1 koppar, hårda | 15 | 0 | 16,15 |
| 1 | KV01 | K1 koppar, hårda | 28 | 0 | 1,20 |
| 1 | KV01 | K5 koppar, förkromade | 15 | 0 | 2,35 |
| 1 | VV01 | K1 koppar, hårda | 15 | 0 | 5,56 |
| 1 | VV01 | K5 koppar, förkromade | 15 | 0 | 0,51 |
| 1 | L9 | S13 Mapress | 22 | 0 | 5,74 † |
| 1 | L9 | S13 Mapress | 28 | 2,74 | 0,64 |
| 1 | L9 | – | 22 | 5,29 | 5,29 |
| 1 | L9 | – | 28 | 0,17 | 2,93 |
| 1 | L9 | – | – | 5,74 | 0,29 |
| 2 | S01 | P2 PP-rör, markavlopp | 110 | 12,59 | 13,71 |
| 2 | S01 | P2 | 75 | 3,75 ‡ | 0,52 |
| 2 | S01 | P2 | 7 § | 0,52 | 0 |
| 2 | S02 | P2 | 110 | 14,85 | 14,85 |
| 2 | S02 | P2 | 75 | 0 | 0,65 |
| 2 | S02 | P2 | 7 § | 0,65 | 0 |
| 2 | S03 | P2 | 110 | 12,16 | 12,16 |

† `L9-S13-22` lästes förut som `L9-S1? 22` utan dimension (5,74 m "L9 –"); nu med DN22.
‡ 2,63 m `S01-P2-75` + 1,12 m skräpläsningen `S01-75-P`. § motorns avkortade `…-7` av `…-75`; DN7 finns inte.

**Summa per system, hela projektet (bekräftade meter, före → nya regler utan T5 → med T5):**

| System | Före | Regler utan T5 | Med T5 |
| --- | --- | --- | --- |
| KV01 | 0 | 0 | 19,70 |
| VV01 | 0 | 0 | 6,07 |
| L9 | 13,94 | 14,60 | 14,89 |
| S01 | 16,86 | 16,86 | 14,23 |
| S02 | 15,50 | 15,50 | 15,50 |
| S03 | 12,16 | 12,16 | 12,16 |
| **Summa** | **58,46** | **59,12** | **82,55** |

### Tvetydiga rör efter (och varför)

| Blad | Meter | Skäl | Kandidater |
| --- | --- | --- | --- |
| 1 | 6,63 | `AMBIGUOUS_FLOW_BEYOND_THE_LABELLED_RUNS` – röret fortsätter förbi de märkta sträckorna, ingen etikett säger vad det heter där | KV01-K1 DN15 |
| 1 | 0,04 | `SYSTEM_CONFLICT` – två system möts i samma punkt | KV01-K1-W40 DN15, L9 |
| 2 | 2,25 | `AMBIGUOUS_FLOW_BEYOND_THE_LABELLED_RUNS` | S01-P2-(L) DN110 |
| 2 | 0,88 | `AMBIGUOUS_BRANCH` – förgrening där båda dimensionerna kan fortsätta | S01-P2 DN110, S01-P2 DN75 |
| 2 | 0,79 | `AMBIGUOUS_BRANCH` | S01-P2-(L) DN110, S01-P2 DN75 |

**W40/W-gränsen (2,75 m):** med L9-familjen i rörgrafen avgör motorn nu gränsen mellan `KV01-K1-15-W40` och
`KV01-K1-15-W` ur rörnätets form (W: 8,60 → 12,36 m, W40: 3,91 → 3,64 m) – inte ur suffixens betydelse. Båda
beteckningarna bär avvikelse A3-13 (`UNKNOWN_LABEL_TOKEN`, fråga till konsulten), så metrarna är markerade.
Ska gränsen hållas tvetydig tills konsulten svarat behövs en regel som gör två beteckningar som bara skiljer
sig i okända suffix till samma kandidatgrupp – inte byggd.

## 4. Omgång 3 (2026-11-03): lagerregeln bakom flagga, mängdlista, material, otilldelat

### Lagerregeln bara med T5

Dahlvvvs `claude/t5-labels` @ `702ceb8`. Regeln (ett lager som bär systemkoden för en av bladets egna
rörbeteckningar är en rörfamilj) är på bara för blad där en etikettfil har använts
(`layer_name_families=None`, CLI `--layer-name-families auto|on|off`). Familjer som bara regeln tog in loggas
(logging, filmen, `sheets/<n>/layer-name-rule.json`). Utan etikettfil ger Årjäng exakt samma mängder och andelar
som före omgången. Motorns svit: 1 422 gröna.

Korpusgrinden (manifestets blad kan bära `"labels": "/sökväg/t5.json"`):

```bash
# 1. Utan T5 – lagerregeln av; får inte bli sämre än main
python engine/tools/corpus.py run manifest.json /tmp/korpus_utan_t5 --jobs 4
python engine/tools/corpus.py gate /tmp/korpus_utan_t5/corpus.json engine/tests/data/corpus_baseline.json

# 2. Med T5 – bara bladen som har "labels" i manifestet, lagerregeln på
python engine/tools/corpus.py run manifest.json /tmp/korpus_med_t5 --jobs 4 --labels
python engine/tools/corpus.py gate /tmp/korpus_med_t5/corpus.json engine/tests/data/corpus_baseline.json --only-read
```

### Mängdlista (Bilaga A, med T5)

`eval/tools/quantity_list.py` (via `app/drawings/quantities.py`): en rad per system × material × dimension;
suffix som underrader; okänt suffix flaggat med avvikelsen. Material som saknas fylls i ur systemets enda
material i projektet (TB:s PNU-rader + ritningens etiketter), konfidens 0,85; flera material → tomt och
`MATERIAL_UNRESOLVED`. TB ger: L9 → S13 (`PNU.215 … L9-S13 Tryckluft`); KV01 → K1, K5, E9; S01/S02 → P2, P3.

| Beteckning | Material | Meter | Tvetydigt | Flaggor |
| --- | --- | --- | --- | --- |
| KV01-K1-15 | K1 | 16,16 | 6,64 | UNKNOWN_LABEL_TOKEN W, W40 (A3-13) |
| &nbsp;&nbsp;(utan suffix) | | 0,15 | 6,63 | |
| &nbsp;&nbsp;-W | | 12,36 | 0 | A3-13 |
| &nbsp;&nbsp;-W40 | | 3,64 | 0,02 | A3-13 |
| KV01-K1-28 | K1 | 1,20 | 0 | |
| KV01-K5-15 | K5 | 2,35 | 0 | |
| L9-S13-22 | S13 (TB + etikett, 0,85) | 11,03 | 0 | MATERIAL_FROM_SYSTEM |
| L9-S13-28 | S13 (TB + etikett, 0,85) | 3,57 | 0 | MATERIAL_FROM_SYSTEM |
| L9-S13 | S13 (TB, 0,85) | 0,29 | 0,02 | MATERIAL_FROM_SYSTEM |
| S01-P2-110 | P2 | 13,71 | 3,09 | |
| S01-P2-75 | P2 | 0,52 | 0,83 | |
| S02-P2-110 | P2 | 14,85 | 0 | |
| S02-P2-75 | P2 | 0,65 | 0 | |
| S03-P2-110 | P2 | 12,16 | 0 | |
| VV01-K1-15 | K1 | 5,56 | 0 | UNKNOWN_LABEL_TOKEN F (A3-13) |
| &nbsp;&nbsp;-F | | 5,56 | 0 | A3-13 |
| VV01-K5-15 | K5 | 0,51 | 0 | |

Summa per system: KV01 19,70, L9 14,88, S01 14,23, S02 15,50, S03 12,16, VV01 6,07; totalt 82,55 m.

### S01 DN75 på plan 0 (3,75 → 0,52 m)

Ingen geometri har tappats; två DN75-sträckor har bytt status:

| Sträcka | Före | Efter | Orsak |
| --- | --- | --- | --- |
| 2,25 m, etiketten `S01-P2` / `75` vid (783, 491) | S01-P2 DN75, bekräftad | tvetydig (`AMBIGUOUS_FLOW_BEYOND_THE_LABELLED_RUNS`, kandidat S01-P2-(L) DN110) | T5-filen har på samma ställe både `S01-P2` (0,98) och OCR:s felläsning `501-P2` (0,75). Blocket får en extra rad och etiketten inget ankare. En-läsning-per-ställe tar bara bort fragment vars text ingår i den andra. |
| 1,05 m, etiketten `S01-P` / `75` vid (809, 691) | `S01-75-P` DN75 (skräpläsning – men riktigt DN75-rör) | bekräftad som **S01-P2 DN110** (`junction_dn_over_symbol_labels`) | Etiketten läses nu rätt (`S01-P2` / `75`), men röret slås ihop med DN110-ledningen. Troligen fel dimension. |
| 0,52 m, `S01-P2` / `7` → `75` | DN7 (felläst) | S01-P2 DN75 | rätt |

Två riktiga rör påverkas alltså: 2,25 m är inte längre bekräftade (tvetydiga) och 1,05 m har sannolikt fel
dimension. Inget rättat.

### Otilldelat per blad (ingen rättning gjord)

`eval/tools/unassigned_map.py` ritar varje blad med otilldelat (rött, numrerat), tvetydigt (orange) och
bekräftat (grönt), och rörbeteckningar som inte fäste (blå ruta); bilder och markerad PDF ligger utanför repot.

**Plan 1 (W-50-1-1000): 4,83 m otilldelat (11,4 %), 6,66 m tvetydigt**

| Grupp | Meter | Sträckor |
| --- | --- | --- |
| A – fortsättning på namngivet rör som ingen etikett når | 3,84 | #1 L9 1,99 m lodrätt längs väggen i verkstaden mellan `L9-S13-28` och knopplisten; #2 L9 0,91 m i kompressorrummet; #4/#6/#7 KV 0,49 + 0,23 + 0,22 m vid kompressorrummet och WC |
| C – närliggande etikett har ledare som inte når något rör | 0,95 | #3 VV 0,69 m och #5 KV 0,26 m i WC: fem etiketters ledare (`S01-P3`, `VV01-K1-15-F`, `KV01-K1-15-W` ×2, `L9-Z8`) slutar i samma punkt (533, 695) där inget rör finns |
| D – ingen rörbeteckning i närheten | 0,04 | #8 T1-stump |

Också på plan 1:
- Tvetydigt 6,63 m KV01-K1 DN15 (orange, överst i tvätthallen): röret fortsätter förbi de märkta sträckorna.
  `KV01-K1-28-W40` (ingen ledare) och `KV01-K1-15` / `CL+1400` (ledaren når inget rör) står vid den.
- `L9-28` läses rätt av T5 och motorn, men motorns grammatik byter tvillingtecken (2 → Z) för att passa bladets
  mönster `A9-A9` och gör det till `L9-Z8`, som saknar dimension. Grammatikens omläsning gäller också T5:s säkra
  läsningar.

**Plan 0 (W-53-1-0900): 9,27 m otilldelat (19,3 %), 3,92 m tvetydigt**

| Grupp | Meter | Sträckor |
| --- | --- | --- |
| B – närliggande etikett saknar ledare | 8,83 | #1 hela den streckade ledningen `KV01-E13-40` (PEM i mark). Etiketten `KV01-E13-40` står på ledningen utan ledare, och `KV01-E13` / `40` vid ledningens början fick inget ankare – KV01 har inget ankare alls på bladet |
| A – fortsättning på namngivet rör | 0,44 | #2/#3 S03 och S01 0,22 m vardera förbi `ENTR. GRÄNS` (entreprenadgränsen) – sannolikt riktigt att de inte räknas |

Också på plan 0: tvetydigt 3,92 m S01 (orange, kompressorrummet och WC) – se S01 DN75 ovan.

**Grupperade orsaker (båda bladen):**

1. Etikett på ledningen utan ledare (plan 0 #1, 8,83 m) – den största posten.
2. Fortsättning förbi de märkta sträckorna som ingen etikett når (plan 1 grupp A 3,84 m, och det tvetydiga
   6,63 m KV01 + 2,25 m S01).
3. Ledare som slutar där inget rör finns (plan 1 grupp C 0,95 m; fem etiketter mot samma punkt i WC).
4. Två läsningar av samma text på samma ställe ger en extra rad och inget ankare (`S01-P2` / `501-P2`, 2,25 m).
5. Grammatikens tvillingomläsning skriver om T5:s säkra läsning (`L9-28` → `L9-Z8`).
6. Förbi entreprenadgränsen (0,44 m) – troligen rätt som det är.

## 5. Vad som behövs härnäst (inget byggt)



1. Kör korpusgrinden (`tools/corpus.py`) på `claude/t5-labels` med och utan `--labels` innan något slås ihop –
   regeln om systemlager ändrar vilka lager som räknas som rör på alla ritningar.
2. Konsultens svar om `W40`, `W` och `F` (A3-13).
3. Linjen mellan `L9` och `ANSL. TRYCKLUFT` på plan 1: vems ledare den är går inte att avgöra ur geometrin.

## 6. Omgång 4 (2026-11-03): sju rättningar i ordning

Varje rättning är en generell regel med syntetiska tester (inga Årjängsspecifika villkor). Hela motorsviten kördes
efter varje steg och var grön varje gång. `make check` i dahlny var grön vid varje dahlny-commit. Inga nya AI-anrop:
alla mätningar använder samma T5-fil som omgång 3 (0 USD av taket på 30 USD).

| Efter steg | Motorsviten | Plan 1: otilldelat / tvetydigt / bekräftat | Plan 0: otilldelat / tvetydigt / bekräftat | Summa bekräftat |
| --- | --- | --- | --- | --- |
| Utgångsläge | 1427 | 4,83 (11,5 %) / 6,66 / 40,65 | 9,26 (19,3 %) / 3,92 / 41,90 | 82,55 |
| 1 Extern etikett skrivs aldrig om | 1427 | 4,83 / 6,66 / 41,15 | 9,26 / 3,92 / 41,90 | 83,05 |
| 2 En läsning per plats (dahlny) | 1427 | 4,83 / 6,63 / 41,19 | 9,26 / 1,67 / 44,52 | 85,72 |
| 3 Etikett utan ledare | 1434 | 4,83 / 6,63 / 41,19 | 3,14 (6,6 %) / 1,67 / 52,08 | 93,27 |
| 4 Spridning till stopp, grenar ärver | 1441 | 4,83 (11,5 %) / 0,00 / 50,78 | 3,14 (6,6 %) / 0,79 / 52,08 (+0,96 granska) | 102,86 |
| 5 Utredning, ingen ändring | – | oförändrat | oförändrat | 102,86 |
| 6 Fångad ledarände, möten utan rör | 1450 | 4,83 / 0,00 / 50,78 | 3,14 / 0,79 / 52,08 | 102,86 |
| 7 Utanför entreprenadgräns | 1459 | 4,83 (11,5 %) / 0,00 / 50,78 | 2,47 (5,2 %) / 0,79 / 51,06 (+0,96 granska) + 1,68 utanför | 101,85 |

Meter i bekräftat är mängdens (`confirmed_total_m` − granska); de räknar överbryggade streckpauser och kan därför
vara större än den ritade linjelängden. A.4 är fortsatt 88/88 (mätt efter steg 4; steg 6–7 rör inte etiketterna).

**1.** En extern etikett med `read_confidence` ≥ `labels.min_read_confidence` (skickas som `_meta` i T5-filen)
skyddas: bladets mönster får inte byta tvillingtecken i den. Ville grammatiken läsa annat flaggas det
(`external_label_against_grammar`, med `grammar_would_read`). `L9-28` behåller DN28 (+0,50 m).

**2.** `one_label_per_place`: två läsningar med IoU > `tiles.dedupe_iou` levereras aldrig båda. Ordning: bekräftad av
T5/T5R-modell > tolkningsbar enligt grammatiken > OCR. `S01-P2` / `501-P2` ger en rad, och S01 DN75 fäster igen.

**3.** Etikett utan ledare → närmaste parallella rör inom `assign.proximity_max_mm_paper` (6 mm), konfidens 0,8; ett
andra rör inom 1,5 × avståndet gör den tvetydig. Streckade ledningar räknas som en sträcka. `KV01-E13-40` i mark
mäts (+7,55 m). Konfidensen följer med till mängdraden (`anchor_confidence` → `PipeRunDraft.confidence`).

**4.** Identiteten följer röret genom raka fortsättningar och böjar till ny etikett, symbol, dimensionsbyte eller
entreprenadgräns, utan längdbudget. En gren utan egen etikett ärver system och material; dimensionen är osäker
(granskningsnivå, 0,6) – utom där bladets egen kopplingsledningsregel säger annat. Nät (≥ 2 cykler) ärver inte.

**5. S01 DN75 (1,05 m) slogs ihop med DN110 – orsak, inte rättad.** Sträckan är en blindgren från DN110-noden vid
(769, 744) upp till en symbol vid (750, 688). Etiketten `S01-P2` / `75` vid (809, 691) fäster via symbolen (svagt:
ledaren pekar på symbolen, inte på röret). Motorns regel `junction_dn_over_symbol_labels` ger då grenen den grövre
dimensionen: ingen dimensionsbytesmarkering är ritad, och grenen bär bara symbolfästa etiketter. Före steg 2 lästes
etiketten `S01-P` (annan bas), så regeln slog inte till och grenen blev DN75. **Fråga:** är det en DN75-anslutning
till stammen, eller DN110 ända fram? Ingen reduktion är ritad.

**6.** En ledare som stannar strax före röret fångas av det närmaste röret inom 2 × `assign.leader_end_tolerance_mm_paper`
(2 mm, skickas till motorn i pt), konfidens 0,7. Ligger ett annat rör inom 1,5 × avståndet fångas inget. Etiketter vars
ledare slutar i samma punkt utan rör rapporteras (`leaders_meet_without_pipe`, minst 3). På Årjäng ändras inga
meter: de två närmaste missarna (`S01-P3` vid (701,8; 621,1) och `S03-P2` vid (701,8; 635,3)) ligger 2,79 mm från
röret, utanför 2 mm. **Punkten i WC är en ledare, inte fem:** ett staplat block med fem rader (`VV01-K1-15-F`,
`KV01-K1-15-W` ×2, `S01-P3`, `L9-28`) har en gemensam ledare som slutar vid **(532,8; 695,26)** på plan 1, 58 mm från
närmaste rör. Den rapporteras med punkten.

**7.** En not `ENTR. GRÄNS` (även `ENTREPRENADGRÄNS`, `Gräns för entreprenad`) med ledare till ett rör kapar röret i
punkten. Sidan utan egen etikett blir `OUTSIDE_CONTRACT`: varken bekräftad eller otilldelad, även den kapade bitens
yttre del. Längden redovisas som "utanför entreprenadgräns" i `quantities.json`, i dahlnys
`SheetTakeoff.outside_contract`, i mängdlistan (eget avsnitt, ingår inte i summan) och lila med ett kryss i gränspunkten
i den markerade PDF:en. Andelen otilldelat räknas innanför gränsen. Etiketter på båda sidor, på ingen sida eller en
ledare som inte når något rör ger `contract_boundary_undecided`. Plan 0: tre av fyra gränser kapar.

| Utanför entreprenadgräns (plan 0) | Meter |
| --- | --- |
| KV01-E13-40 | 0,94 |
| S01-P2-110 | 0,37 |
| S03-P2-110L | 0,37 |
| Summa | 1,68 |

Den fjärde noten (vid (1394, 813)) pekar på en streckad linje i lagret `V-53-FE-_-`, som motorn inte läser som rör på
plan 0. Lagret har ingen systemkod, så lagerregeln gäller inte. Den gränsen rapporteras som "når inget rör".

### Fynd som inte rättats

- **Plan 0, lagret `V-53-FE-_-` (ca 5,5 m, penna 1,44):** läses inte som rör alls och syns därför varken som
  bekräftat eller otilldelat. Etiketten `S02-P2-110` / `VG+-857` pekar på det. Behöver utredas innan andelen
  otilldelat på plan 0 (5,2 %) kan tas som slutlig.
- **Pilspetsar ritade i rörpennan räknas som rörlängd** (ca 0,2 m per pil på plan 0). Det gällde redan före
  omgången; nu syns det i "utanför"-raderna.
- **Plan 1 otilldelat 4,83 m** är oförändrat: grupp A 3,84 m (fortsättning som ingen etikett når), grupp C 0,95 m
  (ledare utan rör, punkten ovan).

### Korpusgrinden

Steg 3, 4, 6 och 7 är generella regler som gäller också utan T5. Utan T5 får korpusen inte bli sämre än main. Varje
regel kan slås av vid jämförelse (steg 3 med avstånd 0: då fäster bara ett parallellt rör som går genom texten):

```bash
vvs-takeoff analyze RITNING.pdf --out UT --rule semantics.proximity.LEADERLESS_MM=0
vvs-takeoff analyze RITNING.pdf --out UT --rule pipes.ownership.PROPAGATE_TO_STOPS=false
vvs-takeoff analyze RITNING.pdf --out UT --rule semantics.attachment.NEAR_MISS_NEAREST=false
vvs-takeoff analyze RITNING.pdf --out UT --rule pipes.ownership.CONTRACT_BOUNDARIES=false
```

