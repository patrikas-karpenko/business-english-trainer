"""Commerce English — Business English Trainer (pilot).

Run:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import json
import os
import re

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from starlette.middleware.sessions import SessionMiddleware

from . import cards, content, db, grading, llm

try:  # .env is optional
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

BASE = os.path.dirname(__file__)
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_app):
    db.init()
    yield


app = FastAPI(title="Commerce English", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SECRET_KEY", "dev-only-change-me"),
                   max_age=60 * 60 * 24 * 180, same_site="lax")
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))

DRILL_NAMES = {0: "Warm-up", 1: "Phrase cards", 2: "Reading", 3: "Write-in", 4: "Chat", 5: "Email", 6: "Revision"}
LESSON_REVIEW_LIMIT = 5      # older due cards mixed into a lesson's Drill 1
CHECKPOINT_REVIEW_LIMIT = 15  # Lesson 12 has no new phrases: a longer review




# ---------------------------------------------------------------- template helpers
def highlight(text: str, parts: list[str]) -> Markup:
    """Wrap each fixed part of a phrase in <mark> (case-insensitive, in order)."""
    out, pos = "", 0
    for p in parts:
        m = re.compile(re.escape(p), re.IGNORECASE).search(text, pos)
        if not m:
            continue
        out += str(escape(text[pos:m.start()])) + f"<mark>{escape(m.group(0))}</mark>"
        pos = m.end()
    return Markup(out + str(escape(text[pos:])))


def frame(text: str) -> Markup:
    """'Could you [send it] by [Thursday]?' -> fixed parts marked, slots grey."""
    pieces = re.split(r"\[([^\]]+)\]", text)
    html = ""
    for i, p in enumerate(pieces):
        if not p:
            continue
        if i % 2:
            html += f'<span class="slot">{escape(p)}</span>'
        elif re.search(r"[A-Za-z]", p):
            lead = p[: len(p) - len(p.lstrip())]
            trail = p[len(p.rstrip()):]
            html += f"{lead}<mark>{escape(p.strip())}</mark>{trail}"
        else:
            html += p
    return Markup(html)


def bold(text: str) -> Markup:
    return Markup(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", str(escape(text))))


templates.env.filters.update(highlight=highlight, frame=frame, bold=bold)
templates.env.globals.update(DRILL_NAMES=DRILL_NAMES)


def render(request: Request, name: str, **ctx):
    uid = request.session.get("user_id")
    ctx.setdefault("user", db.user(uid) if uid else None)
    return templates.TemplateResponse(request, name, ctx)


def current_user(request: Request) -> int | None:
    uid = request.session.get("user_id")
    return uid if uid and db.user(uid) else None


def need_login(request: Request):
    return RedirectResponse("/login", status_code=303)


def unlocked(lesson_id: str, progress: dict) -> bool:
    if os.environ.get("UNLOCK_ALL") == "1":
        return True
    ids = [l["lesson_id"] for l in content.lessons()]
    i = ids.index(lesson_id)
    return i == 0 or bool(progress.get(ids[i - 1], {}).get("lesson_completed_at"))


def current_lesson(progress: dict) -> dict:
    for les in content.lessons():
        if not progress.get(les["lesson_id"], {}).get("lesson_completed_at"):
            return les
    return content.lessons()[-1]


def to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- login
@app.get("/", include_in_schema=False)
def root(request: Request):
    return RedirectResponse("/today" if current_user(request) else "/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", need_code=bool(os.environ.get("PILOT_CODE")), error=None)


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, name: str = Form(...), code: str = Form("")):
    name = name.strip()[:40]
    if os.environ.get("PILOT_CODE") and code.strip() != os.environ["PILOT_CODE"]:
        return render(request, "login.html", need_code=True, error="That code doesn't match. Check the code you were sent.")
    if not name:
        return render(request, "login.html", need_code=bool(os.environ.get("PILOT_CODE")), error="Enter your name.")
    request.session["user_id"] = db.get_or_create_user(name)
    return RedirectResponse("/today", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------- main tabs
@app.get("/today", response_class=HTMLResponse)
def today(request: Request):
    uid = current_user(request)
    if not uid:
        return need_login(request)
    progress = db.all_progress(uid)
    les = current_lesson(progress)
    done = sum(1 for p in progress.values() if p.get("lesson_completed_at"))
    return render(request, "today.html", tab="today", lesson=les, p=db.get_progress(uid, les["lesson_id"]),
                  stats=cards.stats(uid), lessons_done=done, lessons_total=len(content.lessons()),
                  pastes=db.paste_count(uid))


@app.get("/lessons", response_class=HTMLResponse)
def lessons_page(request: Request):
    uid = current_user(request)
    if not uid:
        return need_login(request)
    progress = db.all_progress(uid)
    rows = [{"lesson": l, "p": progress.get(l["lesson_id"], {}), "open": unlocked(l["lesson_id"], progress)}
            for l in content.lessons()]
    return render(request, "lessons.html", tab="lessons", rows=rows)


@app.get("/me", response_class=HTMLResponse)
def me(request: Request):
    uid = current_user(request)
    if not uid:
        return need_login(request)
    return render(request, "me.html", tab="me", stats=cards.stats(uid), llm_on=llm.enabled())


# ---------------------------------------------------------------- phrase cards
def _next_card_id(uid: int, lesson_id: str | None, reviewed: int) -> str | None:
    if lesson_id:
        les = content.lesson(lesson_id)
        new = [c["phrase_id"] for c in content.drill(les, 1).get("cards", [])
               if db.get_card(uid, c["phrase_id"]) is None]
        if new:
            return new[0]
        limit = LESSON_REVIEW_LIMIT if les["phrases"] else CHECKPOINT_REVIEW_LIMIT
        if reviewed >= limit:
            return None
    elif reviewed >= 20:
        return None
    due = db.due_cards(uid, limit=1)
    return due[0] if due else None


@app.get("/cards", response_class=HTMLResponse)
def cards_page(request: Request):
    uid = current_user(request)
    if not uid:
        return need_login(request)
    return render(request, "cards.html", tab="cards", first=_card_fragment_ctx(uid, None, 0))


def _card_fragment_ctx(uid: int, lesson_id: str | None, reviewed: int) -> dict:
    pid = _next_card_id(uid, lesson_id, reviewed)
    ctx = {"lesson_id": lesson_id or "", "reviewed": reviewed, "card": None}
    if pid:
        ctx["card"] = cards.build(uid, pid)
    return ctx


@app.get("/cards/next", response_class=HTMLResponse)
def cards_next(request: Request, lesson: str = "", reviewed: int = 0):
    uid = current_user(request)
    if not uid:
        return HTMLResponse("", status_code=401)
    return render(request, "partials/card.html", **_card_fragment_ctx(uid, lesson or None, reviewed))


@app.post("/cards/meet", response_class=HTMLResponse)
def cards_meet(request: Request, phrase_id: str = Form(...), lesson: str = Form(""), reviewed: int = Form(0)):
    uid = current_user(request)
    if not uid:
        return HTMLResponse("", status_code=401)
    cards.meet_done(uid, phrase_id)
    return render(request, "partials/card.html", **_card_fragment_ctx(uid, lesson or None, reviewed))


@app.post("/cards/answer", response_class=HTMLResponse)
async def cards_answer(request: Request):
    uid = current_user(request)
    if not uid:
        return HTMLResponse("", status_code=401)
    form = await request.form()
    stage = form.get("stage")
    if stage == "fill":
        inputs = [form.get(f"gap{i}", "") for i in range(int(form.get("n_gaps", 0)))]
    else:
        inputs = [form.get("reply", "")]
    pasted = to_int(form.get("pasted"), 0)
    vars_ = json.loads(form.get("vars") or "{}")
    result = cards.answer(uid, form["phrase_id"], stage, to_int(form.get("variant"), 0), inputs, vars_,
                          to_int(form.get("response_ms")))
    if pasted:
        db.log_attempt(uid, None, 1, "paste", "", pasted=pasted)
    return render(request, "partials/card_result.html", r=result, stage=stage, inputs=inputs,
                  lesson_id=form.get("lesson", ""), reviewed=to_int(form.get("reviewed"), 0) + 1,
                  meet=content.card(form["phrase_id"])["meet"])


# ---------------------------------------------------------------- lessons
def _lesson_or_404(request: Request, lesson_id: str):
    uid = current_user(request)
    if not uid:
        return None, None, need_login(request)
    les = content.lesson(lesson_id)
    if not les:
        return None, None, HTMLResponse("Lesson not found", status_code=404)
    if not unlocked(lesson_id, db.all_progress(uid)):
        return None, None, RedirectResponse("/lessons", status_code=303)
    return uid, les, None


@app.get("/lesson/{lesson_id}", response_class=HTMLResponse)
def lesson_page(request: Request, lesson_id: str):
    uid, les, bad = _lesson_or_404(request, lesson_id)
    if bad:
        return bad
    return render(request, "lesson.html", tab="lessons", lesson=les, p=db.get_progress(uid, lesson_id))


@app.get("/lesson/{lesson_id}/drill/{n}", response_class=HTMLResponse)
def drill_page(request: Request, lesson_id: str, n: int):
    uid, les, bad = _lesson_or_404(request, lesson_id)
    if bad:
        return bad
    if n not in DRILL_NAMES:
        return RedirectResponse(f"/lesson/{lesson_id}", status_code=303)
    d = content.drill(les, n)
    ctx = {"lesson": les, "d": d, "n": n}
    if n == 1:
        ctx["first"] = _card_fragment_ctx(uid, lesson_id, 0)
    if n == 4:
        ctx["turn"] = _turn_ctx(les, d, 0, 0)
    if n == 6:
        last = db.last_attempt(uid, lesson_id, 5, "email")
        ctx["draft"] = json.loads(last["response"]) if last else {"subject": "", "body": ""}
    return render(request, f"drill_{d['kind']}.html", **ctx)


@app.post("/lesson/{lesson_id}/drill/{n}/complete")
def drill_complete(request: Request, lesson_id: str, n: int):
    uid, les, bad = _lesson_or_404(request, lesson_id)
    if bad:
        return bad
    db.mark_drill_done(uid, lesson_id, n)
    if n == 3:
        return RedirectResponse(f"/lesson/{lesson_id}?session1=done", status_code=303)
    if n >= 6:
        return RedirectResponse(f"/lesson/{lesson_id}?finished=1", status_code=303)
    return RedirectResponse(f"/lesson/{lesson_id}/drill/{n + 1}", status_code=303)


@app.post("/lesson/{lesson_id}/drill/0", response_class=HTMLResponse)
async def warmup_submit(request: Request, lesson_id: str):
    uid, les, bad = _lesson_or_404(request, lesson_id)
    if bad:
        return bad
    form = await request.form()
    answers = [form.get(f"item{i}", "") for i in range(int(form.get("n_items", 0)))]
    instinct = form.get("instinct", "")
    if instinct:
        db.log_attempt(uid, lesson_id, 0, "instinct", instinct, pasted=to_int(form.get("pasted"), 0))
    if answers:
        db.log_attempt(uid, lesson_id, 0, "warmup", " | ".join(answers), pasted=to_int(form.get("pasted"), 0))
    return render(request, "partials/warmup_result.html", lesson=les, key=content.answer_key_lines(les, "Warm-up"),
                  instinct=instinct)


@app.post("/lesson/{lesson_id}/drill/3", response_class=HTMLResponse)
async def writein_submit(request: Request, lesson_id: str):
    uid, les, bad = _lesson_or_404(request, lesson_id)
    if bad:
        return bad
    form = await request.form()
    d = content.drill(les, 3)
    results = []
    for item in d["items"]:
        ans = form.get(f"item{item['item_no']}", "")
        results.append({"no": item["item_no"], "answer": ans, "ok": grading.check_gap(ans, item["accept"]),
                        "accept": item["accept"]})
    score = sum(r["ok"] for r in results)
    db.log_attempt(uid, lesson_id, 3, "write_in", json.dumps([r["answer"] for r in results]),
                   {"score": score, "of": len(results)}, pasted=to_int(form.get("pasted"), 0))
    return render(request, "partials/writein_result.html", lesson=les, results=results, score=score)


# ---------------------------------------------------------------- chat simulator
def _turn_ctx(les: dict, d: dict, r: int, t: int) -> dict | None:
    rounds = d["rounds"]
    if r >= len(rounds):
        return None
    rnd = rounds[r]
    if t >= len(rnd["turns"]):
        return _turn_ctx(les, d, r + 1, 0)
    turn = rnd["turns"][t]
    phrases = [p for p in les["phrases"]]
    return {"r": r, "t": t, "round": rnd, "turn": turn, "new_round": t == 0,
            "timer": rnd.get("timer_seconds") or d.get("timer_seconds") or 60,
            "hints": d.get("hints", True) and bool(phrases), "phrases": phrases}


@app.post("/lesson/{lesson_id}/drill/4/turn", response_class=HTMLResponse)
def chat_turn(request: Request, lesson_id: str, r: int = Form(...), t: int = Form(...), reply: str = Form(""),
              response_ms: int = Form(0), pasted: int = Form(0), timed_out: int = Form(0)):
    uid, les, bad = _lesson_or_404(request, lesson_id)
    if bad:
        return bad
    d = content.drill(les, 4)
    turn = d["rounds"][r]["turns"][t]
    res = grading.check_turn(reply, turn["checks"])
    comment = llm.chat_feedback(turn["bot_message"], reply, turn["expected_learner_move"]) if turn.get("llm_judge") else None
    db.log_attempt(uid, lesson_id, 4, f"r{r}t{t}", reply, {"passed": res.passed, "problems": res.problems,
                   "timed_out": bool(timed_out), "llm": comment}, pasted=pasted, response_ms=response_ms)
    rnd = d["rounds"][r]
    closing = rnd.get("closing_message") if t + 1 >= len(rnd["turns"]) else None
    nxt = _turn_ctx(les, d, r, t + 1)
    return render(request, "partials/chat_turn.html", lesson=les, d=d, reply=reply, res=res, turn=turn,
                  comment=comment, closing=closing, closing_from=_bot_name(rnd) if closing else None,
                  bot_name=_bot_name(rnd), next=nxt, timed_out=timed_out)


def _bot_name(rnd: dict) -> str:
    return rnd["bot_persona"].split(",")[0]


templates.env.globals.update(bot_name=_bot_name)


# ---------------------------------------------------------------- email and revision
def _grade_email(uid: int, les: dict, subject: str, body: str) -> list[grading.CheckResult]:
    d5 = content.drill(les, 5)
    return grading.check_email(subject, body, d5["checks"], les["phrases"], content.phrases_up_to(les["lesson_id"]))


@app.post("/lesson/{lesson_id}/drill/5", response_class=HTMLResponse)
def email_submit(request: Request, lesson_id: str, subject: str = Form(""), body: str = Form(""),
                 plan_purpose: str = Form(""), plan_action: str = Form(""), plan_reason: str = Form(""),
                 plan_deadline: str = Form(""), pasted: int = Form(0), response_ms: int = Form(0)):
    plan = {"purpose": plan_purpose, "action": plan_action, "reason": plan_reason, "deadline": plan_deadline}
    uid, les, bad = _lesson_or_404(request, lesson_id)
    if bad:
        return bad
    checks = _grade_email(uid, les, subject, body)
    d5 = content.drill(les, 5)
    comment = llm.email_feedback(d5["scenario"], f"Subject: {subject}\n{body}", d5["priority_pattern"], d5["revision_target"])
    db.log_attempt(uid, lesson_id, 5, "email", json.dumps({"subject": subject, "body": body, "plan": plan}),
                   {"passed": [c.passed for c in checks], "llm": comment}, pasted=pasted, response_ms=response_ms)
    return render(request, "partials/email_result.html", lesson=les, d5=d5, checks=checks, comment=comment,
                  all_ok=all(c.passed for c in checks))


@app.post("/lesson/{lesson_id}/drill/6", response_class=HTMLResponse)
def revision_submit(request: Request, lesson_id: str, subject: str = Form(""), body: str = Form(""),
                    pasted: int = Form(0)):
    uid, les, bad = _lesson_or_404(request, lesson_id)
    if bad:
        return bad
    checks = _grade_email(uid, les, subject, body)
    db.log_attempt(uid, lesson_id, 6, "email", json.dumps({"subject": subject, "body": body}),
                   {"passed": [c.passed for c in checks]}, pasted=pasted, is_revision=True)
    d6 = content.drill(les, 6)
    instinct = None
    if d6.get("compare_with_instinct_check"):
        row = db.last_attempt(uid, lesson_id, 0, "instinct")
        instinct = row["response"] if row else None
    return render(request, "partials/revision_result.html", lesson=les, checks=checks, d6=d6, instinct=instinct,
                  revised_first=_first_sentence(body))


def _first_sentence(body: str) -> str:
    lines = [l for l in body.splitlines() if l.strip() and not re.match(r"(?i)^\s*(hi|dear|hello)\b.*,\s*$", l)]
    text = " ".join(lines)
    m = re.match(r"(.+?[.?!])(\s|$)", text)
    return m.group(1) if m else text[:200]
