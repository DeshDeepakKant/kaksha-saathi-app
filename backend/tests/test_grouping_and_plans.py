from app.services.content import get_content
from app.services.grouping import group_class
from app.services.plan_templates import template_plan, render_group


def _statuses():
    content = get_content()
    kids = {i: {cp: "on_track" for cp in content.checkpoints} for i in range(1, 11)}
    for i in range(1, 5):  # 4 children fail borrowing only
        kids[i].update({"N.G2.sub_2digit_borrow": "needs_intervention",
                        "N.G2.sub_2digit_no_borrow": "on_track"})
    for i in range(5, 8):  # 3 children fail place value too -> root at place value
        kids[i].update({"N.G2.sub_2digit_borrow": "needs_intervention",
                        "N.G2.sub_2digit_no_borrow": "needs_intervention",
                        "N.G2.place_value_99": "needs_intervention"})
    return kids


def test_groups_by_foundational_root():
    g = group_class(get_content(), _statuses())
    keys = {x.key: len(x.members) for x in g.groups}
    assert keys.get("N.G2.sub_2digit_borrow") == 4
    assert keys.get("N.G2.place_value_99") == 3


def test_unassessed_not_grouped():
    g = group_class(get_content(), _statuses(), needs_assessment={9})
    assert 9 in g.unassessed
    assert all(9 not in x.members for x in g.groups)


def test_template_plan_uses_reviewed_activity():
    content = get_content()
    groups = [{"key": "N.G2.sub_2digit_borrow", "checkpoint_id": "N.G2.sub_2digit_borrow",
               "title_hi": "उधार", "chapter": "Subtraction", "members": [1, 2], "status": "needs_intervention"}]
    p = template_plan(groups, content)
    g = p["groups"][0]
    assert g["activity_id"] in content.activities
    assert g["reassessment"]["ask_hi"]
    out = render_group({"teacher_script_hi": "बच्चे {R1, R2} अभ्यास करें"},
                       {1: {"first_name": "राहुल"}, 2: {"first_name": "मीना"}})
    assert out["teacher_script_hi"] == "बच्चे राहुल, मीना अभ्यास करें"
