# Content library

Everything the runtime may use is here, and everything is versioned in git.

| File | Used by | Status |
|---|---|---|
| `competency_graph.json` | mastery engine (prerequisites), roadmap matching, checkpoints | NIPUN-anchored, **team-authored**; prerequisite edges need education-mentor review |
| `activities.json` | planner (the only source of activities) | team-authored templates; `reviewed: true` = team review only |
| `practice_items.json` | parent session item bank | team-authored; same caveat |
| `probes.json` | 2-minute teacher probes | team-authored |

## `reviewed` means what?

`reviewed: true` currently marks **team review**, not mentor sign-off. Before a real pilot:

1. The education mentor reviews each activity's steps, materials and reassessment item.
2. The mentor reviews the prerequisite edges in the graph (the riskiest content: a wrong edge sends
   a group to the wrong sub-skill).
3. Change the `source_doc` field to the reviewed source (e.g. "TEJASVI Grade 2 p.42, reviewed by …").

The runtime never invents activities or items; if nothing reviewed matches a gap, it serves the
generic gap-practice template and the plan card says so.

## Adding content

- New checkpoint: add to the graph with `prereqs`, `misconceptions`, `assess_via`; then add at least
  one activity and 3 practice items, or the group will get the generic template.
- New activity: must list `checkpoint_ids` (the first id is the group key it is chosen for), and a
  reassessment item; run `python -c "from app.services.content import get_content; get_content()"`
  from `backend/` to validate the JSON.
