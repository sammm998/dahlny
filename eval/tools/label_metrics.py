"""Etikettläsning mot facit labels.json (SPEC Bilaga A.4): exakt, flaggad, felläst, saknas – per källa.

    python eval/tools/label_metrics.py labels.json KÄLLA=rader.json [KÄLLA=rader.json ...]

`rader.json` har formen {sidindex: {"rows": [{"text", "bbox", ...}]}} – både vvs_engine-dumpen
(eval/tools/vvs_engine_text_rows.py) och T5 (python -m app.drawings.labels) skriver den.

Per facitetikett:
- exakt     – texten finns tecken för tecken (flerordstext även som grannord på samma rad eller raden under);
- flaggad   – inte exakt, men en närliggande läsning finns och den är markerad för granskning
              (T5: read_confidence < 0,8 eller needs_review; vvs_engine: '?' i texten eller okända tecken);
- felläst   – hela etiketten är läst men med fel tecken (samma efter förväxlingarna O/0, Z/2, S/5,
              B/8, I/1), och läsningen är INTE flaggad – ett tyst fel;
- ofullständig – bara en del av etiketten är läst (minst 3 tecken), inte flaggad – också ett tyst fel;
- saknas    – ingen närliggande läsning.
En läsning som själv är en annan facitetikett räknas inte som felläsning av den här.
Facit saknar positioner, så matchningen sker på text per ritning – en etikett som förekommer flera gånger
räknas som läst om någon förekomst lästs.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from typing import Any

SHEET = {"W-50-1-1000": "1", "W-53-1-0900": "2", "W-50-8-1000": "3"}
CONFUSIONS = str.maketrans({"O": "0", "Z": "2", "S": "5", "B": "8", "I": "1", "L": "1", "Q": "0", "D": "0"})
MIN_CONF = 0.8
KINDS = ("exakt", "flaggad", "felläst", "ofullständig", "saknas")


def norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).upper().split())


def canon(text: str) -> str:
    return norm(text).translate(CONFUSIONS).replace(" ", "")


def flagged(row: dict[str, Any]) -> bool:
    if "read_confidence" in row:
        return row["read_confidence"] < MIN_CONF or "needs_review" in (row.get("flags") or [])
    return "?" in row.get("text", "") or bool(row.get("unknown_chars"))


def _words_adjacent(label: str, rows: list[dict[str, Any]]) -> bool:
    """Flerordstext läst som separata rader: orden i ordning, tätt intill på samma linje eller raden under."""
    words = norm(label).split()
    if len(words) < 2:
        return False
    by_word = {w: [r for r in rows if norm(r["text"]) == w and r.get("bbox")] for w in words}
    if any(not v for v in by_word.values()):
        return False

    def chain(i: int, prev: dict[str, Any]) -> bool:
        if i == len(words):
            return True
        for r in by_word[words[i]]:
            pb, rb = prev["bbox"], r["bbox"]
            h = max(pb[3] - pb[1], rb[3] - rb[1], 1.0)
            beside = 0 <= rb[0] - pb[2] <= 3 * h
            same_line = abs((pb[1] + pb[3]) / 2 - (rb[1] + rb[3]) / 2) <= 0.6 * h and beside
            # eller på raden under, i samma spalt (tvåradig text som "ANSL." över "TRYCKLUFT")
            next_line = 0 <= rb[1] - pb[3] <= 1.0 * h and abs(rb[0] - pb[0]) <= 2 * h
            if (same_line or next_line) and chain(i + 1, r):
                return True
        return False

    return any(chain(1, r) for r in by_word[words[0]])


def classify(label: str, rows: list[dict[str, Any]], facit_texts: set[str]) -> tuple[str, str | None]:
    t = norm(label)
    texts = [norm(r["text"]) for r in rows]
    if t in texts or any(t in x.split() for x in texts) or (" " in t and any(t in x for x in texts)):
        return "exakt", t
    if _words_adjacent(label, rows):
        return "exakt", t
    near = []
    for r, x in zip(rows, texts, strict=True):
        if x in facit_texts:
            continue  # en annan etikett läst rätt är ingen felläsning av den här
        cx, ct = canon(x), canon(t)
        if cx == ct or ct in cx or (len(cx) >= 3 and cx in ct):
            near.append(r)
    if not near:
        return "saknas", None
    best = min(near, key=lambda r: (not flagged(r), abs(len(canon(r["text"])) - len(canon(t)))))
    if flagged(best):
        return "flaggad", best["text"]
    whole = canon(best["text"]) == canon(t) or canon(t) in canon(best["text"])
    return ("felläst" if whole else "ofullständig"), best["text"]


def measure(rows_by_sheet: dict[str, Any], facit: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"per_drawing": {}, "total": dict.fromkeys(KINDS, 0)}
    for drawing in facit["drawings"]:
        rows = (rows_by_sheet.get(SHEET[drawing["drawing_no"]]) or {}).get("rows", [])
        facit_texts = {norm(lab["text"]) for lab in drawing["labels"]}
        counts = dict.fromkeys(KINDS, 0)
        details = []
        for lab in drawing["labels"]:
            kind, got = classify(lab["text"], rows, facit_texts)
            counts[kind] += 1
            out["total"][kind] += 1
            if kind != "exakt":
                details.append({"facit": lab["text"], "kind": kind, "read": got})
        out["per_drawing"][drawing["drawing_no"]] = {
            "facit": len(drawing["labels"]),
            **counts,
            "details": details,
        }
    return out


def main(argv: list[str]) -> int:
    with open(argv[0], encoding="utf-8") as fh:
        facit = json.load(fh)
    for spec in argv[1:]:
        name, path = spec.split("=", 1)
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
        res = measure(rows, facit)
        tot = res["total"]
        n = sum(tot.values())
        print(f"## {name}: exakt {tot['exakt']}/{n}, " + ", ".join(f"{k} {tot[k]}" for k in KINDS[1:]))
        meta = rows.get("_meta") or {}
        if meta:
            ai = "på" if meta.get("ai") else "av"
            cost = meta.get("cost_usd")
            cost_txt = f", AI-kostnad {cost:.2f} USD" if isinstance(cost, int | float) else ""
            print(f"   tid {meta.get('seconds')} s, AI {ai}, OCR {meta.get('ocr')}{cost_txt}")
        for no, d in res["per_drawing"].items():
            print(f"   {no}: exakt {d['exakt']}/{d['facit']}, " + ", ".join(f"{k} {d[k]}" for k in KINDS[1:]))
            for x in d["details"]:
                if x["kind"] in ("felläst", "ofullständig"):
                    print(f"      {x['kind'].upper()} {x['facit']!r} lästes {x['read']!r}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1:]))
