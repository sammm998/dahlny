# VS-Kalkyl – Systemspecifikation för automatiserad offertberedning (VVS)

> **Till Claude Code:** Detta dokument är den kompletta specifikationen. Läs hela innan du skriver kod.
> Bygg i den fasordning som anges i kapitel 13. Varje fas har en *Definition of Done* som ska vara uppfylld
> (inklusive tester) innan nästa fas påbörjas. Punkter markerade **[ÖPPEN FRÅGA]** får inte gissas –
> bygg ett adapter-gränssnitt och en stub, och fråga användaren. Lägg denna fil i repots rot som `SPEC.md`
> och skapa en kortare `CLAUDE.md` som pekar hit och sammanfattar kodkonventionerna i kapitel 12.

---

## 0. Innehåll

1. Bakgrund, mål och avgränsning
2. Designprinciper (gäller allt)
3. Arkitekturöversikt
4. Teknikstack
5. Datamodell
6. Pipeline i detalj
   - 6.1 Intag och dokumentklassning
   - 6.2 Extraktion ur teknisk beskrivning (TB)
   - 6.3 Artikelregister och matchning
   - 6.4 Ritningsanalys och mängdning
   - 6.5 Avstämnings- och avvikelsemotor
   - 6.6 Leverantörsförfrågningar
   - 6.7 Export till Prixel
7. AI-modeller: vilken modell gör vad, och hur
8. Robusthet över konsulter och ritningsstilar
9. Granskningsgränssnitt
10. Säkerhet, sekretess och drift
11. Utvärdering och tester
12. Repo-struktur och kodkonventioner
13. Faser och milstolpar
14. Öppna frågor
15. Bilaga A – Testfall: Tvätthall Årjäng (facit)
16. Bilaga B – Referenstabeller (AMA-koder, materialkoder, beteckningsgrammatik)
17. Bilaga C – Filer och länkar som följer med

---

## 1. Bakgrund, mål och avgränsning

### 1.1 Nuläge

Kalkylatorer på Dahl tar emot förfrågningsunderlag för VS-entreprenader: teknisk beskrivning (TB, PDF enligt AMA VVS & Kyla),
ritningsförteckning och ritningar (planer, flödesscheman). Idag:

1. Kalkylatorn läser TB manuellt och plockar ut sakvaror.
2. Lagervaror (med RSK-nummer) knappas in manuellt i offertsystemet **Prixel**.
3. Varor som inte finns i lager eller virtuellt lager kräver prisförfrågan: teknisk data kopieras ur TB till ett mail till leverantör (t.ex. Furhoffs).
4. Ritningar hanteras inte – rör, isolering, ventiler som anges "Enl ritn" mängdas inte systematiskt.

### 1.2 Mål

Ett internt system som, för varje förfrågan:

1. Läser in TB och ritningar oavsett konsult och ritningsstil.
2. Producerar en **strukturerad artikellista** (beteckning, AMA-kod, produkt, fabrikat, art.nr/RSK, antal, tekniska krav) med spårbarhet till källan (sida + koordinater).
3. Matchar varje rad mot Dahls artikelregister → *lagervara*, *virtuellt lager*, *prisförfrågan* eller *osäker*.
4. Mängdar rörledningar per **system × material × dimension** (meter), samt räknar symboler (brunnar, ventiler, uttag, sanitet) ur ritningar – från vektor-PDF, skannade PDF:er, bildfiler och fotograferade ritningar, samt DWG/DXF/IFC – och exporterar en **markerad PDF** där varje mängdat rör och varje läst beteckning syns.
5. Stämmer av TB mot ritningar och listar **avvikelser** (saknade poster, motsägelser, antal som inte stämmer).
6. Genererar **mailutkast** per leverantör för prisförfrågan.
7. Exporterar lagerrader till Prixel.
8. Låter kalkylatorn granska och godkänna allt i ett gränssnitt där varje siffra kan klickas fram till sin källa.

### 1.3 Icke-mål (version 1)

- Systemet skickar **aldrig** mail eller skriver till Prixel utan att en människa godkänt.
- Systemet sätter inte priser eller marginaler – det levererar underlag.
- Ingen prissättning av arbete/montagetid i v1 (kan läggas till senare som modul).
- Ingen automatisk tolkning av A-, K- eller E-ritningar utöver vad som behövs för VS-mängdning.

### 1.4 Om "helt korrekt"

Inget system kan garantera korrekthet på godtyckliga ritningar – handlingar innehåller själva fel (se Bilaga A, avvikelser).
Kravet tolkas därför så här, och systemet ska byggas för att uppfylla det:

- **Ingen tyst gissning.** Varje värde har en källa, en metod och en konfidens. Under tröskel → markeras för granskning, aldrig "bästa gissning" utan flagga.
- **Två oberoende vägar** för allt som går (t.ex. antal brunnar ur TB *och* ur ritning; skala ur titelblock *och* skalstock). Oenighet → avvikelse.
- **Fullständighetskontroll.** Varje rörsegment på en ritning ska antingen vara tilldelat en beteckning eller listas som "otilldelat". Summan av tilldelat + otilldelat = 100 % av ritad längd.
- **Mätbar träffsäkerhet** mot facit (kapitel 11) innan systemet används skarpt för en ny konsult-/ritningsstil.

---

## 2. Designprinciper (gäller all kod)

1. **Deterministiskt först, AI där tolkning krävs.** Geometri, längder, skala, summeringar och regelkontroller görs i vanlig kod. AI används för att läsa text som inte finns som text, tolka fritext, klassificera, matcha osäkert och skriva mail.
2. **AI returnerar alltid strukturerad data** enligt JSON-schema, valideras med Pydantic. Ogiltigt svar → ett nytt försök med felmeddelandet, sedan flagga.
3. **Spårbarhet.** Varje rad i varje utdata bär `source_refs: [{document_id, page, bbox, method, model, confidence}]`.
4. **Idempotens och reproducerbarhet.** Varje körning sparar modell-ID, promptversion, indata-hash. Samma indata + samma version → samma resultat (temperature 0 där API:t tillåter, cachning av AI-svar per hash).
5. **Människan i loopen.** Inget lämnar systemet (mail, Prixel) utan godkännande. Korrigeringar sparas och används för att förbättra stilprofiler (kapitel 8).
6. **Konfiguration före kod.** Beteckningsgrammatik, materialkoder, systemkoder, tröskelvärden och modellval ligger i config/databas – inte hårdkodat. Ritningens egen legend (rörbeteckningstabell) har företräde framför standardtabellen.
7. **Fail loud.** Hellre "kunde inte avgöra skala på sida 3" än ett felaktigt metertal.

---

## 3. Arkitekturöversikt

```
                 ┌──────────────────────────────────────────────────────────────┐
  Uppladdning ──►│ 1. INTAG                                                     │
  (PDF/DWG/DXF/  │  filtyp, sidor, rendering, textlager, vektorer, hash         │
   IFC/ZIP)      └───────────────┬──────────────────────────────────────────────┘
                                 ▼
                 ┌──────────────────────────────────────────────────────────────┐
                 │ 2. DOKUMENT-/SIDKLASSNING                                    │
                 │  TB · ritningsförteckning · plan · flödesschema · sektion ·  │
                 │  detalj · övrigt   (+ titelblock: ritn.nr, skala, plan)      │
                 └───────┬───────────────────────────────────────┬──────────────┘
                         ▼                                       ▼
  ┌──────────────────────────────────┐   ┌───────────────────────────────────────────┐
  │ 3. TB-EXTRAKTION                 │   │ 4. RITNINGSANALYS                         │
  │  AMA-struktur → SpecItems        │   │  4a legend/rörbeteckningar (per projekt)  │
  │  (beteckning, fabrikat, art/RSK, │   │  4b skalkalibrering (2 metoder)           │
  │   antal, krav, "Enl ritn")       │   │  4c etiketter (text/vision-OCR)           │
  └───────────────┬──────────────────┘   │  4d rörgeometri → graf                    │
                  │                      │  4e etikett→segment, propagering          │
                  │                      │  4f symboler (brunnar, ventiler, …)       │
                  │                      │  4g lodräta längder, schema-avstämning    │
                  │                      │  → PipeRuns, SymbolCounts                 │
                  │                      └───────────────┬───────────────────────────┘
                  ▼                                      ▼
                 ┌──────────────────────────────────────────────────────────────┐
                 │ 5. SAMMANSLAGNING + AVSTÄMNING (regelmotor)                  │
                 │  SpecItems ⨝ ritningsmängder → QuantityLines + Deviations    │
                 └───────────────┬──────────────────────────────────────────────┘
                                 ▼
                 ┌──────────────────────────────────────────────────────────────┐
                 │ 6. ARTIKELMATCHNING mot Dahls register                       │
                 │  exakt (RSK/artnr) → fuzzy (pg_trgm) → AI-rerank → klass     │
                 └──────┬───────────────────┬───────────────────┬───────────────┘
                        ▼                   ▼                   ▼
                  Lager/virtuellt      Prisförfrågan         Osäker
                        │                   │                   │
                        ▼                   ▼                   ▼
                 ┌──────────────────────────────────────────────────────────────┐
                 │ 7. GRANSKNINGS-UI (människa godkänner, korrigerar)           │
                 └──────┬───────────────────┬───────────────────────────────────┘
                        ▼                   ▼
               8. PRIXEL-EXPORT     9. MAILUTKAST per leverantör (Outlook/Gmail)
                                        ↳ svar/pris förs tillbaka till projektet
```

Alla steg körs som asynkrona jobb. Ett projekt kan köras om från valfritt steg (t.ex. efter att användaren korrigerat skalan).

---

## 4. Teknikstack

| Del | Val | Motivering |
| --- | --- | --- |
| Språk backend | Python 3.12 | Bäst ekosystem för PDF, CAD, geometri |
| API | FastAPI + Pydantic v2 | Typade scheman delas med AI-validering |
| Databas | PostgreSQL 16 + `pg_trgm` + PostGIS | Fuzzy artikelsök; PostGIS för geometri (segment, bbox, närhetsfrågor) |
| Jobbkö | Celery + Redis (alt. `arq`) | Långa jobb (rendering, AI-anrop) |
| Filer | S3-kompatibel lagring (MinIO lokalt) | Originalfiler, renderingar, tiles |
| PDF | PyMuPDF (`fitz`) | Textlager, vektorer (`get_drawings`), rendering |
| PDF fallback | pdfplumber, poppler (`pdftoppm`) | Korskontroll |
| DWG→DXF | ODA File Converter (kontrollera licens) alt. LibreDWG | ezdxf läser bara DXF |
| DXF | `ezdxf` | Lager, polylinjer, block, attribut, MTEXT |
| IFC | `ifcopenshell` | Rörsegment med system/dimension direkt i modellen |
| Geometri | `shapely` 2, `networkx`, `numpy`, `scipy` (KD-träd) | Snappning, graf, närhet |
| Bild | OpenCV, Pillow | Tiles, rasterlinjer för skannade ritningar |
| Klassisk OCR (korskontroll) | PaddleOCR eller Tesseract | Oberoende andra läsning av etiketter |
| AI | Anthropic Claude API (SDK `anthropic`) som primär; adaptrar för OpenAI och Google | Se kapitel 7, jämförelse i 7.5 |
| Rasterbehandling | OpenCV-contrib (LSD/FastLineDetector, ximgproc), scikit-image (Sauvola, skeletonize), pillow-heif | Skanningar och foton (6.4.4) |
| PDF-markering | PyMuPDF-annotationer | Markerad PDF (6.4.6) |
| Frontend | React + TypeScript + Vite, pdf.js, Konva eller SVG-overlay | Granskning med klickbar källa |
| Export | `openpyxl` (Excel), CSV | Prixel, leverantörsbilagor |
| Mail | Microsoft Graph (Outlook) alt. Gmail API – **endast utkast** | **[ÖPPEN FRÅGA]** vilket mailsystem |
| Test | pytest, pytest-snapshot, Playwright (UI) | |
| Drift | Docker Compose; senare k8s/Azure | |

---

## 5. Datamodell

Alla tabeller har `id (uuid)`, `created_at`, `updated_at`. Koordinater lagras i **PDF-punkter i sidans koordinatsystem** (origo uppe vänster, som PyMuPDF) plus `page_no`; verkliga mått i **meter** efter skalning.

```
Project(id, name, customer, consultant, project_no, status, created_by)
Document(id, project_id, filename, kind[tb|drawing_list|plan|schematic|section|detail|other],
         format[pdf_vector|pdf_raster|dwg|dxf|ifc], sha256, pages)
Page(id, document_id, page_no, width_pt, height_pt, kind, title_block_json,
     drawing_no, level_name, scale_declared, paper_size_declared,
     scale_effective_m_per_pt, scale_confidence, scale_method)
StyleProfile(id, consultant, label_regex_json, layer_map_json, line_width_map_json,
             legend_overrides_json, examples_json, version)

Legend(id, project_id, page_id, materials_json, systems_json, notes_json)
   -- materials: {"K1": "Koppar, hårda", ...}; systems: {"KV": "Tappkallvatten", ...}

SpecItem(id, project_id, ama_code, ama_title, designation, description,
         manufacturer, model, article_no, rsk, quantity, unit,
         quantity_mode[fixed|per_drawing|range|regulated], quantity_range,
         requirements_text, parent_item_id, source_refs)
   -- parent_item_id: "Härtill"-tillbehör (blandare, ventiler) under sanitetsenhet

Label(id, page_id, raw_text, bbox, rotation, read_method[text_layer|vision|ocr],
      read_confidence, parsed_json, parse_status[ok|unknown_token|failed])
   -- parsed_json: {"system":"KV01","material":"K1","dim":"15","suffixes":["W40"]}

PipeSegment(id, page_id, geom LINESTRING (pt), length_pt, length_m,
            stroke_width, dash_pattern, color, layer,
            assigned_label_id, system, material, dim, assign_method, assign_confidence,
            is_vertical_symbol, z_from_m, z_to_m)
PipeRun(id, project_id, system, material, dim, length_m_horizontal, length_m_vertical,
        length_m_total, segment_ids, confidence)
Symbol(id, page_id, kind[floor_drain|valve|backflow|strainer|cleanout|outlet|fixture|meter|...],
       tag, bbox, read_method, confidence, linked_spec_item_id)

QuantityLine(id, project_id, spec_item_id NULL, source[tb|drawing|merged],
             designation, description, quantity, unit, confidence, status[auto|review|approved])
Deviation(id, project_id, rule_id, severity[info|warning|critical], message, refs, status[open|resolved|ignored], note)

Article(id, dahl_art_no, rsk, supplier, supplier_art_no, name, stock_status[stock|virtual|order],
        unit, discount_group, attributes_json)
ArticleMatch(id, quantity_line_id, article_id NULL, method[rsk|art_no|fuzzy|ai],
             score, outcome[stock|virtual|request|uncertain], approved_by)

SupplierRequest(id, project_id, supplier, line_ids, subject, body_md, status[draft|approved|sent|answered],
                reply_prices_json)
Correction(id, project_id, entity, entity_id, field, old, new, user, created_at)
AIRun(id, project_id, step, model, prompt_version, input_hash, request_json, response_json,
      tokens_in, tokens_out, cost_estimate, latency_ms, status)
```

---

## 6. Pipeline i detalj

### 6.1 Intag och dokumentklassning

1. Packa upp ZIP, beräkna SHA-256, avvisa dubbletter.
2. Bestäm format **per sida** (en PDF kan blanda typer):
   - PDF: har sidan textlager? Har den vektorbanor (`page.get_drawings()` > N)? Är den en ren bild (en stor bild, få vektorer) → `pdf_raster`.
   - **Blandad sida:** vektorer ovanpå en inbäddad rasterbild (t.ex. skannat A-underlag med vektoriserade VS-rör) → `pdf_mixed`: vektorvägen för rören, rastret ignoreras som bakgrund men används för rumsnamn.
   - Bildfiler: JPG, PNG, TIFF (även flersidig), HEIC, BMP → `image`. Skannade PDF:er och fotograferade ritningar behandlas likadant (6.4.4).
   - DWG → konvertera till DXF (ODA/LibreDWG), sedan behandla som DXF.
   - IFC → egen väg (6.4.1).
   - **Kvalitetsmätning för raster:** effektiv upplösning (dpi), skärpa (Laplace-varians), kontrast, lutning, perspektiv. Resultatet styr väg D/E och visas för användaren ("för låg upplösning för att läsa 2,5 mm text – skanna om i minst 300 dpi").
3. Rendera varje sida: översikt 100 dpi (för klassning) och arbetsupplösning 300 dpi (för etikettläsning). Lagra.
4. **Sidklassning** (AI, se kap 7, uppgift T1): `tb | drawing_list | plan | schematic | section | detail | legend_only | other`.
   Indata: översiktsbild + textlagrets första 2000 tecken + titelblockets text.
5. **Titelblock** (AI T2 + regex): ritningsnummer (`W-50-1-1000`), plan/innehåll, skala (`1:50 (A1) 1:100 (A3)`), datum, revision, konsult, uppdragsnummer.
   Regler: ritningsnummer ska finnas i ritningsförteckningen; skillnad → Deviation (info).
6. Ritningsförteckningen parsas och jämförs mot mottagna ritningar: saknad ritning → Deviation (critical).

### 6.2 Extraktion ur teknisk beskrivning (TB)

TB följer AMA-struktur: koder som `PRB.12`, `PNU.311`, `PUC.1`, rubrik, löptext, objektrader med beteckning (`B201B`), mängd (`1 st`, `2st`, `Enl ritn`, `1-2 st`, `R`), specifikationstabeller.

**Steg:**

1. Extrahera text per sida med layout (PyMuPDF `get_text("dict")`) inklusive fetstil och x-position. Kolumnerna KOD / TEXT / MÄNGD / ENHET identifieras via x-position (sidhuvudets kolumnrubriker ger x-gränserna).
2. Ta bort sidhuvud/sidfot (upprepade block på varje sida).
3. **Segmentering (deterministisk):** dela på AMA-kod-rubriker (regex `^[A-Z]{1,4}(\.[0-9]{1,5})?\s` i KOD-kolumnen) och på objektbeteckningar (fetstil i TEXT-kolumnen, regex per stilprofil, default `^[A-Z]{1,4}[0-9]{2,4}[A-Z]?$` plus fria ord i versaler som `TRYCKLUFTSUTTAG`). Mängd tas ur MÄNGD-kolumnen på samma rad.
4. **Strukturering (AI, T3):** varje segment + sin AMA-rubrikkedja skickas till modellen med JSON-schema för `SpecItem`. Modellen ska:
   - dela upp "Härtill:"-listor i barnposter med antal (t.ex. "2 st. avstängningsventiler Broens typ Ballofix" → barnpost, antal 2),
   - extrahera RSK (`RSK\s?\d{7}`), tillverkarens art.nr, fabrikat, typ, dimension (DN, mm, tum),
   - sätta `quantity_mode`: `fixed` (1 st), `per_drawing` ("Enl ritn", "Enl. ritning"), `range` ("1-2 st"), `regulated` ("R"),
   - sammanfatta tekniska krav i `requirements_text` **ordagrant hämtat** ur källan (inga omskrivningar av tekniska värden),
   - aldrig hitta på värden; okänt = `null`.
5. **Validering (deterministisk):** varje RSK och art.nr som modellen returnerar måste finnas ordagrant i källtexten (strängsökning efter normalisering av blanksteg). Annars avvisas fältet → `null` + flagga. Samma kontroll för antal.
6. **Andra läsning (AI, T4, annan modell än T3):** kontrollerar fullständighet: "Lista alla produkter/objekt som nämns i texten men saknas i extraktionen." Resultat → Deviation `TB_MENTIONED_NOT_ITEMIZED` (fångar t.ex. golvrännor som nämns i 53.B men saknar PR-post).
7. Generella krav (t.ex. "Blandare utan föravstängning förses med Ballofix", "O-ringar bytas till Viton") lagras som `ProjectRule` och tillämpas i avstämningen.
8. **Skannad TB (inget textlager):** rendera 300 dpi, räta upp, kör vision-modellen (T3-OCR) sida för sida med instruktion att återge texten ordagrant med kolumnerna KOD/TEXT/MÄNGD/ENHET, och korskör Tesseract (`swe`). Oenighet i siffror, RSK, art.nr eller antal → flagga per fält. Därefter samma steg 3–7. RSK/art.nr-valideringen i steg 5 görs mot OCR-texten, och fält där de två OCR-läsningarna skiljer sig kräver granskning.

### 6.3 Artikelregister och matchning

**Register:** import från affärssystem-export (Excel/CSV) – **[ÖPPEN FRÅGA]** exakt format och uppdateringsfrekvens. Minsta kolumner: Dahl art.nr, RSK, leverantör, leverantörens art.nr, benämning, lagerstatus (lager/virtuellt/beställningsvara), enhet, rabattgrupp. Nattlig synk.
Katalogen på katalog.dahl.se (bläddrings-PDF) används **inte** som datakälla.

**Matchningskedja (stoppa vid första säkra träff):**

1. **RSK exakt** → score 1.0.
2. **Leverantörens art.nr exakt** efter normalisering (ta bort blanksteg, bindestreck jämförs både med och utan) + fabrikat stämmer → 0.98.
3. **Fuzzy** med `pg_trgm` på fabrikat + typ + dimension → top 20 kandidater.
4. **AI-rerank (T6):** modellen får SpecItem + kandidater (med attribut) och returnerar bästa kandidat, score och motivering, eller "ingen passar". Får **bara** välja bland givna kandidater.
5. **Klassning:**
   - score ≥ 0.95 och lagerstatus lager/virtuellt → `stock` / `virtual`
   - ingen kandidat ≥ 0.6, eller beställningsvara → `request` (prisförfrågan)
   - övrigt → `uncertain` (granskas)
6. Tillbehörskrav kontrolleras: om TB kräver t.ex. "rutgaller M125, vattenlås, ställben" och matchad artikel saknar dessa attribut → Deviation `ACCESSORY_NOT_CONFIRMED` och raden går till `request` med frågan i mailet.

### 6.4 Ritningsanalys och mängdning

Detta är den svåraste delen. Den byggs som **fyra ingångsvägar** med sjunkande precision. Systemet väljer automatiskt bästa tillgängliga och redovisar vilken som användes.

| Väg | Indata | Förväntad precision | Kommentar |
| --- | --- | --- | --- |
| A | IFC-modell | Högst | System/dimension finns som egenskaper |
| B | DWG/DXF | Hög | Lager, polylinjer, text som text |
| C | Vektor-PDF (även blandad med rasterunderlag) | God | Rörlinjer som vektorer; text ofta som linjer (SHX) |
| D | Skannad PDF / bildfil (plan skanning) | Medel | Rastervektorisering + vision; granskning krävs för låg konfidens |
| E | Fotograferad ritning (mobil) | Låg–medel | Perspektivkorrigering först; skala endast via skalstock/mått |

Systemet ska i UI:t föreslå att kalkylatorn begär DWG/IFC från konsulten när endast C/D finns.

#### 6.4.1 Väg A – IFC

- `ifcopenshell`: hämta `IfcPipeSegment`, `IfcPipeFitting`, `IfcFlowTerminal`, `IfcValve`, `IfcSanitaryTerminal`, `IfcWasteTerminal`.
- System via `IfcRelAssignsToGroup` → `IfcDistributionSystem`/`IfcSystem` namn. Dimension via egenskapsset (`Pset_PipeSegmentTypeCommon.NominalDiameter`) eller geometrins diameter. Längd via geometri (axel) eller `Qto_PipeSegmentBaseQuantities.Length`.
- Mappa systemnamn och material till projektets legend (AI T7 hjälper med mappning första gången; sparas i stilprofil).

#### 6.4.2 Väg B – DWG/DXF

- Läs alla entiteter i modelspace, inklusive i block (explodera rekursivt med transformering).
- **Lagerkarta:** gruppera lager per namn (t.ex. `VS-KV`, `P-SPILL`, `I-RÖR-L9`). AI T7 föreslår mappning lager → system utifrån lagernamn + exempel på närliggande etiketter; användaren bekräftar en gång per konsult, sparas i `StyleProfile.layer_map_json`.
- Text (`TEXT`, `MTEXT`, `ATTRIB`) läses direkt → Label med `read_method=text_layer`, konfidens 1.0.
- Rörlinjer: `LINE`, `LWPOLYLINE`, `POLYLINE`, `ARC` på rörlager. Enheter: läs `$INSUNITS` och verifiera mot dimensioneringar/rutnät.
- Fortsätt med 6.4.3 g–l (graf, tilldelning, symboler, mängder), men skala är redan 1:1 i modellenheter.

#### 6.4.3 Väg C – Vektor-PDF (vanligast idag)

**a) Vektorer.** `page.get_drawings()` ger banor med `items` (linjer `l`, kurvor `c`, rektanglar `re`), `width`, `dashes`, `color`, `fill`. Normalisera till segment.

**b) Text som linjer.** CAD-plottade PDF:er har ofta text som korta linjer (SHX-typsnitt). Detektera textliknande kluster: många korta segment, hög täthet, liten bbox, regelbunden höjd → *glyfkluster*. Dessa ska:
   - **uteslutas** från rörgeometrin,
   - **läsas** som etiketter (c).

**c) Etikettläsning (två oberoende läsningar).**
   1. Om textlager finns: använd det (konfidens 1.0) – kontrollera ändå att text inte är dubblerad som linjer.
   2. Annars: rendera sidan i 300–400 dpi, dela i **överlappande tiles** (t.ex. 1024×1024 px, 20 % överlapp; textrader får inte klippas – tiles som skär en glyfkluster-bbox utökas). Skicka varje tile till **vision-modellen (T5)** med instruktion att returnera alla textetiketter med bbox i tile-koordinater och rotation. Konvertera till sidkoordinater, slå ihop dubbletter från överlapp (IoU > 0.5 + samma text).
   3. **Oberoende korskontroll** med klassisk OCR (PaddleOCR) på samma tiles. Jämför per etikett: lika → konfidens hög; olika → fråga vision-modellen igen med beskärning kring just den etiketten i högre upplösning (600 dpi) och båda läsningarna som alternativ; fortfarande oenighet → `read_confidence < 0.8` → granskning.
   4. Etiketter kan vara roterade 90°: rendera även roterade varianter av glyfkluster som är höga och smala.

**d) Parsning av etiketter** mot grammatik (Bilaga B) och projektets legend:
   - Rörbeteckning: `{system}{nr?}-{material}-{dim}[-{suffix}…]`, t.ex. `KV01-K1-15-W40`, `S02-P2-110`, `L9-S13-28`, `S01-P2-110L`.
   - Höjd: `CL+2300` (centrumhöjd mm över färdigt golv), `VG+-828` (vattengång).
   - Objekt: `B201B`, `AV201-15`, `BV25`, `SIL101-25`, `RA101`, `VUK`.
   - Okänd token (t.ex. suffix som inte finns i legend) → `parse_status=unknown_token`, behålls och visas i UI. **Aldrig tolka bort.**
   - Material- och systemkoder valideras mot **projektets egen legend** (6.4.5) i första hand, standardtabell i andra hand.

**e) Klassning av vektorer.** Separera rörlinjer från arkitektur (väggar, rutnät, dörrar, möbler), måttlinjer, ledarlinjer och symboler:
   - Statistik per sida över (bredd, streckmönster, färg). Rör ritas oftast tjockare än A-underlaget (som ofta är grått/tunt eller i egen färg).
   - Kandidatgrupper visas för AI T8 som en renderad bild där varje grupp färgas och numreras; modellen anger vilka grupper som är rör, vilka är ledarlinjer, vilka är väggar. Detta görs **en gång per sida**, resultat sparas i stilprofilen som (bredd, mönster, färg) → kategori, och återanvänds för samma konsult.
   - Streckade rör (t.ex. i mark eller dolda) är fortfarande rör – streckmönster är ett attribut, inte uteslutningskriterium.
   - Användaren kan korrigera i UI (klicka grupp → "är rör"/"är inte rör").

**f) Skalkalibrering (minst två metoder, måste stämma inom 1 %):**
   1. **Deklarerad skala + papper:** titelblock säger t.ex. `1:50 (A1)`. Faktisk sida = 595×842 pt (A4). Effektiv skala = 1:50 × (A1-bredd / faktisk bredd). Kontrollera orientering.
   2. **Skalstock:** detektera skalstocken (linjal med siffror 0, 1, 2, 5 och "METER"), mät avståndet 0→5 i punkter → meter per punkt.
   3. **Rutnät/måttsättning (om tillgängligt):** axelavstånd från A-ritning eller måttkedjor.
   4. Oenighet > 1 % → Deviation critical, sidan blockeras för mängdning tills användaren valt skala.
   - Planer som ritats i flera skalor (detaljutsnitt) → separata skalzoner per viewport.

**g) Rörgraf.**
   1. Snappa ändpunkter inom tolerans (default 0,5 mm på papper, konfigurerbart) med KD-träd.
   2. Dela segment vid korsningar **endast** om det finns en förgrening/symbol (korsande rör i olika nivåer ska inte kopplas ihop). Regel: en korsning utan nod-symbol (punkt, T-symbol) = ingen koppling.
   3. Bygg `networkx`-graf: noder = ändpunkter/förgreningar/symboler, kanter = segment med längd.
   4. Slå ihop kollineära följdsegment till en kant (för stabil tilldelning).

**h) Etikett → rör (tilldelning).**
   1. **Ledarlinje först:** etiketter har ofta en tunn linje (ibland med pil eller prick) från understrykning till röret. Följ ledarlinjens fria ände; röret den slutar på/närmast (inom 1 mm) får etiketten. Konfidens 0.95.
   2. **Närhet och parallellitet:** saknas ledare → närmaste rörsegment som är parallellt med etikettens textriktning inom avstånd d (default 6 mm på papper). Konfidens 0.8, sänks om två kandidater ligger inom 1,5× avståndet.
   3. **Propagering:** en etikett gäller längs grafen tills: ny etikett, dimensionsbyte-symbol, ventil-/apparatanslutning, systemgräns ("ENTR. GRÄNS"), sidkant. Vid förgrening där grenen saknar egen etikett: grenen ärver system och material men **dimension markeras osäker** (konfidens 0.6), om inte projektets förklaringstabell anger dimension för kopplingsledning (t.ex. "Dimensioner på kopplings-/anslutningsledningar där ej annat anges": TS 12/12, WC 15, …) – i så fall används den tabellen (konfidens 0.85).
   4. **Konfliktlösning:** om två etiketter propagerar till samma segment med olika värden → segmentet får `assign_confidence=0` och Deviation.
   5. **Fullständighet:** alla rörsegment utan tilldelning listas som "otilldelat" med längd. Andel otilldelad längd > 2 % → sidan kan inte godkännas utan åtgärd.

**i) Symboler.**
   - Hämta symbollegend från ritningen (t.ex. flödesschemats "MATERIAL SPECIFIKATION": avstängningsventil, injusteringsventil, backventil, blandningsventil, säkerhetsventil, återströmningsskydd).
   - Detektion: (1) DXF-block om väg B. (2) Vektor-PDF: små slutna figurer → kandidater; jämför form med legendens symboler (form-deskriptorer, t.ex. Hu-moment på rasteriserad symbol) + vision-modell T5 för bekräftelse. (3) Etikett-taggar (`B201B`, `AV203-20`) räknas som symbolförekomster när de pekar på en symbol.
   - Varje symbol länkas till närmaste rör (system) och till SpecItem via beteckning.

**j) Lodräta längder och nivåer.**
   - Plan visar inte stammar. Lodräta längder beräknas från höjdangivelser: rör på CL+2300 som ansluter till en apparat på känd höjd, eller från plan 0 (i mark, VG-angivelser) till plan 1.
   - Lodrätt-symboler (cirkel/prick med "upp/ner") detekteras; mellan nivåer används våningshöjd från A-ritning eller användarinmatning.
   - **Saknas data → lodrät längd anges som separat rad "ej bestämd" med antal förekomster**, aldrig som 0.
   - Standardpåslag för anslutningar (uppstick till blandare, golvbrunnsanslutning) konfigureras per objekttyp och redovisas separat från uppmätt längd.

**k) Flödesschema-avstämning.**
   - Schemat ger topologi och komponentlista per system (t.ex. KV: SIL101-25, ASS (BA), BV15, BV25, mätargrenar ×2; L9: AV25 vid kompressor, 4×AV20 uttag + AV20 avtappning).
   - Komponentantal i schema jämförs med plan och TB → Deviations.
   - Dimensionsangivelser i schema (KV01-28, L9-22) jämförs med plan.

**l) Resultat.**
   - `PipeRun` per (system, material, dim): horisontell, lodrät, total längd, källsegment, konfidens (längdviktat minimum av segmentkonfidenser).
   - Rördelar: antal böjar/T/reduktioner härleds från grafen (riktningsändringar > 30°, noder med grad 3, dimensionsbyten) – redovisas som *uppskattning* med egen konfidens.
   - Isolering: från TB-regler × PipeRuns (t.ex. "KV01 isoleras 30 mm diff.tät", "kopplingsledningar isoleras ej inom rummet de betjänar") → isolerlängder per dimension och tjocklek.

#### 6.4.4 Väg D och E – Skannade dokument, bilder och foton

Målet är att samma graf- och tilldelningslogik (g–l) ska kunna köras; skillnaden är hur segment och etiketter tas fram.

**1. Förbehandling (OpenCV)**
- *Foto (väg E):* hitta arkets kant/ram (största fyrhörning via konturer eller ritningsramens linjer) → homografi till rätt rektangel med arkets proportioner (A0–A4 enligt titelblock eller bildförhållande). Linskorrigering om EXIF finns.
- *Alla raster:* rotera rätt (Hough på rutnät/ram, 0,1° precision), avbrusa (non-local means), skuggkorrigering (bakgrundsdivision), adaptiv binarisering (Sauvola), separera färg om ritningen är i färg (rör har ofta egen färg – klustra i Lab-färgrymd).
- *Upplösningskrav:* minsta texthöjd i bild ≥ 20 px för att läsa etiketter automatiskt. Lägre → endast manuell mängdning, tydligt meddelande.

**2. Rastervektorisering**
- Skelettering (Zhang-Suen) + linjesegmentdetektion (LSD / `cv2.ximgproc.FastLineDetector`) + sammanfogning av kollineära segment.
- Linjetjocklek uppskattas med distanstransform → används som `stroke_width` precis som i vektor-PDF, så klassning (e) och stilprofiler fungerar likadant.
- Streckade linjer: fyll luckor längs samma riktning om luckorna är periodiska.
- Text- och symbolområden detekteras först (vision T5 + OCR) och maskas bort innan vektorisering, så text inte blir "rör".

**3. Etiketter:** samma tile-flöde som 6.4.3 c, men alltid med två oberoende läsningar (vision + OCR) och högre tile-upplösning.

**4. Skala:** deklarerad skala är **opålitlig** för skanningar (skalning vid utskrift/skanning) och oanvändbar för foton. Skalstock eller kända mått (rutnätsavstånd, måttkedja, dörrbredd från A-ritning) är **obligatoriska**; minst två oberoende referenser, annars ber UI användaren dra ut ett känt mått.

**5. Konfidens:** alla segment från väg D/E får max-konfidens 0.85 (väg E 0.75) oavsett metod, så de alltid passerar granskning före export. UI erbjuder halvmanuell spårning: användaren klickar på en rörlinje, systemet följer den i rastret till nästa förgrening (som "markera hela sträckan med ett klick").

#### 6.4.5 Projektets egen legend

Ritningar innehåller ofta en tabell "RÖRBETECKNINGAR" (material- och systemkoder), "FÖRKLARINGAR" (standarddimensioner på kopplingsledningar) och "MATRIS FÖR ISOLERING". Dessa ska:
1. Hittas (AI T2/T5 på sidans renderade högerspalt; text eller vision).
2. Läsas in till `Legend` för projektet.
3. **Ha företräde** framför standardtabellerna i Bilaga B.
4. Jämföras mellan ritningsblad – olika legend på olika blad → Deviation.

#### 6.4.6 Markerad PDF (utdata)

Varje analyserad ritning ska kunna exporteras som en **markerad PDF** – samma ritning med resultatet ritat ovanpå, så att kalkylator, konsult eller montör kan se exakt vad som mängdats:

- Rör ritas som PDF-annotationer (polylinjer, `PyMuPDF` `add_polyline_annot`) i systemets färg och med bredd efter dimension, ovanpå originalet (originalet ändras inte).
- Varje annotation bär metadata i sin kommentar: system, material, dimension, längd i meter, etikett, konfidens, segment-id. Annotationerna är standard-PDF-markeringar och kan därför öppnas och redigeras i Bluebeam, Adobe och andra PDF-verktyg.
- Etiketter som tolkats ringas in; okända tokens och avvikelser markeras med moln (`cloud`) och nummer som hänvisar till avvikelselistan.
- Otilldelade segment i rött, låg konfidens streckat orange.
- Symboler får en räknemarkering (t.ex. "B101P 1/2").
- Första sidan: teckenförklaring + summering per system × material × dimension.
- Export för vektor- och rasterunderlag på samma sätt (för foton i den korrigerade bildens koordinater, med originalfotot som bilaga).
- Export även som Excel/CSV av mängdlistan, och vid behov Bluebeam-markeringslista (CSV) **[ÖPPEN FRÅGA: används Bluebeam eller Wikells hos Dahl?]**.

#### 6.4.7 Ritningsmängder från vvs_engine (`DrawingQuantitySource`)

Mängdningen i 6.4.1–6.4.4 implementeras i första hand av `vvs_engine` (beslut 2026-11-02, se 7.5). Adaptern:

- anropar motorn som separat process (`vvs-takeoff analyze`) eller som bibliotek, och läser dess artefakter
  (`physical-pipes.json`, `quantities.json`, `drawing-legend.json`, `vector-designations.json`, …) med kontroll av
  `artifact_schema`;
- mappar motorns `PhysicalPipe` till `PipeRun` (system × material × dim, horisontell/lodrät längd, konfidens) och
  dess stammar och taggar till `Symbol`;
- behåller motorns evidenskedja i `source_refs` (sida, bbox, `method="vvs_engine"`, motorversion, pipe-id,
  ankare/ledare/källbanor), så att varje meter kan klickas fram till sina streck;
- översätter motorns tillstånd: `CONFIRMED` → konfidens enligt motorns egen bedömning, `AMBIGUOUS`/otilldelat →
  egna rader för granskning, och skala som inte är `VERIFIED` → sidan blockeras (6.4.3 f.4). Ingen meter räknas
  om eller rättas tyst i adaptern;
- kör alltid VS-Kalkyls egna kontroller ovanpå motorns resultat: skala mot titelblock och pappersstorlek (6.4.3 f),
  okända tokens mot projektets legend (6.4.3 d), otilldelad andel (6.4.3 h.5).

Gap mellan motorn och 6.4 åtgärdas i fas 6–8 och 9–11, antingen i motorn eller i VS-Kalkyl ovanpå den.

### 6.5 Avstämnings- och avvikelsemotor

Regler är Python-funktioner registrerade med id, allvarlighetsgrad och testfall. Minst följande i v1:

| Regel-id | Kontroll | Grad |
| --- | --- | --- |
| `TB_MENTIONED_NOT_ITEMIZED` | Objekt/produkt nämns i TB-text men har ingen post (T4) | critical |
| `TB_SELF_CONTRADICTION` | Samma post har motstridiga mått/värden (t.ex. 300x300x192 vs 300x300x400) | warning |
| `TB_QTY_VS_DRAWING` | Antal i TB ≠ antal symboler/taggar på ritning | warning |
| `DRAWING_ITEM_NOT_IN_TB` | Beteckning på ritning saknar TB-post | critical |
| `MATERIAL_CODE_MISMATCH` | TB-kod (t.ex. KV01-E9) ≠ ritning (KV01-E13) | warning |
| `UNKNOWN_LABEL_TOKEN` | Etikett innehåller kod som inte finns i legend | warning |
| `SCALE_DISAGREEMENT` | Skalmetoder skiljer > 1 % | critical |
| `UNASSIGNED_PIPE` | Otilldelad rörlängd > 2 % på sida | critical |
| `ACCESSORY_NOT_CONFIRMED` | TB-krävt tillbehör ej bekräftat i matchad artikel | warning |
| `OPTION_REQUIRED` | TB säger "ska ingå i anbudet, utreds senare" (t.ex. radontätning) | info |
| `UNDEFINED_VALUE` | Platshållare som "DN XX", "1-2 st" | warning |
| `CONFLICTING_REQUIREMENTS` | Två krav på samma sak som utesluter varandra | warning |
| `DRAWING_LIST_MISMATCH` | Ritning i förteckning saknas/finns utöver | critical |
| `TITLEBLOCK_MISMATCH` | Uppdragsnr/datum skiljer mellan TB och ritning | info |
| `DECIDE_WITH_CLIENT` | "i samråd med beställaren/kommunen" | info |

Varje avvikelse har länkar till källorna och ett föreslaget formulerat frågetext till konsult/beställare.

### 6.6 Leverantörsförfrågningar

1. Gruppera rader med `outcome=request` per leverantör (från register; okänd leverantör → användaren väljer).
2. AI T9 skriver mailutkast enligt mall (svenska, sakligt): projektnamn, beställare, uppdragsnummer, rader med beteckning, antal, **tekniska krav citerade ordagrant**, specifika frågor från `ACCESSORY_NOT_CONFIRMED`/`TB_SELF_CONTRADICTION`, optioner separat. Inga påhittade värden; deterministisk kontroll att alla antal/mått i mailet finns i raderna.
3. Bilaga: Excel med raderna (kolumner leverantörens art.nr, benämning, antal, enhet, pris, leveranstid tomma att fylla).
4. Skapa **utkast** i mailsystemet via API. Skicka aldrig automatiskt.
5. Svar: användaren laddar upp eller vidarebefordrar svaret; AI T10 extraherar pris/leveranstid per rad till `reply_prices_json` → granskas.

### 6.7 Export till Prixel

**[ÖPPEN FRÅGA]** Prixels importmöjligheter. Bygg gränssnittet `PrixelExporter` med implementationer:
1. `ExcelExporter` – kolumner i Prixels ordning (konfigurerbar mappning).
2. `ClipboardExporter` – tabbseparerad text i radordning som går att klistra in.
3. `ApiExporter` – stub tills API är bekräftat.

Rader grupperas per beteckning/position (som i Prixel-exemplet: rubrik `B202B`, sedan rad med art.nr, benämning, antal, enhet, rabattgrupp, leverantör). Fritextbeskrivning per rad = kort produktdata (dim, material, utlopp) genererad deterministiskt ur SpecItem.

---

## 7. AI-modeller: vilken modell gör vad, och hur

### 7.1 Modellval

Alla modell-ID ligger i `config/models.yaml` och kan bytas utan kodändring. Verifiera aktuella modell-ID, priser och funktioner i Anthropics dokumentation (docs.claude.com) innan driftsättning. Utgångsval:

| Id | Uppgift | Modell (default) | Eskalering | Varför |
| --- | --- | --- | --- | --- |
| T1 | Sidklassning | `claude-haiku-5-5` | `claude-sonnet-5-5` om låg konfidens | Enkel, många sidor, billig |
| T2 | Titelblock + legendtabeller | `claude-sonnet-5-5` (vision) | `claude-opus-5-5` | Små texter i tabeller |
| T3 | TB-strukturering | `claude-sonnet-5-5` | `claude-opus-5-5` för segment som misslyckas validering | Lång text, strikt schema |
| T4 | TB-fullständighetskontroll | `claude-opus-5-5` | – | Oberoende andra läsning, annan modell än T3 |
| T5T | Sortering och läsning av ritningstiles (tom/enkel/svår) | `claude-haiku-5-5` (vision) | – (ogiltigt svar → tilen läses av T5) | Kostnad: tiles där OCR inte hittar text går inte till AI alls (beslut 2026-11-02) |
| T5 | Etikettläsning på ritningstiles | `claude-sonnet-5-5` (vision) | T5R: omläsning av etikettutsnitt i 600 dpi med `claude-sonnet-5-5`, eskalering till `claude-opus-5-5` när läsningarna inte enas och Sonnet inte kan avgöra. Opus läser aldrig hela tiles. | Beslut 2026-11-03: träffsäkerheten går före kostnaden. Bilaga A: 88/88 exakt, 0 tysta fel (docs/t5_bilaga_a.md). Standard `labels_routing: all` = Sonnet på varje tile med bläck; `tiles`/`labels` (Haiku sorterar/läser) blir inte standard – Haiku och OCR kan göra samma fel och godkännas tillsammans. En läsning per ställe: fragment inne i en längre läsning tas bort |
| T6 | Artikel-rerank | `claude-haiku-5-5` | `claude-sonnet-5-5` vid score 0.6–0.95 | Väljer bara bland kandidater |
| T7 | Lager-/systemmappning (DXF/IFC) | `claude-sonnet-5-5` | – | Görs en gång per konsult |
| T8 | Vektorgruppsklassning (rör/vägg/ledare) | `claude-opus-5-5` (vision) | – | En gång per sida/stil |
| T9 | Mailutkast | `claude-sonnet-5-5` | – | Text, mall |
| T10 | Pris ur leverantörssvar | `claude-sonnet-5-5` | – | Strukturering |

### 7.2 Anropsregler

- Använd officiella SDK:n `anthropic`. All AI-kod i `app/ai/` bakom ett enda gränssnitt `AIClient.structured(task_id, inputs, schema) -> PydanticModel`.
- **Strukturerat svar:** definiera ett verktyg (tool) med JSON-schemat genererat från Pydantic-modellen och tvinga verktygsanrop, eller använd API:ts stöd för strukturerade utdata om det finns för vald modell (kontrollera i dokumentationen). Validera alltid med Pydantic.
- **Retry:** vid valideringsfel ett nytt anrop med felet bifogat; därefter eskalera enligt tabellen; därefter flagga. Nätverksfel: exponentiell backoff.
- **Determinism:** låg temperatur (0) där parametern stöds för modellen; cacha svar på `(task_id, model, prompt_version, input_hash)`.
- **Prompt caching:** systemprompt + projektets legend + TB-text återanvänds över många anrop – använd API:ts prompt-caching för dessa block.
- **Batch:** icke-brådskande jobb (t.ex. omkörning av hela tile-uppsättningar) via Message Batches API för lägre kostnad.
- **Bilder:** skicka tiles som PNG; håll varje bild inom API:ts rekommenderade storlek (kontrollera dokumentationen) – hellre fler tiles än nedskalning som gör text oläslig. Minsta texthöjd i tile ska vara ≥ 12 px.
- **PDF:** TB kan skickas som text (bäst, eftersom textlagret finns) – skicka inte TB som bild i onödan.
- **Loggning:** varje anrop i `AIRun` med tokens och kostnadsuppskattning. Kostnadstak per projekt i config; överskrids → pausa och fråga.

### 7.3 Promptprinciper (alla uppgifter)

Promptar ligger som versionerade filer i `app/ai/prompts/{task_id}/v{n}.md`. Varje prompt ska innehålla:
1. Roll och domän ("Du läser svenska VVS-handlingar enligt AMA VVS & Kyla").
2. Exakt uppgift och schema.
3. Hårda regler: *returnera bara det som står i källan; okänt = null; citera tekniska värden ordagrant; hitta aldrig på RSK eller art.nr; ange konfidens 0–1 och kort skäl.*
4. 2–4 exempel (few-shot) – från stilprofilen när sådana finns (kap 8).
5. För vision: "Läs tecken för tecken. Skilj på 0/O, 1/I/l, 5/S, 8/B. Bindestreck och plus är betydelsebärande (`VG+-828`). Ange rotation."

### 7.4 Exempel – schema för T5 (etiketter i tile)

```json
{
  "labels": [
    {
      "text": "KV01-K1-15-W40",
      "bbox_px": [412, 88, 598, 104],
      "rotation_deg": 0,
      "underlined": true,
      "has_leader": true,
      "leader_end_px": [520, 140],
      "confidence": 0.97,
      "uncertain_chars": []
    }
  ],
  "tile_has_cut_text": false
}
```
`tile_has_cut_text=true` → orkestreringen utökar tilen och kör om.

### 7.5 Andra modeller och tjänster – och hur valet görs

**Rekommendation:** Claude som primär modell för TB-läsning, avstämning, matchning och mail (lång svensk facktext, strikta scheman, resonemang över många regler). För **ritningsläsning** (T5, T8) ska valet avgöras av mätning, inte antaganden: bygg `AIClient` providerneutralt och kör en jämförelse på facitprojekten (kap 11) innan modell låses.

| Alternativ | Vad det är | Roll i systemet |
| --- | --- | --- |
| Claude (Anthropic) – Opus 5.5 / Sonnet 5.5 / Haiku 5.5 / Fable 5.1 | Allmänna modeller med vision och verktygsanrop | Primär för T1–T10. Fable 5.1 som eskalering på svåra etiketter. |
| OpenAI GPT-6 Astra | OpenAIs senaste allmänna modell; enligt [AEC Magazine](https://aecmag.com/ai/gpt-6-astra-and-the-future-of-bim-modelling) testad på att göra 3D-modeller av ritningar och foton och att granska en handlingsuppsättning | Kandidat i jämförelsen för T5/T8 (etiketter, vektorgruppklassning). API-villkor och pris måste verifieras. |
| Google Gemini (aktuell Pro-modell) | Allmän modell med stark bild-/dokumentförståelse | Kandidat i jämförelsen för T5 och skannad TB. |
| Klassisk OCR (PaddleOCR, Tesseract `swe`) | Lokala, deterministiska | Alltid med som oberoende andra läsning. |
| Egen tränad detektor (YOLO/RT-DETR) | Tränas på era godkända korrigeringar | Fas 2-option för symboler när ≥ 2 000 märkta exempel finns. |
| [handoff H1](https://www.handoff.ai/tech/h1-model-release) | Specialiserad mängdningsmodell med API; utvärderad på amerikanska bostadsritningar (bl.a. VVS-avlopp/plumbing) | Låg relevans: ej svenska VS-beteckningar eller AMA. Bevaka. |
| [FutureCalc](https://www.futurecalc.ai/sv) (modell "Meridian") | Svensk tjänst för VVS-mängdning ur PDF: läser beteckningar och ledarlinjer, markerar rör, mängdar per dimension och material, flaggar osäkert, export till Wikells/XLSX/CSV/Bluebeam | Direkt jämförbar med ritningsdelen i detta system. Se beslutspunkt nedan. |

**Providerregler:**
- `AIClient` har adaptrar `anthropic`, `openai`, `google`, med samma `structured()`-gränssnitt. Modell per uppgift sätts i `config/models.yaml`.
- Jämförelsen (`make bakeoff`) kör T5 och T8 på samma tiles med alla konfigurerade modeller och rapporterar tecken-exakthet, andel flaggade, kostnad och tid. Vinnaren per uppgift blir default.
- **Ensemble för etiketter:** när två olika modeller + OCR är överens är konfidensen hög; oenighet → eskalering. Det är billigare än att alltid köra den största modellen och ger en oberoende kontroll.
- Varje provider kräver separat granskning av avtal, dataplacering och om indata används för träning (kap 10).

**Beslutspunkt: bygga eller köpa ritningsdelen.** FutureCalc gör i stort det som 6.4 beskriver för PDF (enligt deras egen sida: endast PDF, automatisk markering av läsbara ritningar, manuell mängdning på skannade/fotograferade). Innan fas 6 startar: testa FutureCalc på Bilaga A och 2–3 facitprojekt. Om resultatet når gränserna i 11.2 kan ritningsdelen ersättas med import av deras export (XLSX/CSV) via en adapter `DrawingQuantitySource`, och detta system fokuserar på TB, avstämning, matchning, Prixel och förfrågningar – där FutureCalc inte verkar täcka Dahls behov. Bygg därför 6.5 så att mängder kan komma från egen analys **eller** extern källa.

**Beslut 2026-11-02:** ritningsdelen byggs inte på nytt. Den befintliga motorn `vvs_engine` (repo `sammm998/Dahlvvvs`) integreras som första implementation av `DrawingQuantitySource` (6.4.7). FutureCalc kan läggas till senare som en andra källa bakom samma adapter. Motorns egna AI-anrop (OpenAI-"second reader", vision-endpoint) används inte – AI i VS-Kalkyl går alltid via `app/ai/` (kap 7.2).

---

## 8. Robusthet över konsulter och ritningsstilar

Ritningar skiljer sig mellan konsulter (Bengt Dahlgren, Sweco, WSP, Ramboll, Afry, Norconsult, mindre byråer) och över tid. Strategi:

1. **Projektets legend först** (6.4.5) – systemet lär sig koderna från varje projekt, inte från en fast lista.
2. **StyleProfile per konsult** lagrar: etikettregex, lager→system-karta, linjebredd/mönster→kategori, typiska tile-storlekar, exempelbilder på etiketter + rätt läsning (few-shot), kända suffix (t.ex. `W40`, `L`, `F`) med betydelse efter att användaren förklarat.
3. **Ny stil detekteras** när: titelblockets konsult är okänd, > 10 % etiketter får `unknown_token`, eller vektorgruppernas statistik avviker kraftigt från alla profiler. Då körs "inlärningsläge": T8 körs på varje sida, UI ber användaren bekräfta 3–5 grupper och 10 etiketter, profil skapas.
4. **Korrigeringar** (`Correction`) återförs: felläst etikett → läggs som few-shot-exempel; felklassad linjegrupp → profilen uppdateras. Versionera profiler.
5. **Grammatiken är data** (Bilaga B, `config/label_grammar.yaml`), inte kod. Varianter som `KV1-CU-15`, `VS 21 - K1 - 20`, `Ø110 PP` eller dimension i tum (`3/4"`) ska läggas in som alternativa mönster.
6. **Testsvit per stil** (kap 11): minst ett projekt med facit per konsult innan profilen räknas som produktionsklar.

---

## 9. Granskningsgränssnitt

Vyer:

1. **Projektöversikt:** dokument, sidklassning, status per pipeline-steg, avvikelser per allvarlighetsgrad, kostnad.
2. **TB-lista:** tabell över SpecItems (redigerbar), barnposter indenterade, klick på rad → TB-sidan med markerad källa.
3. **Ritningsvy:** pdf.js (bilder via canvas) med overlay. Rör färgade per system (färg från legend), tjocklek per dimension. Hover → etikett, längd, konfidens, metod. Otilldelade segment i rött. Låg konfidens streckat orange. Klick på en rad i mängdlistan markerar dess segment, etikett och ledarlinje i ritningen.
   Verktyg (fungerar på vektor, skanning och foto):
   - tilldela/ändra etikett, markera grupp som rör/inte rör, dela/slå ihop segment,
   - **markera hel sträcka med ett klick** (följer grafen eller rastret till nästa förgrening),
   - manuell ritning av rör med snäpp till linjer/ändpunkter, ortoläge (0/45/90°) och avdrag,
   - räkneverktyg för symboler, lodrät längd som manuell post,
   - sätta skala (dra ut känt mått),
   - **revisionsjämförelse:** ny ritningsrevision läses in och skillnad i meter per system×dim visas, ändrade segment markeras.
4. **Mängdlista:** PipeRuns per system/material/dim, symbolantal, isolering, rördelar (uppskattning tydligt märkt). Varje tal klickbart till sina segment.
5. **Avvikelser:** lista med källor, föreslagen fråga, status.
6. **Matchning:** rad → kandidater, vald artikel, utfall (lager/virtuellt/förfrågan/osäker), godkänn.
7. **Förfrågningar:** mailutkast per leverantör, redigera, godkänn → skapa utkast i mailsystemet.
8. **Export:** Prixel-fil/urklipp, PDF-sammanställning av avvikelser till konsult.

Allt som ändras manuellt loggas i `Correction`.

---

## 10. Säkerhet, sekretess och drift

- Förfrågningsunderlag är konfidentiella. Lagra krypterat i vila, åtkomst via inloggning (Entra ID/SSO **[ÖPPEN FRÅGA]**), rollstyrning per projekt.
- AI-anrop: klargör med IT/juridik krav på dataplacering. Alternativ: Anthropics API direkt, eller Claude via molnleverantör i EU-region (verifiera att valda modeller finns där). Konfigurerbar `AI_PROVIDER`.
- Inga personuppgifter behövs utöver namn i handlingarna; logga inte mer än nödvändigt.
- Utgående: mail endast som utkast; Prixel endast fil/urklipp tills API bekräftats.
- Hemligheter i miljövariabler/secret store, aldrig i repo.
- Observability: strukturerad loggning, jobbstatus, kostnad per projekt och steg.

---

## 11. Utvärdering och tester

### 11.1 Facitdata

Samla 10–20 avslutade förfrågningar med: TB, ritningar, och **facit** = kalkylatorns slutliga artikellista i Prixel + (för mängder) manuellt uppmätta rörmeter för minst 3 projekt. Fördela över minst 4 konsulter. Lagra i `eval/projects/{namn}/` (utanför git om konfidentiellt; i git endast Bilaga A-projektet om tillåtet).

### 11.2 Mått och acceptansgränser (v1)

| Mått | Gräns |
| --- | --- |
| TB: recall på sakvaror (rader i facit som hittas) | ≥ 98 % |
| TB: precision (påhittade rader) | ≥ 99 % |
| RSK/art.nr exakt korrekt | 100 % (valideras mot källtext) |
| Antal korrekt | ≥ 99 % |
| Etikettläsning tecken-exakt (vektor-PDF) | ≥ 98 %; resterande flaggade |
| Andel otilldelad rörlängd | ≤ 2 % per sida |
| Rörmeter per system×dim jämfört med manuell mätning | ±3 % (horisontellt) |
| Symbolantal (brunnar, ventiler, uttag) | 100 % eller flaggat |
| Skala | Två metoder inom 1 % eller blockerat |
| Artikelmatchning: rätt utfall (lager/förfrågan) | ≥ 95 %, resten "osäker" |

En kombination konsult×format räknas som produktionsklar först när gränserna nås på dess facit.

### 11.3 Testtyper

- **Enhetstester:** grammatikparser (alla exempel i Bilaga B), skalberäkning, snappning, propagering, regelmotor (varje regel minst ett positivt och ett negativt fall).
- **Snapshot-tester:** TB-extraktion för Bilaga A (AI-svar cachade så att testet är deterministiskt).
- **Golden-tester:** hela pipelinen på Bilaga A → jämför mot facit i `eval/projects/arjang_tvatthall/expected/`.
- **Syntetiska ritningar:** generera DXF/PDF med kända rörlängder och etiketter i olika stilar (rotation, typsnitt, linjebredd, med/utan ledare, korsande rör utan koppling) → exakt facit för mängdmotorn.
- **Regression:** `make eval` kör alla facitprojekt och skriver en rapport (markdown) med måtten ovan; CI failar om något mått sjunker.

---

## 12. Repo-struktur och kodkonventioner

```
vs-kalkyl/
  SPEC.md                    # detta dokument
  CLAUDE.md                  # kort: konventioner, kommandon, pekare hit
  docker-compose.yml
  Makefile                   # make dev, make test, make eval, make migrate
  backend/
    app/
      main.py                # FastAPI
      config/                # settings.py, models.yaml, label_grammar.yaml, thresholds.yaml
      db/                    # SQLAlchemy-modeller, Alembic-migreringar
      ingest/                # filtyper, rendering, tiles, DWG/DXF/IFC-läsare
      classify/              # sid- och titelblocksklassning
      tb/                    # segmentering, strukturering, validering, fullständighet
      drawings/
        legend.py
        scale.py
        vectors.py           # get_drawings → segment, glyfkluster
        labels.py            # textlager, vision, OCR, sammanslagning
        grammar.py           # parser enligt label_grammar.yaml
        graph.py             # snappning, graf, korsningsregler
        assign.py            # ledare, närhet, propagering, konflikter
        symbols.py
        vertical.py
        schematic.py
        quantities.py        # PipeRuns, rördelar, isolering
        paths/ifc.py, paths/dxf.py, paths/pdf_vector.py, paths/pdf_raster.py
      rules/                 # en fil per regel + registry
      articles/              # registerimport, matchning
      suppliers/             # mailutkast, svarsextraktion, mailadapter
      export/                # PrixelExporter-implementationer
      ai/
        client.py            # AIClient.structured, retry, eskalering, cache, loggning
        schemas/             # Pydantic-scheman per uppgift
        prompts/T1..T10/v1.md
      jobs/                  # Celery-tasks per steg
      api/                   # REST-endpoints
    tests/
  frontend/
    src/ (views enligt kap 9)
  eval/
    projects/arjang_tvatthall/{input,expected}/
    synthetic/
    run_eval.py
```

Konventioner: typannoteringar överallt, `ruff` + `mypy --strict` i backend, `eslint` + `tsc --noEmit` i frontend. Inga AI-anrop utanför `app/ai/`. Inga magiska tal – trösklar i `thresholds.yaml`. Svenska i UI och genererade texter, engelska i kod.

---

## 13. Faser och milstolpar

| Fas | Innehåll | Definition of Done |
| --- | --- | --- |
| 0 | Repo, Docker, DB, CI, AIClient med loggning och cache, config-filer | `make test` grönt; ett AI-testanrop loggas i `AIRun` |
| 1 | Intag, sidklassning, titelblock, ritningsförteckning | Bilaga A: alla 5 dokument/sidor rätt klassade, ritningsnr och skala lästa |
| 2 | TB-extraktion inkl. barnposter, validering, fullständighetskontroll | Bilaga A: alla 28 rader enligt A.1 (inkl. barnposter och kylaggregaten rad 27–28) plus rörraden, inga påhittade; golvränna-avvikelsen hittas |
| 3 | Regelmotor (TB-regler) + granskningsvy för TB och avvikelser | Bilaga A: avvikelser 1–4, 7–9 i A.3 hittas |
| 4 | Artikelregister-import + matchning + Prixel-export (Excel/urklipp) | Med testregister: rätt utfall för alla rader med RSK |
| 5 | Leverantörsmail (utkast) + svarsextraktion | Furhoffs-utkast för Bilaga A innehåller B201B, B202B, TS501 och frågorna |
| 6 | Ritning väg C – **integrera vvs_engine** via `DrawingQuantitySource` (6.4.7); mät dess etikettläsning, grammatik och legend mot facit; åtgärda gapen: vision (T5) + OCR som oberoende läsningar, flaggade teckenförväxlingar, `unknown_token`, FÖRKLARINGAR och MATRIS FÖR ISOLERING | Bilaga A: alla etiketter i A.4 lästa tecken-exakt eller flaggade |
| 7 | **Integrera vvs_engine:s** skala, graf, tilldelning, propagering och mätning → PipeRuns; mät mot facit och åtgärda gapen (skalval mot sidans pappersstorlek och två oberoende metoder, `ENTR. GRÄNS`, kopplingsledningar ur FÖRKLARINGAR); ritningsvy med overlay | Syntetiska ritningar ±0,5 %; Bilaga A ≤ 2 % otilldelat |
| 8 | **Integrera vvs_engine:s** stamräkning och lodräta längder → Symbol/PipeRun; mät mot facit och komplettera det som saknas i motorn: VVS-symboler per typ mot legend, flödesschema-igenkänning och -avstämning, rördelar, isolering | Bilaga A: avvikelser 5–6 hittas; symbolantal enligt A.5 |
| 9 | Väg B (DXF/DWG) och väg A (IFC) | Syntetiska DXF/IFC exakta |
| 10 | Stilprofiler + inlärningsläge + korrigeringsåterföring | Andra konsultens facitprojekt klarar 11.2 |
| 6b | Markerad PDF-export (6.4.6) + Excel-mängdlista | Bilaga A: markerad PDF öppnas i Adobe/Bluebeam, alla rör färgade, summering på första sidan |
| 11 | Väg D och E (skanning, bild, foto) inkl. förbehandling, rastervektorisering, halvmanuell spårning | Bilaga A renderad till 200 dpi-bild och fotograferad version: ±5 % rörmeter efter granskning, alla etiketter lästa eller flaggade |
| 12 | Utvärderingsrapport, härdning, SSO, drift | `make eval` rapport på alla facitprojekt |

Fas 1–5 ger nytta direkt (motsvarar dagens manuella arbete). Fas 6–8 är ritningsmängdningen, som **inte byggs från grunden**: den befintliga motorn `vvs_engine` (repo `sammm998/Dahlvvvs`) integreras, mäts mot facit och kompletteras där den inte når gränserna i 11.2 (beslut 2026-11-02). Utgångsmätningen på Bilaga A finns i `docs/vvs_engine_bilaga_a.md`. Acceptansgränserna i 11.2 gäller oförändrat för motorns resultat.

---

## 14. Öppna frågor (måste besvaras av Dahl – gissa inte)

1. **Prixel:** finns import (Excel/CSV/API)? Kolumnformat? Hur hanteras rubrikrader (positioner som `B202B`)? Vad betyder fälten i exempelraden (`4252,00 STK. 4252 DF9999 4039,00 5,0 T Furhoffs`) – t.ex. bruttopris, rabattgrupp/varugrupp, nettopris, rabatt %, prisstatus?
2. **Artikelregister:** vilket affärssystem, exportformat, hur markeras "virtuellt lager"?
3. **Mailsystem:** Outlook/Microsoft 365 eller Gmail? Ska utkast skapas i användarens egen brevlåda?
4. **Leverantörsregister:** mailadresser/kontaktvägar per leverantör (Furhoffs m.fl.).
5. **Hosting och dataplacering:** on-prem, Azure, annat? Krav på EU-region för AI-anrop?
6. **Inloggning:** Entra ID/SSO?
7. **Facitprojekt:** vilka 10–20 tidigare förfrågningar kan användas, och finns slutliga Prixel-offerter som facit?
8. **Konsultfiler:** kan DWG/IFC begäras rutinmässigt i förfrågningar?
9. **Påslag:** standardpåslag för rördelar/spill per system som kalkylatorerna använder idag?
10. **Bygga eller köpa ritningsdelen:** har FutureCalc testats? Används Wikells eller Bluebeam hos Dahl (styr exportformat)?
11. **AI-leverantörer:** vilka leverantörer (Anthropic, OpenAI, Google) är godkända av IT/juridik?

---

## 15. Bilaga A – Testfall: Nybyggnad tvätthall/verkstad samt carport, Årjängs Bostads AB

Underlag: `11.5 Teknisk Beskrivning VS.pdf` (37 s, Bengt Dahlgren Karlstad AB, uppdrag 70250105, 2025-09-15, AMA VVS & Kyla 22) och `12.4 Ritningar VS.pdf` (4 s: ritningsförteckning, W-50-1-1000 Plan 1, W-53-1-0900 Plan 0 i mark, W-50-8-1000 Flödesschema VS; skala 1:50 (A1) / 1:100 (A3)). Obs (uppmätt 2026-11-02): ritningsförteckningen är A4, men sidorna 2–4 är **A1** (2384 × 1684 pt), så `1:50 (A1)` gäller direkt på sidorna – bekräftat med dörrbågar i A-underlaget (0,8–1,1 m vid 1:50).

Viktig egenskap: ritningarnas all text (utom några rumsnamn) är ritad som linjer → testar etikettläsning via vision.

### A.1 Förväntade SpecItems (facit)

| # | Beteckning | Produkt | Art.nr / RSK | Antal | quantity_mode |
| --- | --- | --- | --- | --- | --- |
| 1 | B201B | Sandfångsbrunn Furhoffs FURO 152, stålslipat betonggolv, EN1.4404, bottenutlopp 110, vattenlås, sandfång, galler 1500 kg, ställben, skyddslock | – | 1 st | fixed |
| 2 | B202B | Golvbrunn Furhoffs FURO 142, halkskyddad epoxi, 273x273x250, EN1.4404, utlopp 110, vattenlås, rutgaller M125, ställben, skyddslock | – | 1 st | fixed |
| 3 | B101P | Golvbrunn Purus Brage, plastmatta, urtagbart vattenlås, klämring, plastsil | – | 2 st | fixed |
| 4 | TS101 | Tvättställ IFÖ Cera 23220, 570x435 | RSK 7606418 | 1 st | fixed |
| 5 | (TS101) | Ettgreppsblandare FMM 9000E EcoSafe | 8060-0000 | 1 st | fixed |
| 6 | (TS101) | Silventil FMM S600017 | RSK 8560167 | 1 st | fixed |
| 7 | (TS101) | Avstängningsventil Broen Ballofix förkromad med vred | – | 2 st | fixed |
| 8 | TS501 | Tvättränna Furo 40512H, 1200x451, EN 1.4301, utlopp höger, stänkbleck 95 mm | 40512H | 1 st | fixed |
| 9 | (TS501) | Tvättränneblandare FMM 9000E | 8118-0010 | 2 st | fixed |
| 10 | (TS501) | Ballofix | – | 4 st | fixed |
| 11 | VK101 | WC IFÖ Spira 6261-0931-1010, vit, med sits | RSK 7811054 | 1 st | fixed |
| 12 | (VK101) | Ballofix | – | 1 st | fixed |
| 13 | UB101 | Utslagsback IFÖ CU 44G | RSK 8036222 | 1 st | fixed |
| 14 | (UB101) | Tvågrepps spolblandare FMM | 3160-0610 | 1 st | fixed |
| 15 | (UB101) | Blandarfäste 160cc FMM 2099-1600 | RSK 8188682 | 1 st | fixed |
| 16 | (UB101) | Ballofix | – | 2 st | fixed |
| 17 | VUK101 | Vattenutkastare FMM 4293-0600 | RSK 4316698 | 1 st | fixed |
| 18 | VVB001 | Varmvattenberedare Nibe Eminent 55 R, med ventilrör | – | 1 st | fixed |
| 19 | SIL101 | Smutsfilter AT 4003A DN25 | AT 4003A | 1 st | fixed |
| 20 | ASS401 | Återströmningsskydd BA AT 1168C25M DN25 | AT 1168C25M | 1 st | fixed |
| 21 | BV201 | Backventil EA AT 1159 | AT 1159 | Enl ritn | per_drawing |
| 22 | AV201 | Kulventil Armatec AT3700/AT3701 | – | Enl ritn | per_drawing |
| 23 | AV203 | Kulventil Beulco BA 107 | – | Enl ritn | per_drawing |
| 24 | TRYCKLUFTSUTTAG | Tryckluftsuttag DN20 med AV203 och snabbkoppling | – | 4 st | fixed |
| 25 | RA101 | Rensrör Wafix grå PP med lock | – | 2 st | fixed |
| 26 | VM101 | Vattenmätare (kommunen) + vattenmätarkonsol (VSE) | – | 1–2 st | range |
| 27 | PAK.514 | Utedel Mitsubishi MUZ-FT25VGHZ(-SC) + markstativ DP-900 | – | 2 st | fixed |
| 28 | PJC.2222 | Innedel Mitsubishi MSZ-FT25VGK(-SC) | – | 2 st | fixed |
| – | Rör | L9-S13 Mapress elförzinkat; KV01/VV01-K1; KV01/VV01-K5; KV01-E9/E13 PEM PN10; S01/S02-P2 PP mark SN8; S01/S02-P3 Wafix PP | – | Enl ritn | per_drawing |

(Ballofix kan även summeras till totalt 9 st i exporten.)

### A.2 Förväntade generella krav (`ProjectRule`)

- Tryckluft: O-ringar bytas till Viton (gröna).
- Synliga ledningar i WC, städ, verkstad förkromade (K5).
- Blandare utan inbyggd föravstängning förses med Ballofix.
- Isolering: KV01 30 mm diff.tät, VV01 40 mm, L9 i tvätthall 30 mm; synliga raka rör ytbeklädda med mönsterpräglad aluminiumplåt 0,2 mm; kopplingsledningar isoleras ej inom rummet de betjänar.
- Avtappningsdon under alla horisontella stammar för L9.

### A.3 Förväntade avvikelser

1. `TB_MENTIONED_NOT_ITEMIZED` – golvränna i verkstad och tvätthall nämns i 53.B; plan 0 har texten "Monteras i golvränna" vid B201B; ingen PR-post.
2. `TB_SELF_CONTRADICTION` – B201B 300x300x192 i text vs 300x300x400 i specifikation.
3. `TB_SELF_CONTRADICTION` (info) – B202B text "Storlek Golvtyp …" ofullständig mening.
4. `OPTION_REQUIRED` – radontätning B201B/B202B "ska ingå i anbudet, utredningen sker i senare skede".
5. `MATERIAL_CODE_MISMATCH` – TB `KV01-E9` vs ritning `KV01-E13-40` (legend: E13 = PEM-rör PN10).
6. `TB_QTY_VS_DRAWING` – RA101 2 st i TB; kontrollera antal på plan.
7. `CONFLICTING_REQUIREMENTS` – PUC.1: plastbelagda konsoler vs förstärkta konsoler typ skolmodell.
8. `UNDEFINED_VALUE` – VM101 "DN XX", "1-2 st".
9. `TITLEBLOCK_MISMATCH` – ritningar uppdragsnr 70230105, TB 70250105.
10. `DECIDE_WITH_CLIENT` – snabbkopplingstyp tryckluft/tappvatten; vattenmätarkonsol med kommunen.
11. `ACCESSORY_NOT_CONFIRMED` – B202B mot Prixel-artikel 142B1106 (rutgaller M125, vattenlås, ställben, skyddslock).
12. `TITLEBLOCK_MISMATCH` (info) – ritningsförteckningen anger skala "-" för W-50-8-1000, flödesschemats titelblock 1:50 (A1) / 1:100 (A3) (tillagd 2026-11-02).
13. `UNKNOWN_LABEL_TOKEN` – suffixen `W40`, `W` och `F` i `KV01-K1-15-W40`, `KV01-K1-15-W` och `VV01-K1-15-F` finns inte i legenden: fråga till konsulten, betydelsen gissas inte. Den tvetydiga gränsen mellan `KV01-K1-W40` och `KV01-K1-W` (2,75 m, W-50-1-1000) förblir tvetydig tills konsulten svarat (tillagd 2026-11-03).

### A.4 Etiketter som ska läsas (urval, tecken-exakt)

Plan 1 (W-50-1-1000): `KV01-K1-15-W40`, `KV01-K1-28-W40`, `KV01-K1-W40`, `KV01-K1-15`, `KV01-K1`, `AV201-15`, `AV201-25`, `AV203-20`, `L9-S13-28`, `L9-S13-22`, `L9-28`, `L9`, `22`, `28`, `VV01-K5`, `KV01-K5`, `KV01-K5-15`, `VV01-K1-15-F`, `KV01-K1-15-W`, `S01-P3`, `S03-P2`, `S02-P2`, `RA101`, `B101P`, `B201B`, `B202B`, `CL+3400`, `CL+2900`, `CL+2700`, `CL+2550`, `CL+2300`, `CL+1400`, `VVB001`, `55L`, `110L`, `110`, `75`, `15`, `VUK`, texter `ANSL. HÖGTRYCK`, `ANSL. SPOLSLANG`, `ANSL. TRYCKLUFT`.

Plan 0 (W-53-1-0900): `KV01-E13-40`, `KV01-E13`, `40`, `S01-P2-75`, `VG+-563`, `S01-P2`, `110L`, `S03-P2`, `S02-75L`, `VG+-570`, `VG+-733`, `S01-110`, `S01-P2-110`, `VG+-635`, `VG+-700`, `VG+-609`, `S02-P2-75`, `VG+-757`, `S02-P2-110`, `VG+-828`, `VG+-857`, `VG+-834`, `S03-P2-110L`, `VG+-1005`, `ENTR. GRÄNS`, `IHOPKOPPLING LUFTNING`, `Monteras i golvränna`, `1:100` (fall).

Flödesschema (W-50-8-1000): `L9-22`, `L9-28`, `AV20`, `AV25`, `AVTAPPNING`, `KV01-15`, `KV01-28`, `VV01-15`, `BV15`, `BV25`, `AV15`, `SIL101-25`, `VATTENUTKASTARE`, `HÖGTRYCKSTVÄTT`, `SPOLSLANG`, `80°C`, `60°C`, `VVB 55 LITER`.

Obs: `W40`, `W`, `F` som suffix finns inte i legenden → ska ge `UNKNOWN_LABEL_TOKEN` (fråga användaren/konsulten om betydelse), inte tolkas bort. `1:100` intill spillvattenledningar = fall (1 %), inte skala.

### A.5 Förväntade symbolantal

- Golvbrunnar: B101P 2, B201B 1, B202B 1.
- Tryckluftsuttag (schema): 3 i verkstad + 1 i tvätthall = 4, plus 1 avtappning (AV20) och AV25 vid kompressor.
- Tappvatten (schema): SIL101 1, återströmningsskydd BA 1, backventiler BV15 1 och BV25 1, avstängningsventiler AV15 ×4 (3 på utkastare/högtryck/spolslangar + 1 efter BV15 på KV01-15 före beredaren) och AV25 ×1, två parallella mätargrenar.
- Legenden: RÖRBETECKNINGAR (material och system), FÖRKLARINGAR (kopplingsledningsdimensioner), MATRIS FÖR ISOLERING ska läsas in.

### A.6 Förväntad Prixel-rad (format, exempel från användaren)

```
B202B
1  142B1106 Golvbrunn FURO 142        4252,00  STK.  4252  DF9999  4039,00  5,0  T  Furhoffs
   Dim. L=273 mm B=273 mm.
   För massagolv. Bottenutlopp Ø110 mm.
   Syrafast kvalitet EN 1.4404.
```

---

## 16. Bilaga B – Referenstabeller
17. Bilaga C – Filer och länkar som följer med

> Standardtabeller. **Projektets egen legend har alltid företräde.** Lagras i `config/`.

### B.1 Materialkoder (från Bengt Dahlgrens legend i Bilaga A – vanlig svensk praxis)

| Kod | Betydelse |
| --- | --- |
| K1 | Koppar, hårda |
| K5 | Koppar, förkromade |
| K6 | Koppar, prisol |
| K7 | Koppar, plusprisol |
| S1 | Stålrör, blå |
| S13 | Mapress eller likv. |
| S4 | Ståltub |
| G3 | MA-rör |
| R1 | Rostfritt, PN10 |
| R3 | Rostfritt, syrafast |
| R10 | Rostfritt, syrafast, för avlopp |
| E13 | PEM-rör, PN10 |
| X2 | PEX, golvvärme |
| X3 | PEX-rör |
| X7 | Alupex, komposit |
| X8 | Plastkulvert, PEX, VS |
| X9 | Plastkulvert, VV, VVC |
| P2 | PP-rör, markavlopp |
| P3 | PP-rör, inomhus |
| P5 | PP-rör, ljuddämpande |

### B.2 Systemkoder

| Kod | Betydelse |
| --- | --- |
| VS21 | Radiatorvärme sekundär |
| VP01 | Värme primär |
| VS11 | Ventilationsvärme sekundär |
| VS31 | Golvvärme sekundär |
| KS01 | Kyla sekundär |
| KP01 | Kyla primär |
| KV | Tappkallvatten |
| VV | Tappvarmvatten |
| VVC | Tappvarmvatten cirkulation |
| S01 | Spillvatten |
| D01 | Dagvatten |
| S01L | Spillvatten, luftning |
| S02 | Spillvatten, oljeavskiljare |
| S03L | Luftning oljeavskiljare |
| L9 | Tryckluft allmän |

### B.3 Material → AMA-kod (för koppling ritning ↔ TB)

| Material | AMA-kod (typiskt) |
| --- | --- |
| K1 | PNU.311 Ledningar av icke ytbehandlade raka kopparrör |
| K5 | PNU.312 Ledningar av ytbehandlade raka kopparrör |
| S13 (C-stål) | PNU.215 Ledningar av raka tunnväggiga olegerade stålrör |
| E13 / E9 (PE) | PNU.5121 Ledningar av PE-rör, standardiserade tryckrör |
| P2 | PNU.521 Ledningar av plaströr, markavloppsrör |
| P3 | PNU.5223 Ledningar av PP-rör, inomhusavloppsrör |

Kopplingen ska i första hand läsas ur TB (TB listar t.ex. `KV01-K1  Tappkallvatten  Enl ritn` under PNU.311). Tabellen används när TB saknar explicit koppling.

### B.4 Beteckningsgrammatik (`config/label_grammar.yaml`, utgångsläge)

```yaml
pipe:
  # SYSTEM[NR]-MATERIAL-DIM[-SUFFIX...]
  pattern: '^(?P<system>[A-Z]{1,4}\d{0,3}L?)(?:-(?P<material>[A-Z]{1,2}\d{1,2}))?(?:-(?P<dim>\d{1,3}(?:[.,]\d)?L?))?(?P<suffixes>(?:-[A-Z]+\d*)*)$'
  examples_ok: [KV01-K1-15-W40, S02-P2-110, L9-S13-28, S01-P2-110L, KV01-E13-40, VV01-K1-15-F, KV01-K1, L9-28, KV01-15, S01-110]
  notes:
    - "Dimension avser mm, tum eller DN enligt legend ('Rördimension avser mått i mm, tum eller DN')."
    - "Suffix 'L' efter dimension = luftning (110L)."
    - "Okänt suffix (W40, W, F) => unknown_token, fråga."
    - "Ensam dimension ('22', '28', '15') under en etikett hör till närmaste rör/etikett ovanför (understruken siffra)."
height:
  cl: '^CL\+(?P<mm>\d{3,5})$'          # centrumhöjd mm över färdigt golv
  vg: '^VG\+-(?P<mm>\d{2,5})$'         # vattengång relativt färdigt golv (tecken enligt konsult)
slope: '^1:(?P<n>\d{2,4})$'            # fall, t.ex. 1:100 – får ALDRIG tolkas som skala nära rör
object:
  pattern: '^(?P<type>[A-Z]{1,4})(?P<nr>\d{2,4})(?P<suffix>[A-Z]?)(?:-(?P<dim>\d{1,3}))?$'
  examples_ok: [B201B, B101P, AV201-15, AV203-20, SIL101-25, RA101, VVB001, VUK101, TS501]
schematic_valve:
  pattern: '^(?P<type>AV|BV|IV|SV|BLV)(?P<dim>\d{2,3})$'   # AV15, BV25 = typ + DN direkt
  examples_ok: [AV15, AV20, AV25, BV15, BV25]
alternatives:   # andra konsulters varianter – fyll på via stilprofiler
  - '^(?P<system>[A-Z]{2,4})\s?(?P<nr>\d{1,3})\s?-\s?(?P<material>[A-Z]{1,2}\d{1,2})\s?-\s?(?P<dim>\d{1,3})$'
  - '^Ø(?P<dim>\d{2,3})\s?(?P<material>PP|PVC|PE|GJK|SML)$'
  - '^(?P<dim>\d/\d|\d(?: \d/\d)?)\"$'
```

Varje ändring i grammatiken kräver att alla `examples_ok` fortfarande parsas och att `make eval` inte försämras.

---

## 17. Bilaga C – Filer och länkar som följer med

Paketet `vs-kalkyl-start.zip` innehåller denna fil och testunderlaget i rätt mappstruktur:

```
SPEC.md
eval/projects/arjang_tvatthall/input/
  11_5_Teknisk_Beskrivning_VS.pdf   # TB, 37 s, textlager finns
  12_4_Ritningar_VS.pdf             # 4 s: ritningsförteckning, W-50-1-1000, W-53-1-0900, W-50-8-1000 (text ritad som linjer)
  prixel_exempelrad_B202B.png       # så ser en färdig rad ut i Prixel (Bilaga A.6)
  tb_utdrag_PRB12.png               # utdrag ur TB, PRB.12 golvbrunnar
eval/projects/arjang_tvatthall/expected/
  README.md                         # facit skapas i fas 0 från Bilaga A (A.1–A.5) som JSON/CSV
```

**Länkar:**
- Dahls produktkatalog 2026: https://katalog.dahl.se/dahl-sverige-ab/dahl-produktkatalog-2026pdf/
  Används **inte** som datakälla för matchning (bläddrings-PDF, ingen lagerstatus). Får användas manuellt som referens för benämningar och bilder. Matchning sker mot artikelregister-exporten (6.3, öppen fråga 2).
- Anthropic API-dokumentation (modell-ID, strukturerade utdata, prompt caching, batch): https://docs.claude.com
- FutureCalc (jämförelse/köpalternativ för ritningsdelen, 7.5): https://www.futurecalc.ai/sv
- handoff H1 (bevakas, 7.5): https://www.handoff.ai/tech/h1-model-release
- GPT-6 Astra, artikel (kandidat i bakeoff, 7.5): https://aecmag.com/ai/gpt-6-astra-and-the-future-of-bim-modelling

**Fas 0, extra uppgift:** skriv `expected/spec_items.json`, `expected/deviations.json`, `expected/labels.json` och `expected/symbols.json` utifrån Bilaga A, och låt `make eval` läsa dem.
