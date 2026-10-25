"""Extraction evaluation for teacher voice notes.

    python evals/run_extraction.py                  # deterministic rules extractor (no API key)
    python evals/run_extraction.py --mode rules
    python evals/run_extraction.py --mode live      # calls Claude (needs ANTHROPIC_API_KEY)

Metrics (micro-averaged over notes):
  * child-event F1 over (roll, checkpoint, result) triples
  * wrong-child attribution rate = predicted events whose roll is not in the label set
  * absence recall / precision
Writes evals/reports/extraction-<mode>-<date>.json and prints a markdown summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ai import rules  # noqa: E402
from app.services.content import get_content  # noqa: E402


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, other: "Counts") -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


class _Child:
    def __init__(self, roll: int, name: str):
        self.roll_no, self.first_name = roll, name


def load_roster() -> list[_Child]:
    """Demo class 2A from the seeds (fictional). Eval never needs a live DB."""
    from app.seed import NAMES_2A
    return [_Child(i, n) for i, n in enumerate(NAMES_2A, start=1)]


def predict_rules(transcript: str, roster: list[_Child], content) -> dict:
    cps = list(content.checkpoints.values())
    data = rules.extract_note_rules(transcript, roster, cps)
    out = {"absent": set(), "events": set(), "unknown_child": 0}
    for c in data["children"]:
        roll = c.get("roll")
        if roll is None:
            out["unknown_child"] += 1
            continue
        if c["status"] == "absent":
            out["absent"].add(roll)
        else:
            out["events"].add((roll, c["checkpoint_id"], c["result"]))
    return out


def predict_live(transcript: str, roster: list[_Child], content) -> dict:
    """Same call the API makes, without persistence (school_id=None)."""
    from app.ai import features
    from app.db import SessionLocal
    from app.models.tables import Base, engine

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        p = features.extract_note(db, school_id=None, transcript=transcript,
                                  roster=[(c.roll_no, c.first_name) for c in roster],
                                  checkpoint_ids=[c.id for c in content.checkpoints.values()],
                                  content=content, subject="numeracy")
        name_to_roll = {c.first_name: c.roll_no for c in roster}
        out = {"absent": set(), "events": set(), "unknown_child": 0}
        for c in p.payload.get("children", []):
            roll = name_to_roll.get(c["name"])
            if roll is None:
                out["unknown_child"] += 1
                continue
            if c["status"] == "absent":
                out["absent"].add(roll)
            elif c.get("checkpoint_id"):
                out["events"].add((roll, c["checkpoint_id"], c["result"]))
        return out
    finally:
        db.close()


def run(mode: str) -> dict:
    content = get_content()
    roster = load_roster()
    labels = [json.loads(line) for line in (ROOT / "evals/golden/notes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    predict = predict_rules if mode == "rules" else predict_live
    ev = Counts()
    absent = Counts()
    unknown = 0
    rows = []
    for case in labels:
        pred = predict(case["transcript"], roster, content)
        unknown += pred["unknown_child"]
        gold = {(r, cp, res) for r, cp in case["wrong"] for res in ("incorrect",)}
        gold |= {(r, cp, "correct") for r, cp in case["correct"]}
        hit = pred["events"] & gold
        case_counts = Counts(len(hit), len(pred["events"] - gold), len(gold - pred["events"]))
        ev.add(case_counts)
        g_abs = set(case["absent"])
        absent.add(Counts(len(g_abs & pred["absent"]), len(pred["absent"] - g_abs), len(g_abs - pred["absent"])))
        rows.append({"id": case["id"], "tp": case_counts.tp, "fp": case_counts.fp, "fn": case_counts.fn,
                     "predicted": sorted(list(pred["events"])), "gold": sorted(list(gold)),
                     "absent_pred": sorted(pred["absent"]), "absent_gold": sorted(g_abs)})
    report = {
        "mode": mode, "date": date.today().isoformat(), "notes": len(labels),
        "child_event": {"precision": round(ev.precision, 3), "recall": round(ev.recall, 3),
                        "f1": round(ev.f1, 3), "tp": ev.tp, "fp": ev.fp, "fn": ev.fn},
        "absence": {"precision": round(absent.precision, 3), "recall": round(absent.recall, 3),
                    "f1": round(absent.f1, 3)},
        "wrong_child_events": sum(1 for r in rows for e in r["predicted"] if e[0] not in
                                  {g[0] for g in r["gold"]}),
        "unresolved_names": unknown,
        "cases": rows,
    }
    out = ROOT / "evals/reports" / f"extraction-{mode}-{report['date']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rules", "live"], default="rules")
    args = ap.parse_args()
    r = run(args.mode)
    ce = r["child_event"]
    print(f"# Extraction eval ({r['mode']}) — {r['notes']} notes, {r['date']}\n")
    print(f"- child-event precision **{ce['precision']}**, recall **{ce['recall']}**, F1 **{ce['f1']}**")
    print(f"- absence F1 **{r['absence']['f1']}**")
    print(f"- wrong-child events: {r['wrong_child_events']}  · unresolved names: {r['unresolved_names']}")
    misses = [c["id"] for c in r["cases"] if c["fn"] or c["fp"]]
    if misses:
        print(f"- notes with misses: {', '.join(misses)}")
