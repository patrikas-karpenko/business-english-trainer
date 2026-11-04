"""Loads the lesson content (content/level1_lessons_1-12.json) and offers lookups.

The JSON file is the single source of truth for lessons, phrases and cards.
Regexes in it are already escaped for json.load, so they compile as they are.
"""
from __future__ import annotations

import json
import random
import re
from functools import lru_cache
from pathlib import Path

CONTENT_PATH = Path(__file__).resolve().parent.parent / "content" / "level1_lessons_1-12.json"


@lru_cache(maxsize=1)
def data() -> dict:
    with open(CONTENT_PATH, encoding="utf-8") as f:
        return json.load(f)


def lessons() -> list[dict]:
    return data()["lessons"]


def lesson(lesson_id: str) -> dict | None:
    return next((l for l in lessons() if l["lesson_id"] == lesson_id), None)


def drill(les: dict, drill_no: int) -> dict:
    return next(d for d in les["drills"] if d["drill_no"] == drill_no)


@lru_cache(maxsize=1)
def _cards() -> dict[str, dict]:
    """phrase_id -> card (meet / fill_variants / use_variants / grade_with), plus lesson_id."""
    out = {}
    for les in lessons():
        for card in drill(les, 1).get("cards", []):
            out[card["phrase_id"]] = {**card, "lesson_id": les["lesson_id"]}
    return out


def card(phrase_id: str) -> dict:
    return _cards()[phrase_id]


def all_phrase_ids() -> list[str]:
    return list(_cards().keys())


def phrases_up_to(lesson_id: str) -> list[dict]:
    """Phrases from this lesson and every earlier one (for min_course_phrases)."""
    out = []
    for les in lessons():
        out += les["phrases"]
        if les["lesson_id"] == lesson_id:
            break
    return out


def answer_key_lines(les: dict, prefix: str) -> list[str]:
    return [a for a in les["answer_key"] if a.lower().startswith(prefix.lower())]


# ---------------------------------------------------------------- card variables
VAR_RE = re.compile(r"<([A-Z]+)>")


def fill_vars(text: str, values: dict[str, str]) -> str:
    return VAR_RE.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def pick_vars(rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random
    return {name: rng.choice(options) for name, options in data()["card_variables"].items()}
