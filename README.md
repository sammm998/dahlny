# VS-Kalkyl

Internt system för automatiserad offertberedning av VS-entreprenader: läser teknisk beskrivning och
ritningar, bygger en spårbar artikellista, mängdar rör, stämmer av handlingarna mot varandra, matchar mot
Dahls artikelregister och tar fram Prixel-export och leverantörsförfrågningar. Specifikation: [SPEC.md](SPEC.md).
Konventioner för utveckling: [CLAUDE.md](CLAUDE.md).

## Kom igång

```bash
cp .env.example .env          # fyll i DAHLNY_ANTHROPIC_API_KEY för riktiga AI-anrop
make setup                    # Python 3.12-venv i backend/.venv
make db-up                    # PostgreSQL 16 + PostGIS + pg_trgm, Redis
make migrate
make check                    # lint + mypy --strict + tester
make dev                      # http://localhost:8000/health
```

Indata för testprojektet (Bilaga A) är konfidentiella och ligger inte i repot – se [eval/README.md](eval/README.md).

### Anthropic-nyckeln

VS-Kalkyl läser nyckeln från `DAHLNY_ANTHROPIC_API_KEY` i första hand och `ANTHROPIC_API_KEY` som reserv, och
skickar den uttryckligen till klienten. I Claude Codes molnmiljö är `ANTHROPIC_API_KEY` och `ANTHROPIC_BASE_URL`
reserverade av Claude Code och når inte sessionen – lägg nyckeln som `DAHLNY_ANTHROPIC_API_KEY` i miljöns
inställningar och starta en ny session. API-adressen är `https://api.anthropic.com` och läses aldrig från
`ANTHROPIC_BASE_URL` (ändra vid behov med `DAHLNY_ANTHROPIC_BASE_URL`). Kontrollera utan att visa värdet:

```bash
test -n "$DAHLNY_ANTHROPIC_API_KEY" && echo finns || echo saknas
```

## Struktur

```
backend/app/config/   models.yaml, thresholds.yaml, label_grammar.yaml, reference_tables.yaml, settings.py
backend/app/db/       SQLAlchemy-modeller (SPEC 5) + Alembic-migreringar
backend/app/ai/       AIClient, adaptrar (anthropic, openai, google-stub, fake), scheman, promptar
backend/app/ingest/  filtyp, ZIP, format per sida, rendering, lagring
backend/app/classify/ sidklassning (regler + T1), titelblock (textlager + T2), ritningsförteckning
backend/app/pipeline/ fas 1-flödet (python -m app.pipeline.phase1)
backend/app/drawings/ DrawingQuantitySource, vvs_engine-adapter, skal-/token-/täckningskontroller
backend/app/tb/      TB-hjälp (måttnormalisering)
backend/app/api/      REST-endpoints
backend/app/jobs/     Celery
backend/tests/        pytest (riktig Postgres)
eval/                 facit, run_eval.py, rapporter
frontend/             granskningsgränssnitt (från fas 3)
```

## Status

| Fas | Innehåll | Status |
| --- | --- | --- |
| 0 | Repo, Docker, DB, CI, AIClient med loggning och cache, config-filer, facit | Klar; `make ai-smoke` grön |
| 1 | Intag, sidklassning, titelblock, ritningsförteckning | Klar: Bilaga A **23/23** med T1/T2 (9/23 med `--no-ai`), AI-kostnad ≈ 0,03 USD |
| 6–8 | Ritningsmängder: integrera `vvs_engine` (SPEC 6.4.7) | Adapter + kontroller klara; T5 88/88 på Bilaga A; T5-etiketter i motorn på Dahlvvvs-grenen `claude/t5-labels` (bekräftade meter 58,46 → 82,55) – se [docs/t5_bilaga_a.md](docs/t5_bilaga_a.md) |

Fas 1 på Bilaga A (`make eval`): TB, ritningsförteckning, format och uppdragsnummer läses deterministiskt.
Planernas typ, ritningsnummer, skala och uppdragsnummer står bara i titelblock ritade som linjer och läses
med vision (T2). Tester gör aldrig riktiga AI-anrop; `make eval` gör det när `DAHLNY_ANTHROPIC_API_KEY` finns.

Ritningsmotorn: installera `sammm998/Dahlvvvs/engine` i en egen miljö och sätt `VVS_ENGINE_CMD`, t.ex.

```bash
python3.12 -m venv ~/.venvs/vvs-engine && ~/.venvs/vvs-engine/bin/pip install -e ../Dahlvvvs/engine
export VVS_ENGINE_CMD=~/.venvs/vvs-engine/bin/vvs-takeoff
```
