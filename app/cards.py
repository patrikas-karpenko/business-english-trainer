"""Three-stage phrase cards (Meet -> Fill -> Use) scheduled with FSRS.

One phrase = one FSRS item per learner. The stage shown depends on the item:
  * no item yet                         -> Meet (study only; creates the item)
  * fewer than 2 successful review days -> Fill (gapped sentence; hints fade)
  * otherwise                           -> Use  (reply to a message in your own words)
A wrong answer resets the successful days, so the phrase goes back to Fill.
Variants rotate (never one of the last two shown) and <DAY>/<TIME>/... are random.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from fsrs import Card, Rating, Scheduler

from . import content, db
from .grading import auto_rating, check_fill, matches_any

SCHEDULER = Scheduler(enable_fuzzing=False)
RATINGS = {"Again": Rating.Again, "Hard": Rating.Hard, "Good": Rating.Good, "Easy": Rating.Easy}
OWNED_AFTER = timedelta(days=7)


def stage_for(row: dict | None) -> str:
    if row is None:
        return "meet"
    return "fill" if len(row["success_days"]) < 2 else "use"


def _pick_variant(row: dict | None, stage: str, n: int, rng: random.Random) -> int:
    recent = (row or {}).get("recent_variants", {}).get(stage, [])
    options = [i for i in range(n) if i not in recent[-2:]] or list(range(n))
    unseen = [i for i in options if i not in recent]
    return rng.choice(unseen or options)


def build(user_id: int, phrase_id: str, rng: random.Random | None = None) -> dict:
    """Everything a template needs to show the next card for this phrase."""
    rng = rng or random.Random()
    c = content.card(phrase_id)
    row = db.get_card(user_id, phrase_id)
    stage = stage_for(row)
    view = {"phrase_id": phrase_id, "stage": stage, "meet": c["meet"], "lesson_id": c["lesson_id"]}
    values = content.pick_vars(rng)
    if stage == "fill":
        v = _pick_variant(row, "fill", len(c["fill_variants"]), rng)
        fv = c["fill_variants"][v]
        level = min(row["fill_reviews"], 2)
        view.update(variant=v, context=content.fill_vars(fv["context"], values),
                    segments=_segments(content.fill_vars(fv["text"], values), fv["gaps"],
                                       fv["first_letter_hints"], level),
                    hint_level=level)
    elif stage == "use":
        v = _pick_variant(row, "use", len(c["use_variants"]), rng)
        uv = c["use_variants"][v]
        view.update(variant=v, who=content.fill_vars(uv["context_who"], values),
                    message=content.fill_vars(uv["context_message"], values) if uv["context_message"] else None,
                    situation=content.fill_vars(uv["situation"], values) if uv["situation"] else None,
                    task=content.fill_vars(uv["task"], values))
    view["vars"] = values
    return view


def _segments(text: str, gaps: list[str], hints: list[str], level: int) -> list[dict]:
    """Split a fill sentence into text and gap pieces for the template."""
    out, pos = [], 0
    for i, g in enumerate(gaps):
        k = text.find(g, pos)
        out.append({"text": text[pos:k]})
        words = len(g.split())
        hint = hints[i] if level == 0 else (f"{words} word{'s' if words > 1 else ''}" if level == 1 else "")
        out.append({"gap": i, "size": max(len(g), 4), "hint": hint})
        pos = k + len(g)
    out.append({"text": text[pos:]})
    return out


def _new_row(phrase_id: str) -> dict:
    return {"phrase_id": phrase_id, "fsrs": Card().to_dict(), "due": db.iso(), "success_days": [],
            "fill_reviews": 0, "recent_variants": {}, "first_use_success_at": None, "owned": 0}


def _schedule(row: dict, rating: str, when: datetime) -> None:
    card, _ = SCHEDULER.review_card(Card.from_dict(row["fsrs"]), RATINGS[rating], review_datetime=when)
    row["fsrs"] = card.to_dict()
    row["due"] = card.due.isoformat()


def meet_done(user_id: int, phrase_id: str) -> None:
    """The learner has studied the Meet card: start the FSRS item (first Fill comes soon)."""
    if db.get_card(user_id, phrase_id):
        return
    row = _new_row(phrase_id)
    _schedule(row, "Good", db.now())
    db.save_card(user_id, row)


def answer(user_id: int, phrase_id: str, stage: str, variant: int, inputs: list[str], vars_: dict,
           response_ms: int | None) -> dict:
    """Grade a Fill or Use answer, update FSRS, return the result for the template."""
    c = content.card(phrase_id)
    row = db.get_card(user_id, phrase_id) or _new_row(phrase_id)
    when = db.now()
    if stage == "fill":
        fv = c["fill_variants"][variant]
        sentence = content.fill_vars(fv["text"], vars_)
        correct = check_fill(inputs, fv["gaps"], sentence, c["grade_with"])
        expected = sentence
        row["fill_reviews"] += 1
    else:
        correct = matches_any(c["grade_with"], inputs[0] if inputs else "")
        expected = None
    rating = auto_rating(correct, response_ms)
    _schedule(row, rating, when)
    today = when.date().isoformat()
    if correct:
        if today not in row["success_days"]:
            row["success_days"].append(today)
        if stage == "use":
            if not row["first_use_success_at"]:
                row["first_use_success_at"] = when.isoformat()
            elif when - datetime.fromisoformat(row["first_use_success_at"]) >= OWNED_AFTER:
                row["owned"] = 1
    else:
        row["success_days"] = []
    recent = row["recent_variants"].setdefault(stage, [])
    recent.append(variant)
    row["recent_variants"][stage] = recent[-4:]
    db.save_card(user_id, row)
    db.log_attempt(user_id, c["lesson_id"], 1, f"{phrase_id}:{stage}:{variant}", " | ".join(inputs),
                   {"correct": correct, "rating": rating}, response_ms=response_ms)
    return {"correct": correct, "rating": rating, "expected": expected, "frame": c["meet"]["frame"],
            "next_due": row["due"]}


def stats(user_id: int) -> dict:
    rows = db.card_rows(user_id)
    due_now = set(db.due_cards(user_id, limit=1000))
    by_stage = {"fill": 0, "use": 0}
    for r in rows:
        if r["phrase_id"] in due_now:
            by_stage["fill" if len(r["success_days"]) < 2 else "use"] += 1
    return {"introduced": len(rows), "owned": sum(r["owned"] for r in rows), "due": len(due_now),
            "due_fill": by_stage["fill"], "due_use": by_stage["use"], "total": len(content.all_phrase_ids())}
