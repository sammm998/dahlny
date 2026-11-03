# Kom igång – VS-Kalkyl för kalkylatorn

VS-Kalkyl läser ett förfrågningsunderlag (teknisk beskrivning och ritningar) och tar fram ett förslag:
artikellista, mängdlista, avvikelser med frågor till konsulten, utkast till leverantörsförfrågningar och en fil att
klistra in i Prixel. **Allt är förslag.** Du granskar, rättar och godkänner – inget skickas och inget läggs in i
Prixel av sig självt.

## 1. Starta (en gång per dator)

Det här gör IT eller den som installerar:

```bash
make setup
```
```bash
make db-up
```
```bash
make migrate
```

API-nyckeln till AI-tjänsten läggs i filen `.env` (se `.env.example`), aldrig i ett mail eller ett dokument.
Ritningsmotorn (vvs_engine) installeras i en egen miljö; sökvägen anges i `VVS_ENGINE_CMD`.

## 2. Kör ett underlag

Lägg teknisk beskrivning och ritningar (PDF, gärna ZIP) i en mapp och kör:

```bash
cd backend && .venv/bin/python -m app.pipeline.demo ../MAPP_MED_UNDERLAG ../projekt/MITT_PROJEKT --register ../ARTIKELREGISTER.csv
```

Det tar några minuter (ritningarna läses bit för bit). En andra körning på samma underlag går snabbt och kostar
inget, eftersom AI-svaren sparas.

Exemplet Årjäng (tvätthall) körs med:

```bash
make demo
```

## 3. Granska

Starta gränssnittet och öppna <http://localhost:8000/ui/>:

```bash
VSK_PROJECTS_DIR=projekt make dev
```

Vyerna, i den ordning du normalt går igenom dem:

| Vy | Vad du gör |
| --- | --- |
| **Projekt** | Kontrollera projektnamn, beställare och uppdragsnummer, och att alla dokument kom med. |
| **TB-lista** | Varje post ur den tekniska beskrivningen med beteckning, produkt, art.nr/RSK och antal. Klicka på *sida N* för att se stället i TB:n. Klicka på ett antal för att rätta det. Barnposter (blandare, Ballofix) står indragna under sin huvudpost. |
| **Avvikelser** | Kritiska först. Varje avvikelse har en föreslagen fråga till konsulten. Sätt status *resolved* eller *ignored* när du tagit ställning. |
| **Ritning** | Mätt, otilldelat, tvetydigt och *utanför entreprenadgräns* per blad. Öppna den markerade PDF:en för att se varje rör i färg. |
| **Mängdlista** | Rörmeter per system × material × dimension, isolering och böjar (uppskattning). Rätta meter eller material direkt. Rader med flaggan `UNKNOWN_LABEL_TOKEN` har en kod som konsulten måste förklara. |
| **Matchning** | Varje post mot artikelregistret: *stock*, *virtual*, *request* (prisförfrågan) eller *uncertain* (granska). Byt utfall i listan om förslaget är fel. |
| **Förfrågningar** | Ett mailutkast (.eml) per leverantör med raderna, de citerade kraven och frågorna. Ladda ned, öppna i Outlook eller Gmail, läs och skicka själv. |
| **Export** | `prixel.xlsx` och `prixel_urklipp.txt` för Prixel, `mangdlista.xlsx`, `markerad.pdf`, `artikellista.xlsx`. |

Varje rättning sparas med vem, när, gammalt och nytt värde.

## 4. Vad du ska titta extra på

- **Otilldelad rörlängd** (rött i den markerade PDF:en): rör som ingen etikett når. Mängdlistan räknar dem inte.
  Står andelen över 2 % på ett blad finns avvikelsen `UNASSIGNED_PIPE`.
- **Tvetydigt** (orange): två etiketter gör anspråk på samma rör. Ofta en gräns mellan två dimensioner.
- **Utanför entreprenadgräns** (lila): rör förbi `ENTR. GRÄNS`. De ingår inte i mängden men redovisas.
- **Lodräta längder** står som "ej bestämd" när ritningen saknar höjder. Lägg till dem själv.
- **Rördelar** är en uppskattning ur ritade riktningsändringar.
- **Okänd leverantör**: rader där registret saknar leverantör. Välj leverantör innan mailet skickas.

## 5. Det som inte är påslaget än

Detta väntar på svar från Dahl (se SPEC kap 14) och står tydligt i gränssnittet:

- Export direkt till Prixel via API (fråga 1). Använd Excel eller urklipp.
- Utkast direkt i Outlook eller Gmail (fråga 3). Använd .eml-filen.
- Leverantörernas mailadresser (fråga 4). Mottagaren är tom i utkasten.
- Inloggning med SSO (fråga 6) och uppladdning direkt i gränssnittet.
- Skannade ritningar och foton läses bara delvis (etiketter, inte rörlängder).
