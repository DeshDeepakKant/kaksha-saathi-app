"""Reviewed parent content: tips per misconception and 5-minute home versions of class activities.

Stub: the content agent fills `content/misconception_tips.json` and `content/activity_home.json`
and this loader (see docs/parent_insights_contract.md).
"""
from __future__ import annotations


def get_tip(misconception_id: str) -> dict | None:
    return None


def home_version(activity_id: str) -> dict | None:
    return None


def all_tips() -> dict:
    return {}
