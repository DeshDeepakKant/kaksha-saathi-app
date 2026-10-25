"""Spoken-name → child resolution. Ambiguity is surfaced to the teacher, never guessed."""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from app.models.tables import Child


@dataclass
class Resolution:
    child: Child | None
    reason: str  # matched | fuzzy | ambiguous | no_roster_match
    candidates: list[Child]


def resolve_names(name: str, children: list[Child], threshold: float = 86) -> Resolution:
    name = (name or "").strip()
    if not name:
        return Resolution(None, "no_roster_match", [])
    exact = [c for c in children if c.first_name == name]
    if len(exact) == 1:
        return Resolution(exact[0], "matched", exact)
    if len(exact) > 1:
        return Resolution(None, "ambiguous", exact)
    scored = sorted(((fuzz.ratio(name, c.first_name), c) for c in children), key=lambda x: -x[0])
    if not scored or scored[0][0] < threshold:
        return Resolution(None, "no_roster_match", [])
    top = [c for s, c in scored if s >= threshold]
    if len(top) > 1 and scored[0][0] - scored[1][0] < 5:
        return Resolution(None, "ambiguous", top[:4])
    return Resolution(top[0], "fuzzy", top)
