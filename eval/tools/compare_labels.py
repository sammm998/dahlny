"""Jämför en källas lästa text med facit labels.json (SPEC Bilaga A.4).

    python eval/tools/compare_labels.py rader.json eval/projects/arjang_tvatthall/expected/labels.json

Varje facitetikett klassas som: exakt rad, exakt i längre rad, teckenförväxling (O/0, Z/2, S/5, B/8, I/1),
förväxling i längre rad eller saknas. Förväxlingar räknas INTE som rätt i acceptansmåttet (SPEC 11.2) – de
redovisas för att visa var läsningen är nära.
"""

from __future__ import annotations

import collections
import json
import sys
from typing import Any

# Sidindex (0-baserat, som motorn) per ritningsnummer i Bilaga A
SHEET = {"W-50-1-1000": "1", "W-53-1-0900": "2", "W-50-8-1000": "3"}
CONFUSIONS = str.maketrans({"O": "0", "Z": "2", "S": "5", "B": "8", "I": "1", "L": "1", "Q": "0", "D": "0"})


def norm(text: str) -> str:
    return " ".join(text.split()).upper()


def canon(text: str) -> str:
    return norm(text).translate(CONFUSIONS).replace(" ", "")


def classify(label: str, texts: list[str], tokens: collections.Counter[str]) -> str:
    t = norm(label)
    if t in texts:
        return "exakt rad"
    if t in tokens or (" " in t and any(t in x for x in texts)):
        return "exakt i längre rad"
    if any(canon(x) == canon(t) for x in texts) or any(canon(tok) == canon(t) for tok in tokens):
        return "teckenförväxling"
    if any(canon(t) in canon(x) for x in texts):
        return "förväxling i längre rad"
    return "saknas"


def compare(rows: dict[str, Any], facit: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for drawing in facit["drawings"]:
        texts = [norm(r["text"]) for r in rows[SHEET[drawing["drawing_no"]]]["rows"]]
        tokens = collections.Counter(tok for t in texts for tok in t.split())
        counts: collections.Counter[str] = collections.Counter()
        details = []
        for label in drawing["labels"]:
            kind = classify(label["text"], texts, tokens)
            counts[kind] += 1
            if kind != "exakt rad":
                near = [x for x in texts if canon(label["text"]) in canon(x)][:2]
                details.append({"kind": kind, "text": label["text"], "near": near})
        summary[drawing["drawing_no"]] = {
            "facit": len(drawing["labels"]),
            "counts": dict(counts),
            "details": details,
        }
    return summary


def main(rows_path: str, facit_path: str) -> None:
    with open(rows_path, encoding="utf-8") as fh:
        rows = json.load(fh)
    with open(facit_path, encoding="utf-8") as fh:
        facit = json.load(fh)
    for drawing_no, result in compare(rows, facit).items():
        print("==", drawing_no, result["facit"], result["counts"])
        for d in result["details"]:
            print("   ", d["kind"], repr(d["text"]), d["near"])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
