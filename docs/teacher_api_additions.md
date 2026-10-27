# Teacher app v2: API contract (additive)

All routes are under `/v1`, teacher JWT, scoped to the teacher's school. Existing payloads only gain
fields. `status` values everywhere: `on_track`, `needs_practice`, `needs_intervention`, `not_started`.
A class "has done" a topic for a child when that child is `on_track`; `needs_practice` and
`needs_intervention` are "in progress / struggling"; `not_started` means no evidence yet.

## Setup (backend/app/api/setup.py, services/coverage.py)
| Route | Body / query | Returns |
|---|---|---|
| `POST /classes` | `{grade:1-8, section:str, label?:str}` | `{id,label,grade,section,children:0,consented:0}` |
| `GET /classes/{id}/subjects` | | `[{key,name_en,name_hi,builtin,topics}]` built-ins (`numeracy` Maths, `literacy` Hindi) always first |
| `POST /subjects` | `{name:str, name_hi?:str}` | `{key,name_en,name_hi,builtin:false}` (key = slug, <= 16 chars, unique per school) |
| `GET /classes/{id}/syllabus?subject=` | | `{subject,confirmed,version,source,children,chapters:[{chapter,totals,topics:[{checkpoint_id,title_hi,title_en,custom,nipun_ref,position,total,assessed,counts:{on_track,needs_practice,needs_intervention,not_started},pct_done}]}],totals:{topics,counts}}` |
| `POST /classes/{id}/syllabus` | `{subject,source,items:[{checkpoint_id?,custom_title?,custom_title_hi?,chapter?,position}]}` | same as GET (new roadmap version). Items with no `checkpoint_id` become custom topics. |
| `POST /classes/{id}/syllabus/topics` | `{subject,chapter,title,title_hi?}` | the created topic (same shape as a topic above) |
| `DELETE /classes/{id}/syllabus/topics/{checkpoint_id}?subject=` | | same as GET |

Existing and reused: `POST /classes/{id}/children`, `/children/bulk`, `PATCH /children/{id}/consent`,
`POST /classes/{id}/roadmap/draft` (index photo), `GET /classes/{id}/roster`.
Custom topics are registered as real checkpoints (id `C<school>-<n>`, no prerequisites, no practice
items), so tap marking, board, profile and plans work on them.

## Core (backend/app/api/teacher.py, services/ledger.py)
- `POST /captures/{id}/confirm`: body gains `skipped:int=0`, `edited:int=0`. `reject_all` already exists.
- `GET /ai_activity`: gains `edited`, `skipped`, `cost_inr_today`, `checks_7d`, `plans_7d`; `rejected` now
  includes skipped proposals.
- `GET /classes/{id}/moved?subject=&hours=24` -> `{since, moves:[{child_id,first_name,roll_no,direction:"improved|slipped|changed",from:{key,title_hi,title_en}|null,to:{key,title_hi,title_en}|null}]}`
  (`null` = on track / no group).
- `GET /children/{id}/timeline?subject=&weeks=6` -> `{points:[{week_end,on_track,needs_practice,needs_intervention,assessed,total}]}`
- `GET /classes/{id}/attendance?day=` -> `{day,absent_rolls:[int],present:int}`.
- Board response gains `absent:[child_id]`; groups, plan groups, profile items and
  `/content/checkpoints` gain `nipun_ref`.
- `plan.assess_first.members` becomes `[{id,first_name}]` like every other group (was roll ints).

## Flutter shared pieces
- `CaptureSheet(classId, subject, presetCheckpointId?, presetChildIds?, presetChildren?)`.
- `SyllabusScreen(classId, subject, className)`.
- `Api.i.postQueued(path, body)` returns `{'queued': true}` when parked offline; `Api.i.pendingCount` is a
  `ValueNotifier<int>`; `Api.i.flushOutbox()`; `Api.i.plan(classId, subject, {force, forDate})`.
- Put new API wrappers inline (`Api.i.get/postJson`) or in your own `lib/api_<area>.dart` extension; never edit
  another agent's file.
