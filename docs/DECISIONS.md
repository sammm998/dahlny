# Beslut under bygget

Beslut som togs utan att vänta på användaren (uppdrag 2026-11-03: "stanna inte för frågor"). Varje rad: vad, varför,
hur det ändras. Användarens egna beslut står i SPEC och markeras "beslut användare".

| Datum | Område | Beslut | Skäl |
| --- | --- | --- | --- |
| 2026-11-03 | AI-budget | Budgeten 50 USD för hela bygget räknas på `ai_run` efter `2026-11-03 04:20:18 UTC` (25,35 USD var redan förbrukat i tidigare omgångar). `eval/tools/ai_spend.py` visar läget. | Uppdraget säger "logga i AIRun, stanna vid 50". |
| 2026-11-03 | S01 DN75 (beslut användare) | En etikett med dimension som pekar på en återvändsgren eller symbolen i dess ände, där grenen saknar annan etikett, ger grenen etikettens dimension – före `junction_dn_over_symbol_labels`. | Användarens beslut. |
| 2026-11-03 | Pilspetsar (beslut användare) | Pilspetsar ritade med rörpennan räknas aldrig som rörlängd. | Användarens beslut. |
| 2026-11-03 | CONFLICTING_REQUIREMENTS | Konflikter läses av T3 (v3, fältet `conflicts`) i samma anrop som posterna, inte av en egen uppgift. Båda citaten måste stå ordagrant i sektionen. | Samma text skickas redan per sektion; inga extra anrop. Deterministisk konfliktläsning går inte att göra generell. |
| 2026-11-03 | DECIDE_WITH_CLIENT | Bara meningar där ett valord (typ, val, fabrikat …, `rules.yaml`) står före samrådsfrasen. | Samråd om utförande (märkning, ljud) är inget produktval och ger annars brus. |
| 2026-11-03 | Barnposter | Barnposter bara ur "Härtill:"/"Tillbehör:"-listor och bara när punkten namnger en produkt (fabrikat, typ, art.nr, RSK) eller ett antal. Övriga punkter är krav på huvudposten. | SPEC 6.2 nämner "Härtill"; generiska punkter (plastvattenlås, konsoler) är inte egna inköpsrader i facit. |
| 2026-11-03 | Barnposters antal | Ett antal i barnposten måste stå i dess egen rad; annars ärver den huvudpostens antal. | SPEC 6.2 steg 5 (antal valideras mot källan). |
| 2026-11-03 | Artikelregister (ÖPPEN FRÅGA 2) | Import känner igen kolumner på rubrik och tar en egen mappning; lagerstatusord i `articles.yaml`. Testregistret är påhittat och märkt TESTDATA. | Formatet är okänt; ingen gissning om fältens betydelse utöver rubriken. |
| 2026-11-03 | Tillbehörskrav | Bara tillbehör som TB säger att produkten levereras med (samma mening som "levereras med", "försedd med" …) krävs av artikeln. | Ett tillbehör som är en egen Härtill-post (plastvattenlås) köps separat. |
| 2026-11-03 | Matchning i utvärdering | `make eval` matchar mot registret i minnet (`MemoryArticleSource`, samma trigramlikhet som pg_trgm) så att TESTDATA aldrig skrivs in i databasens register. | Produktionsregistret får inte blandas med testdata. |
| 2026-11-03 | Prixel (ÖPPEN FRÅGA 1) | Kolumnordning enligt A.6; fält med okänd betydelse (pris, nettopris, rabatt %, prisstatus) lämnas tomma med rubriken "(okänt)". API-exporten är en stub. | Gissa inte Prixels fält. |
| 2026-11-03 | Mail (ÖPPEN FRÅGA 3, 4) | Utkast som .eml (öppnas i Outlook som osänt utkast via `X-Unsent: 1`, i Gmail och andra som vanligt mail). Mottagaradress lämnas tom tills leverantörsregistret finns. Ingen kod skickar mail. | Inget får lämna systemet utan människa (CLAUDE.md). |
| 2026-11-03 | T9 | Mallen är grunden; T9 får formulera om den, men texten används bara om varje beteckning finns med, inga tal saknar källa och kraven står ordagrant. | SPEC 6.6 steg 2: inga påhittade värden. |
| 2026-11-03 | TESTDATA TS501 | TS501 (FURO 40512H) ligger hos Furhoffs som beställningsvara i testregistret. | FURO är Furhoffs varumärke; DoD fas 5 förutsätter att TS501 efterfrågas hos Furhoffs. |
