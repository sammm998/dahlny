# Facit – Tvätthall Årjäng

Skapat i fas 0 ur SPEC.md Bilaga A och avstämt mot TB-texten (alla RSK, art.nr och beteckningar
finns ordagrant i `11_5_Teknisk_Beskrivning_VS.pdf`). JSON-filerna är källan – redigera dem direkt.
Schemat finns i `backend/app/evaluation/facit.py` och valideras av `make test` och `make eval`.

| Fil | Innehåll | Bilaga |
| --- | --- | --- |
| `spec_items.json` | Förväntade SpecItems inkl. barnposter (`parent_designation`) | A.1 |
| `project_rules.json` | Generella krav (`ProjectRule`) | A.2 |
| `deviations.json` | Förväntade avvikelser, med fas då de ska hittas | A.3 |
| `labels.json` | Etiketter per ritning, tecken-exakt, med förväntad tolkning | A.4 |
| `symbols.json` | Symbolantal och legendtabeller som ska läsas in | A.5 |

Kända oklarheter (inte gissade – se `notes` i filerna):
- SPEC 13 fas 2 säger "26 rader i facit", tabell A.1 har 28 numrerade rader + rörraden.
