# Fas 11 – Bilaga A som skanning och foto (2026-11-03)

Ritningarna i Bilaga A (`12_4_Ritningar_VS.pdf`) renderades med `eval/tools/raster_variants.py`:
- **skanning:** 200 dpi gråskala med brus;
- **simulerat foto:** 200 dpi, trapetsperspektiv 3 %, skugga mot ena hörnet, brus, oskärpa, JPEG.

Båda lästes med T5 (`python -m app.drawings.labels … --pages 2,3,4`) och mättes mot A.4 med
`eval/tools/label_metrics.py`. Motorn kördes på skanningen.

| Variant | Etiketter A.4 (88) | Tysta fel | AI-kostnad | Tid | Rörmeter | Skala |
| --- | --- | --- | --- | --- | --- | --- |
| Vektor-PDF (referens) | 88 exakt | 0 | – (cache) | – | 98,3 m bekräftat | verifierad |
| 200 dpi-skanning | 88 exakt | 0 | 3,10 USD | 1006 s | **0 m** | NONE (blockerad) |
| Simulerat foto | 88 exakt | 0 | 3,09 USD | 1098 s | ej körd (samma väg) | – |

**Slutsats:**
- **Etiketterna** (vision + OCR) klarar raster och foto lika bra som vektor på Bilaga A.
- **Rörmetern** saknas helt. vvs_engine har ingen rastervektorisering (väg D/E): linjerna i en bild blir inga
  rör, och skalan kan inte bestämmas. Skalan blockeras därför i stället för att gissas (SPEC 11.2).
- **DoD fas 11 (±5 % rörmeter efter granskning)** är **inte** uppfyllt.
- **Nästa steg:** förbehandling (uppräta perspektiv, binarisera), linjeextraktion (Hough/LSD eller
  segmentering), skala ur skalstock och ritat mått, sedan samma graf och tilldelning som vektorvägen. Lägg till
  halvmanuell spårning i UI:t för det som inte hittas.
