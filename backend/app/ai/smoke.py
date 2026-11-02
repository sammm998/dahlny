"""Rökprov för fas 0: ett riktigt AI-anrop som loggas i AIRun.

    python -m app.ai.smoke [--task T0]

Avslutas med kod 0 om svaret validerades och kontrollsträngen ekades exakt, annars 1.
Oavsett utfall loggas försöket i ai_run (status ok / api_error / not_configured / ...).
"""

from __future__ import annotations

import argparse
import secrets
import sys

from sqlalchemy import select

from app.ai.client import AIClient, AIError
from app.ai.datatypes import ProviderError, ProviderNotConfigured
from app.ai.schemas.t0 import PingResult
from app.db.models import AIRun
from app.db.session import make_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="T0")
    args = parser.parse_args(argv)

    nonce = f"VS-{secrets.token_hex(4).upper()}-K1-15"
    factory = make_session_factory()
    client = AIClient(factory, use_cache=False)
    exit_code = 1
    try:
        result = client.structured(args.task, f"Kontrollsträng: {nonce}", PingResult)
        exact = result.echo == nonce
        print(f"Svar: echo={result.echo!r} exakt={exact} confidence={result.confidence}")
        exit_code = 0 if exact else 1
    except (ProviderError, ProviderNotConfigured, AIError) as exc:
        print(f"AI-anropet misslyckades: {exc}", file=sys.stderr)

    with factory() as session:
        run = session.scalars(select(AIRun).order_by(AIRun.created_at.desc()).limit(1)).first()
    if run is None:
        print("Ingen AIRun loggades – fel i loggningen", file=sys.stderr)
        return 1
    print(
        f"AIRun {run.id}: step={run.step} model={run.model} served={run.served_model} status={run.status} "
        f"tokens_in={run.tokens_in} tokens_out={run.tokens_out} cost_usd={run.cost_estimate} "
        f"latency_ms={run.latency_ms}"
    )
    if run.error:
        print(f"  fel: {run.error}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
