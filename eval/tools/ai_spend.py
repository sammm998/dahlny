"""AI-kostnad för bygget (docs/DECISIONS.md): summa i ai_run efter baslinjen, per uppgift.

python eval/tools/ai_spend.py [--since 2026-11-03T04:20:18Z] [--cap 50]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app.db.session import get_engine  # noqa: E402

BASELINE = "2026-11-03T04:20:18Z"
CAP_USD = 50.0


def spent(since: str = BASELINE) -> tuple[float, list[tuple[str, int, float]]]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT step, count(*), coalesce(sum(cost_estimate), 0) FROM ai_run "
                "WHERE created_at > CAST(:since AS timestamptz) GROUP BY step ORDER BY 3 DESC"
            ),
            {"since": since},
        ).all()
    per = [(str(r[0]), int(r[1]), float(r[2])) for r in rows]
    return sum(p[2] for p in per), per


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default=BASELINE)
    ap.add_argument("--cap", type=float, default=CAP_USD)
    args = ap.parse_args()
    total, per = spent(args.since)
    for step, n, usd in per:
        print(f"{step:<8} {n:6d} anrop  {usd:8.2f} USD")
    print(f"Totalt {total:.2f} av {args.cap:.2f} USD")
    return 1 if total >= args.cap else 0


if __name__ == "__main__":
    raise SystemExit(main())
