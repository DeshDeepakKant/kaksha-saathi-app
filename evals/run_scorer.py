"""Reading/pronunciation scorer evaluation against human-labelled ASR transcripts.

    python evals/run_scorer.py

Labels are word-level: for each target item, the human judgement (correct | close | wrong |
omitted). We report agreement (Cohen's κ) and the confusion matrix — the number that matters
is κ, because the scorer must agree with a teacher, not with itself.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.speech.scorer import score_read  # noqa: E402

CASES = [
    {"id": "v01", "targets": ["कमल", "घर", "कल"], "transcript": "कमल घर कल",
     "labels": ["correct", "correct", "correct"]},
    {"id": "v02", "targets": ["कमल", "घर", "कल"], "transcript": "कलम घर कल",
     "labels": ["close", "correct", "correct"]},
    {"id": "v03", "targets": ["का", "कि", "की"], "transcript": "का कि",
     "labels": ["correct", "correct", "omitted"]},
    {"id": "v04", "targets": ["का", "कि", "की"], "transcript": "का कु की",
     "labels": ["correct", "wrong", "correct"]},
    {"id": "v05", "targets": ["12"], "transcript": "बारह", "labels": ["correct"]},
    {"id": "v06", "targets": ["52"], "transcript": "पचास", "labels": ["wrong"]},
    {"id": "v07", "targets": ["ग", "श", "ण"], "transcript": "ग स न",
     "labels": ["correct", "close", "close"]},
    {"id": "v08", "targets": ["राम का घर"], "transcript": "राम का घर",
     "labels": ["correct"]},
    {"id": "v09", "targets": ["राम का घर"], "transcript": "राम घर",
     "labels": ["wrong"]},
    {"id": "v10", "targets": ["कमल"], "transcript": "", "labels": ["omitted"]},
]


def kappa(pairs: list[tuple[str, str]]) -> float:
    labels = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    n = len(pairs)
    if n == 0:
        return 1.0
    po = sum(1 for a, b in pairs if a == b) / n
    pe = sum((sum(1 for a, _ in pairs if a == l) / n) * (sum(1 for _, b in pairs if b == l) / n) for l in labels)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def main() -> dict:
    pairs, rows = [], []
    for c in CASES:
        r = score_read(c["targets"], c["transcript"])
        judged = [i.judged for i in r.items]
        # pad if the scorer emitted fewer/more items than labelled (should not happen)
        judged = (judged + ["omitted"] * len(c["labels"]))[: len(c["labels"])]
        for t, g, p in zip(c["targets"], c["labels"], judged):
            pairs.append((g, p))
        rows.append({"id": c["id"], "labels": c["labels"], "judged": judged,
                     "accuracy": round(r.accuracy, 3)})
    agree = sum(1 for a, b in pairs if a == b) / len(pairs)
    report = {"date": date.today().isoformat(), "items": len(pairs), "agreement": round(agree, 3),
              "kappa": round(kappa(pairs), 3), "cases": rows}
    out = ROOT / "evals/reports" / f"scorer-{report['date']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"# Scorer eval — {report['items']} labelled items, {report['date']}\n")
    print(f"- exact agreement **{report['agreement']}**, Cohen's κ **{report['kappa']}**")
    for r in rows:
        if r["labels"] != r["judged"]:
            print(f"  {r['id']}: labelled {r['labels']} → judged {r['judged']}")
    return report


if __name__ == "__main__":
    main()
