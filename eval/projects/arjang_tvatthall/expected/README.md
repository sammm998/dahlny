# Facit – Tvätthall Årjäng

Skapat i fas 0 ur SPEC.md Bilaga A och avstämt mot TB-texten (alla RSK, art.nr och beteckningar
finns ordagrant i `11_5_Teknisk_Beskrivning_VS.pdf`). JSON-filerna är källan – redigera dem direkt.
Schemat finns i `backend/app/evaluation/facit.py` och valideras av `make test` och `make eval`.

| Fil | Innehåll | Bilaga |
| --- | --- | --- |
| `pages.json` | Dokument- och sidtyper, ritningsnr, skala, uppdragsnr per sida, förteckningens rader, fas 1-avvikelser (titelblocken granskade visuellt) | A + fas 1 |
| `spec_items.json` | Förväntade SpecItems inkl. barnposter (`parent_designation`) | A.1 |
| `project_rules.json` | Generella krav (`ProjectRule`) | A.2 |
| `deviations.json` | Förväntade avvikelser, med fas då de ska hittas | A.3 |
| `labels.json` | Etiketter per ritning, tecken-exakt, med förväntad tolkning | A.4 |
| `symbols.json` | Symbolantal och legendtabeller som ska läsas in | A.5 |

Beslut:
- 28 rader enligt A.1 (kylaggregaten rad 27–28 ingår) plus rörraden – SPEC 13 fas 2 uppdaterad 2026-11-02.
- B201B-motsägelsen (A.3 nr 2) jämförs efter normalisering av blanksteg och enhet
  (`backend/app/tb/dimensions.py`): TB skriver `300x300x192` i löptext och `300 x 300 x 400mm` i tabellen.
