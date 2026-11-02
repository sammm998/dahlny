# VS-Kalkyl

Internt system för automatiserad offertberedning av VS-entreprenader: läser teknisk beskrivning och
ritningar, bygger en spårbar artikellista, mängdar rör, stämmer av handlingarna mot varandra, matchar mot
Dahls artikelregister och tar fram Prixel-export och leverantörsförfrågningar. Specifikation: [SPEC.md](SPEC.md).
Konventioner för utveckling: [CLAUDE.md](CLAUDE.md).

## Kom igång

```bash
cp .env.example .env          # fyll i ANTHROPIC_API_KEY för riktiga AI-anrop
make setup                    # Python 3.12-venv i backend/.venv
make db-up                    # PostgreSQL 16 + PostGIS + pg_trgm, Redis
make migrate
make check                    # lint + mypy --strict + tester
make dev                      # http://localhost:8000/health
```

Indata för testprojektet (Bilaga A) är konfidentiella och ligger inte i repot – se [eval/README.md](eval/README.md).

## Struktur

```
backend/app/config/   models.yaml, thresholds.yaml, label_grammar.yaml, reference_tables.yaml, settings.py
backend/app/db/       SQLAlchemy-modeller (SPEC 5) + Alembic-migreringar
backend/app/ai/       AIClient, adaptrar (anthropic, openai, google-stub, fake), scheman, promptar
backend/app/api/      REST-endpoints
backend/app/jobs/     Celery
backend/tests/        pytest (riktig Postgres)
eval/                 facit, run_eval.py, rapporter
frontend/             granskningsgränssnitt (från fas 3)
```

## Status

| Fas | Innehåll | Status |
| --- | --- | --- |
| 0 | Repo, Docker, DB, CI, AIClient med loggning och cache, config-filer, facit | Klar (se nedan) |
| 1 | Intag, sidklassning, titelblock, ritningsförteckning | – |

**Fas 0 – kvar att verifiera med riktig nyckel:** `make test` är grönt (55 tester, mot PostgreSQL 16 +
PostGIS 3.4). AI-anropet loggas i `ai_run` även när det misslyckas. Ett *lyckat* skarpt anrop kräver
`ANTHROPIC_API_KEY`; kör `make ai-smoke`.
