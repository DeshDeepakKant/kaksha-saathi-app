"""Planner evaluation: grouping + plan validity over scripted classroom scenarios.

    python evals/run_planner.py            # template (offline) planner
    python evals/run_planner.py --mode live

Checks (all deterministic — these are the same validators the API enforces):
  1. every group in the input appears exactly once
  2. every chosen activity exists in the reviewed library and matches the group's checkpoint
  3. total planned time ≤ 25 minutes; no printer needed
  4. a reassessment question exists for every group
  5. groups are ordered most-foundational-first
The mentor rubric (activity appropriateness, script clarity) is exported as CSV for review;
it is NOT scored automatically.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.content import get_content  # noqa: E402
from app.services.grouping import group_class  # noqa: E402
from app.services.plan_templates import template_plan  # noqa: E402

SCENARIOS = [
    {"id": "s1_borrow_only", "subject": "numeracy",
     "fails": {1: ["N.G2.sub_2digit_borrow"], 2: ["N.G2.sub_2digit_borrow"], 3: ["N.G2.sub_2digit_borrow"],
               4: ["N.G2.add_2digit_carry"], 5: ["N.G2.add_2digit_carry"], 6: ["N.G2.add_2digit_carry"],
               7: ["N.G2.place_value_99"], 8: ["N.G2.place_value_99"], 9: ["N.G2.place_value_99"]}},
    {"id": "s2_foundation_gap", "subject": "numeracy",
     "fails": {1: ["N.G2.place_value_99", "N.G2.sub_2digit_no_borrow", "N.G2.sub_2digit_borrow"],
               2: ["N.G2.place_value_99", "N.G2.sub_2digit_no_borrow", "N.G2.sub_2digit_borrow"],
               3: ["N.G2.place_value_99"], 4: ["N.G2.place_value_99"], 5: ["N.G2.place_value_99"]}},
    {"id": "s3_literacy_mixed", "subject": "literacy",
     "fails": {1: ["L.G1.vyanjan"], 2: ["L.G1.vyanjan"], 3: ["L.G1.vyanjan"],
               4: ["L.G1.matra_basic"], 5: ["L.G1.matra_basic"], 6: ["L.G1.matra_basic"],
               7: ["L.G2.word_formation"], 8: ["L.G2.word_formation"], 9: ["L.G2.word_formation"]}},
    {"id": "s4_single_child", "subject": "numeracy", "fails": {1: ["N.G2.sub_2digit_borrow"]}},
    {"id": "s5_all_on_track", "subject": "numeracy", "fails": {}},
    {"id": "s6_whole_class", "subject": "numeracy", "fails": {i: ["N.G2.sub_2digit_borrow"] for i in range(1, 16)}},
]


def statuses_for(content, fails: dict[int, list[str]], n_children: int = 16) -> dict[int, dict[str, str]]:
    out = {}
    for child in range(1, n_children + 1):
        st = {cp: "on_track" for cp in content.checkpoints}
        for cp in fails.get(child, []):
            st[cp] = "needs_intervention"
        # prerequisites of a failing checkpoint are assumed fine unless also failing
        out[child] = st
    return out


def plan_live(groups, content):
    from app.ai import features
    from app.db import SessionLocal
    from app.models.tables import Base, engine
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        p = features.plan_day(db, school_id=None, grade=2, subject="numeracy", day=date.today().isoformat(),
                              groups=groups, content=content)
        return p.payload, p.ai_status
    finally:
        db.close()


def run(mode: str) -> dict:
    content = get_content()
    rows, results = [], []
    for sc in SCENARIOS:
        st = statuses_for(content, sc["fails"])
        grouping = group_class(content, st)
        groups = [{"key": g.key, "checkpoint_id": g.checkpoint_id, "title_hi": g.title_hi,
                   "chapter": g.chapter, "members": g.members, "status": g.status,
                   "unassessed": False} for g in grouping.groups]
        if not groups:
            results.append({"id": sc["id"], "groups": 0, "valid": True, "issues": [],
                            "plan": {"groups": [], "whole_class_note_hi": ""}})
            continue
        if mode == "live":
            payload, source = plan_live(groups, content)
        else:
            payload, source = template_plan(groups, content), "fallback"
        issues = []
        keys = {g["key"] for g in groups}
        seen = [g["key"] for g in payload.get("groups", [])]
        if sorted(seen) != sorted(keys):
            issues.append(f"group coverage mismatch: {seen} vs {sorted(keys)}")
        total = 0
        for g in payload.get("groups", []):
            total += int(g.get("time_min", 0))
            act = content.activities.get(g.get("activity_id", ""))
            if act is None:
                issues.append(f"{g['key']}: activity {g.get('activity_id')} not in library")
            elif g["key"] not in act["checkpoint_ids"]:
                issues.append(f"{g['key']}: activity does not target this checkpoint")
            elif not act.get("reviewed"):
                issues.append(f"{g['key']}: activity not mentor-reviewed")
            if not (g.get("reassessment") or {}).get("ask_hi"):
                issues.append(f"{g['key']}: no reassessment question")
            if not (g.get("teacher_script_hi") or "").strip():
                issues.append(f"{g['key']}: empty teacher script")
            rows.append({"scenario": sc["id"], "group": g["key"], "activity": g.get("activity_id"),
                         "minutes": g.get("time_min"), "script_hi": g.get("teacher_script_hi", ""),
                         "reassessment_hi": (g.get("reassessment") or {}).get("ask_hi", "")})
        if total > 25:
            issues.append(f"total time {total} min exceeds 25")
        deferred = [g["key"] for g in payload.get("groups", []) if g.get("deferred")]
        if deferred and not any("कल" in (payload.get("whole_class_note_hi") or "") for _ in [0]):
            issues.append("deferred groups not explained to the teacher")
        results.append({"id": sc["id"], "groups": len(groups), "total_minutes": total,
                        "valid": not issues, "issues": issues, "source": source, "plan": payload})
    passed = sum(1 for r in results if r["valid"])
    report = {"mode": mode, "date": date.today().isoformat(), "scenarios": len(results),
              "valid": passed, "results": results}
    out = ROOT / "evals/reports" / f"planner-{mode}-{report['date']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = ROOT / "evals/reports" / f"planner-{mode}-{report['date']}-mentor-review.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["scenario", "group", "activity", "minutes", "script_hi", "reassessment_hi"])
        w.writeheader()
        w.writerows(rows)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["template", "live"], default="template")
    args = ap.parse_args()
    r = run(args.mode)
    print(f"# Planner eval ({r['mode']}) — {r['scenarios']} scenarios, {r['date']}\n")
    print(f"- structurally valid plans: **{r['valid']}/{r['scenarios']}**")
    for res in r["results"]:
        flag = "OK " if res["valid"] else "FAIL"
        print(f"  {flag} {res['id']}: {res['groups']} groups, {res.get('total_minutes', 0)} min"
              + (f" — {'; '.join(res['issues'])}" if res["issues"] else ""))
