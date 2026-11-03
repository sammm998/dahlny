# Nya ritningar (Higab, Andersson & Hultmark) – test 2026-11-03

Fyra blad som användaren laddade upp: V50-01-2711, V50-01-2713, V50-01-2811D (A3, vektor, text ritad som linjer) och
V50-01-4212-OMB (A1, en inbäddad rasterbild). Inget facit finns; filerna ligger bara i sandlådan och checkas aldrig in.

## Vad som var fel och rättades (generella regler med syntetiska tester)

| Fel | Rättning | Var |
| --- | --- | --- |
| Demonteringsritning togs som vanlig plan | Flagga `purpose:demolition` ur sidans text | `classify/pages.py`, `documents.yaml` |
| Ritningsnumret lästes inte (`V50-01-2711` matchade bara Bengt Dahlgrens mönster `W-50-1-1000`) | Nytt mönster för disciplin+kategori-del-löpnummer med ev. bokstav och tillägg | `config/documents.yaml` |
| Rörlista på en rad (`KV02-53-,VV02-53-20`, `KV01-53-20,VV01-53-20,VVC01-53-16`) lästes som en beteckning | Delas i en rad per rör, staplade i listans ordning; led utan dimension ärver sista ledets | motorn `text/external_labels.py` (`SPLIT_PIPE_LISTS`) |
| Motorn kraschade (IndexError) när en delad lista låg bredvid en etikett utan bläck – bläckflaggan låg i en parallell lista | Flaggan följer etiketten | `text/external_labels.py` |
| Ritningshänvisningen `V50-02-271` blev ett rör med DN271 | Bara dimensioner som rör tillverkas i gör en text till ett rör | `semantics/legend.py` (`PIPE_SIZES_ONLY`) |
| Listkoder med platshållare (`KBXX-6 KÖLDBÄRARE, ROSTFRITT STÅL`) blev material | En systemmall med XX och materialled är ett system | `semantics/legend.py` (`PLACEHOLDER_IS_SYSTEM`) |

## Mätning (med T5-etiketter, 1,4 USD/blad)

| Blad | Skala | Rörgeometri | Namngivet före → efter | Otilldelat före → efter |
| --- | --- | --- | --- | --- |
| V50-01-2711 | 1:100 på A3, verifierad mot skalstock | 927 m | 120 → 167 m | 85 % → 76 % |
| V50-01-2713 | 1:100 på A3, verifierad | 1028 m | 284 → 328 m | 70 % → 62 % |
| V50-01-2811D | 1:100 på A3, verifierad | 129 m | 0 → 0 m | 100 % → 97 % |
| V50-01-4212-OMB | ingen (rasterbild) | 0 m | – | – |

Årjäng (Bilaga A) är oförändrat; motorsviten 1465 gröna.

## Kvar – orsaker som inte är rättade

1. **Täta knippen av parallella rör** (KV/VV/VVC bredvid varandra): de flesta ankare är tvetydiga (40 av 69 på 2711) –
   ledaren korsar flera rör och listan säger inte vilket led som är vilket rör. Behöver knippesordningen (fas 8/10).
2. **Rörgeometrin är stor** (900–1000 m på ett A3-blad): sannolikt räknas linjer som inte är rör (radiatorer,
   symboler i rörpenna). Utan facit går det inte att avgöra; behöver ett facit för minst ett blad.
3. **V50-01-2811D är en demonteringsritning**: fas 1 flaggar nu bladet `purpose:demolition` (stämpeln
   DEMONTERINGSRITNING, `documents.yaml` `purpose_markers`). Mängdningen ska hoppa över sådana blad – kopplas in i
   ritningsflödet (fas 6–8).
4. **V50-01-4212-OMB är en rasterbild**: väg D (fas 11) – ingen geometri ur vektorvägen.
5. Motorns egen OCR-hjälp (RapidOCR PP-OCRv6) kan inte laddas ned i sandlådan (modelscope.cn nås inte); T5 och
   motorns linjetext fungerar ändå.
