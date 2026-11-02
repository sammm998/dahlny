# vvs_engine på Bilaga A – mätning mot facit (2026-11-02)

Underlag: `12_4_Ritningar_VS.pdf` (sha256 `364d8d17…`), facit `eval/projects/arjang_tvatthall/expected/`
(labels.json = A.4, symbols.json = A.5). Motor: `sammm998/Dahlvvvs` @ `7f8248a`, installerad utan
`review`-extran (ingen OCR-assist eller OCR-korskontroll). Kört med
`vvs-takeoff analyze 12_4_Ritningar_VS.pdf`, och all läst text dumpad via `vvs_engine.text.vector_text_rows`.
Mätskripten ligger i `eval/tools/` (`vvs_engine_text_rows.py`, `compare_labels.py`) och blir `make eval`-steg i fas 6.
Adapterns integrationstest (`tests/test_drawings_vvs_engine.py`, kräver `VVS_ENGINE_CMD`) visar att VS-Kalkyls
skalkontroll blockerar planerna.

## Sammanfattning

| Område | Resultat | Krav (SPEC 11.2) |
| --- | --- | --- |
| Etiketter tecken-exakt | **29 / 88 (33 %)**; 41 / 88 (47 %) om O/0, Z/2, S/5, B/8, I/1 räknas som rätt | ≥ 98 %, resten flaggat |
| Skala på planerna | **Fel: 1:100 vald, ska vara 1:50** – alla meter på W-50-1-1000 och W-53-1-0900 är 2× för stora, men står som `VERIFIED` | två metoder inom 1 % eller blockerat |
| Otilldelad rörlängd | Plan 1: 76 %, plan 0: 27 % (+17 % tvetydigt) | ≤ 2 % per sida |
| Flödesschema | Känns inte igen som schema (skala `VERIFIED`, omdöme `INVALID`), komponenter räknas inte | – |
| Legend RÖRBETECKNINGAR | 26 av koderna lästa (+1 skräprad), beskrivningar med `?` för `,` | läses in |
| FÖRKLARINGAR, MATRIS FÖR ISOLERING | Läses inte (`connection_pipes: []`) | läses in |
| Symbolantal (A.5) | Ingen symbolräkning per typ. Taggar räknade ur texten: golvbrunnar rätt, ventiler rätt bara med teckenförväxling | 100 % eller flaggat |
| Titelblock (fas 1) | Ritningsnummer läses inte på planerna; uppdragsnummer bara fragment (`70`, `Z?`, `?010`). Schemat: `70250105`, `1:50 (A1)` rent | – |

Slutsats: motorn är en bra grund för geometri, ledarlinjer och mätning, men på Bengt Dahlgrens stil når
textläsningen och skalvalet inte gränserna. Det mesta av gapet ligger i **etikettläsningen** (glyfer som inte
känns igen) och i **skalvalet**, inte i rörgrafen.

## 1. Etiketter (A.4)

| Ritning | Facit | Exakt | Teckenförväxling | Saknas |
| --- | --- | --- | --- | --- |
| W-50-1-1000 Plan 1 | 42 | 15 | 4 | 23 |
| W-53-1-0900 Plan 0 | 28 | 8 | 0 | 20 (varav `1:100` bara som titelblockets `1:100 (A3)`) |
| W-50-8-1000 Flödesschema | 18 | 6 | 8 | 4 |
| **Summa** | **88** | **29** | **12** | **47** |

Felmönster:

- **Teckenförväxlingar** som systemet inte får rätta i efterhand (SPEC 1.4): `AV2O1-15`, `L9-Z8`, `RA1O1`,
  `VVBOO1`, `KVO1-15`, `AV2S`, `AV1S`, `SIL1O1-25`, `6O°C`, `S01-PZ-110`, `S0Z-PZ-110`.
- **Avkortade rader** – tecken efter en viss position tappas: `VG+` (alla 12 `VG+-…` saknar siffrorna), `CL+2`,
  `CL I`, `S02-P2-7` (ska vara `S02-P2-75`), `S01-P2-7`, `AV2O1-2?`.
- **Hela etiketter saknas**, bland annat alla `KV01-K1-…-W40`, `KV01-K5`, `VV01-K5`, `L9-S13-28/22`,
  `KV01-E13-40`. Suffixet `W40` läses som en egen rad – se `UNKNOWN_LABEL_TOKEN` i SPEC 6.5.
- **Fritext läses inte**: `ANSL. HÖGTRYCK/SPOLSLANG/TRYCKLUFT` (bara `ANSL.`), `ENTR. GRÄNS`,
  `IHOPKOPPLING LUFTNING`, `Monteras i golvränna`, `VATTENUTKASTARE`, `HÖGTRYCKSTVÄTT`, `VVB 55 LITER`.
  `ENTR. GRÄNS` stoppar propageringen och `Monteras i golvränna` är underlaget för avvikelse A3-1.

## 2. Skala

Titelblocket säger `1:50 (A1)` och `1:100 (A3)`. PDF-sidorna är **2384 × 1684 pt = A1**, alltså gäller 1:50.
SPEC A säger "plottad som A4", men det stämmer inte för den här filen; bara förteckningen är A4.

Motorn läste A1-raden trasigt (`1 0 (A1)`) och valde den rena raden `1:100 (A3)`: 0,03528 m/pt. Den
"bekräftades" av en omärkt skalstock som motorn själv tolkade som 23 m över 655,2 pt.

Oberoende kontroll med dörrbågar i A-underlaget (kvartscirklar, plan 1): radierna 45, 50 och 61 pt ger
0,79 / 0,88 / 1,08 m vid 1:50 (vanliga dörrblad) men 1,59 / 1,76 / 2,15 m vid 1:100. **Rätt skala är 1:50.**
Alla motorns meter på planerna ska alltså halveras, och felet syntes inte utåt.

## 3. Mängder (motorns egna siffror, i motorns felaktiga skala)

| Blad | Ritad | Bekräftad | Tvetydig | Otilldelad | Rader |
| --- | --- | --- | --- | --- | --- |
| Plan 1 | 81,42 m | 19,69 m | 0 | 61,73 m (76 %) | bara L9: `L9-28`, `L9-S1`, `LJ-S13-28` (felläst `L9-S13-28`). Inget KV/VV mätt |
| Plan 0 | 105,91 m | 59,34 m | 17,93 m | 28,63 m (27 %) | S01/S02/S03, flera med fel DN eller material (`-7` för 75, `PZ` för P2) |
| Schema | 46,51 m | 0 | 0 | 46,51 m | schemat borde inte mätas alls |

## 4. Symboler (A.5)

Motorn räknar inte VVS-symboler per typ (golvbrunnar, ventiler, återströmningsskydd). Den har stamräkning
(`riser_count`) och en blockigenkänning för A-planer (`abt/symbols.py`). Räknar man taggarna i den lästa texten
blir det så här:

| Tagg | Facit | Exakt i texten | Med teckenförväxling |
| --- | --- | --- | --- |
| B101P / B201B / B202B | 2 / 1 / 1 | 2 / 1 / 1 | 2 / 1 / 1 |
| RA101 (plan; TB säger 2, A3-6) | – | 0 | 1 |
| AV20 (4 uttag + avtappning) | 5 | 0 | 5 |
| AV25 (kompressor + tappvatten) | 2 | 0 | 2 |
| AV15 (facit ändrat till 4 2026-11-02) | 4 | 0 | 4 |
| BV15 / BV25 | 1 / 1 | 1 / 1 | 1 / 1 |
| SIL101 | 1 | 0 | 1 |
| ASS (BA), mätargrenar | 1, 2 | 0 | 0 |

## 5. Vad motorn saknar mot SPEC 6.4

| SPEC | Krav | I vvs_engine |
| --- | --- | --- |
| 6.4.1 Väg A | IFC (`ifcopenshell`, IfcPipeSegment, system, dimension) | **Saknas** |
| 6.4.2 Väg B | DWG/DXF (`ezdxf`, lager, block, text som text) | **Saknas** – bara vektor-PDF |
| 6.4.3 c | Två oberoende läsningar (vision + OCR), omläsning i 600 dpi vid oenighet, `read_confidence` | Delvis: egen glyfigenkänning; OCR bara som kontroll/ifyllnad av `?` (extra); ingen vision-läsning av etiketter; förväxlingar (O/0) flaggas inte |
| 6.4.3 d | Okänd token (`W40`) behålls och flaggas | Suffixet läses som separat rad; ingen `unknown_token`-status |
| 6.4.3 f | Två skalmetoder inom 1 % annars blockerat | Har text + skalstock, men valde fel ratio här och kallade det VERIFIED; ingen kontroll mot sidans pappersstorlek när A1-raden är oläslig |
| 6.4.3 h.3 | Propagering stoppas av `ENTR. GRÄNS`; kopplingsledningar från FÖRKLARINGAR (konf. 0,85) | FÖRKLARINGAR läses inte; `ENTR. GRÄNS` läses inte |
| 6.4.3 i | Symboler mot legend (golvbrunnar, ventiler, ASS …), länk till SpecItem | **Saknas** för VVS-symboler; finns för A-planens block |
| 6.4.3 j | Lodräta längder ur CL/VG, "ej bestämd" i stället för 0 | Delvis: VG/CL-par på ett rör; stamräkning; våningshöjd manuellt. Här läses CL/VG-siffrorna inte |
| 6.4.3 k | Flödesschema-avstämning (komponenter per system mot plan och TB) | **Saknas** – schemat känns inte ens igen som schema här |
| 6.4.3 l | Rördelar (böjar/T/reduktioner) som uppskattning; isolering ur TB-regler × PipeRuns | **Saknas** (isoleringsmatrisen läses inte) |
| 6.4.4 Väg D | Skannad PDF/bild: förbehandling, rastervektorisering, max konfidens 0,85 | Finns (`raster/`, 150–300 dpi, allt till granskning) – ej mätt här |
| 6.4.4 Väg E | Foto: perspektivkorrigering (homografi), max konfidens 0,75 | **Saknas** (ingen perspektivkorrigering) |
| 6.4.4.4 | Skala för skanning/foto bara via skalstock/kända mått, minst två | Delvis: OCR-skaltext räcker inte ensam, kräver bekräftelse |
| 6.4.4.5 | Halvmanuell spårning (klick → följ till förgrening) | I Dahlvvvs-UI:t (fliken Markera), inte som motor-API |
| 6.4.5 | Projektets legend: RÖRBETECKNINGAR, FÖRKLARINGAR, MATRIS FÖR ISOLERING; jämför mellan blad | RÖRBETECKNINGAR ja; övriga nej |
| 6.4.6 | Markerad PDF med annotationer + summering först | Finns (`production-overlay.pdf` m.fl., färg per beteckning); summeringssida och moln för avvikelser ej verifierade |
| 7.2/7.5 | AI bakom `AIClient`, bakeoff | Motorn har egen OpenAI-"second reader" (`gpt-6-astra`) och vision-endpoint – i VS-Kalkyl ska AI gå via `app/ai/` |

## 6. Rekommenderad ordning för att täppa gapen

1. **Skala** (kritiskt, tyst fel): kräv att den valda ratio-raden matchar sidans pappersstorlek; oläslig rad →
   `SCALE_DISAGREEMENT`, aldrig byte till en annan rad. Lägg dörrbredd eller rutnät som tredje metod.
2. **Etikettläsning**: vision (T5) + OCR som oberoende läsningar enligt 6.4.3 c, med motorns glyfläsning som
   tredje röst. Förväxlingar (O/0 …) flaggas och rättas inte i tysthet.
3. **Legendtabeller** FÖRKLARINGAR och MATRIS FÖR ISOLERING, och fritext som `ENTR. GRÄNS`.
4. **Symboler** per typ mot legenden, och **flödesschema** (känna igen schema, räkna komponenter).
5. DXF/IFC (väg A/B) och foto (väg E) – i SPEC:s fasordning.
