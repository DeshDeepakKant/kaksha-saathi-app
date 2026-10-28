"""Reviewed parent content: tips per misconception and 5-minute home versions of class activities.

Loaded once from `content/misconception_tips.json` and `content/activity_home.json` (see
docs/parent_insights_contract.md). Lookups never raise: an unknown id, or a missing/broken file,
gives None so a parent screen simply shows less. Only `reviewed` tips are handed to parents.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

from app.config import get_settings

log = logging.getLogger(__name__)


def _load(filename: str, key: str) -> dict[str, dict]:
    path = get_settings().content_dir / filename
    try:
        with path.open(encoding="utf-8") as f:
            rows = json.load(f).get(key, [])
    except (OSError, ValueError, AttributeError) as e:
        log.warning("parent content %s not loaded: %s", filename, e)
        return {}
    return {r["id"]: r for r in rows if isinstance(r, dict) and r.get("id")}


@lru_cache
def _tips() -> dict[str, dict]:
    return _load("misconception_tips.json", "tips")


@lru_cache
def _home() -> dict[str, dict]:
    return _load("activity_home.json", "activities")


def get_tip(misconception_id: str | None, reviewed_only: bool = True) -> dict | None:
    """The parent tip for a misconception id, or None (unknown id, or not yet reviewed)."""
    tip = _tips().get(misconception_id or "")
    if tip is None or (reviewed_only and not tip.get("reviewed")):
        return None
    return dict(tip)


def home_version(activity_id: str | None) -> dict | None:
    """The 5-minute home version of a class activity, or None."""
    act = _home().get(activity_id or "")
    return dict(act) if act is not None else None


def all_tips() -> dict:
    """Every tip by misconception id, reviewed or not (for tests and content tooling)."""
    return {k: dict(v) for k, v in _tips().items()}
