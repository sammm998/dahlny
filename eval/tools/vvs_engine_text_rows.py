"""Dumpar all text som vvs_engine läser per sida (streckad text och textlager), som JSON.

Körs med motorns egen Python, som har vvs_engine installerat:

    <motorns venv>/bin/python -I eval/tools/vvs_engine_text_rows.py ritningar.pdf rader.json
"""

from __future__ import annotations

import json
import sys

from vvs_engine.pdf.extract import extract_document  # type: ignore[import-not-found]
from vvs_engine.text.vector_text import vector_text_rows  # type: ignore[import-not-found]


def main(pdf_path: str, out_path: str) -> None:
    doc = extract_document(pdf_path)
    out: dict[int, dict[str, object]] = {}
    for i in range(len(doc.pages)):
        page = doc.pages[i]
        result = vector_text_rows(page)
        out[page.info.index] = {
            "rows": [
                {
                    "text": r.text,
                    "bbox": [round(v, 1) for v in r.bbox],
                    "angle": round(r.angle),
                    "height": round(r.height, 2),
                    "source": r.source,
                    "unknown_chars": r.unknown_chars,
                    "layer": r.layer,
                }
                for r in result.rows
            ],
            "rejected": [r.text for r in result.rejected_rows][:200],
        }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print({k: len(v["rows"]) for k, v in out.items()})  # type: ignore[arg-type]


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
