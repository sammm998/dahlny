# CLAUDE.md – VS-Kalkyl

**Den fullständiga specifikationen är [`SPEC.md`](SPEC.md). Läs den innan du ändrar något.**
Bygg i fasordningen i SPEC 13. En fas är klar först när dess *Definition of Done* är uppfylld med tester.
Punkter markerade **[ÖPPEN FRÅGA]** (SPEC 14) får inte gissas: bygg adapter + stub och fråga användaren.

## Kommandon

```bash
make setup        # backend/.venv (Python 3.12) + beroenden
make db-up        # PostgreSQL 16 + PostGIS + pg_trgm, Redis (Docker)
make migrate      # Alembic upgrade head
make check        # lint + mypy --strict + pytest (= CI)
make test         # bara pytest (kräver databas; TEST_DATABASE_URL)
make eval         # utvärdering mot facit → eval/reports/eval.md
make ai-smoke     # ett riktigt AI-anrop (T0) som loggas i ai_run
```

## Kodkonventioner (SPEC 12 + 2)

- Python 3.12, typannoteringar överallt, `ruff` + `mypy --strict`. Frontend: `eslint` + `tsc --noEmit`.
- **Inga AI-anrop utanför `backend/app/ai/`.** Allt går via `AIClient.structured(task_id, inputs, schema)`,
  som validerar med Pydantic, gör retry med felet bifogat, eskalerar enligt `config/models.yaml`, cachar på
  `(task_id, model, prompt_version, input_hash)` och loggar varje försök i `ai_run`.
- Promptar är versionerade filer: `backend/app/ai/prompts/{task_id}/v{n}.md`. Ändra inte en publicerad
  version – skapa `v{n+1}`.
- **Inga magiska tal** – trösklar i `config/thresholds.yaml`, modellval i `models.yaml`, grammatik i
  `label_grammar.yaml`, standardtabeller i `reference_tables.yaml`. Projektets legend går före standardtabeller.
- Deterministiskt först (geometri, längd, skala, summor, regler i vanlig kod); AI bara där tolkning krävs.
- Varje värde har `source_refs` (dokument, sida, bbox, metod, modell, konfidens). Ingen tyst gissning:
  under tröskel → flagga för granskning. Fail loud.
- Inget lämnar systemet (mail, Prixel) utan mänskligt godkännande.
- Svenska i UI, genererade texter, felmeddelanden och kommentarer; engelska i identifierare (namn på
  moduler, klasser, funktioner, kolumner).
- Schemaändringar: ändra `app/db/models.py`, generera migrering med
  `alembic revision --autogenerate`, och låt `tests/test_db.py::test_migrations_match_models` vara grön.

## Data och sekretess

- Repot är **publikt**. Förfrågningsunderlag (TB, ritningar) checkas **aldrig** in – `eval/projects/*/input/`
  är gitignorerad utom `MANIFEST.json` (sha256). Facit (`expected/*.json`) checkas in.
- Hemligheter bara i miljövariabler (`.env`, se `.env.example`).

## Anthropic-API (nuvarande modeller)

- `temperature` stöds inte (400) – determinism via cache. Tvingat `tool_choice` ger 400 på opus-5-5/
  sonnet-5-5/fable-5-1 – använd `output_config.format` (json_schema). Sätt `effort` per uppgift.
- SDK 2.x använder `httpx2`; testa adaptrar med `httpx2.MockTransport`.
