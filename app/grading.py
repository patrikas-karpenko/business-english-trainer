"""All rule-based grading: write-in gaps, phrase cards, chat turns and emails.

Text is normalised first (curly apostrophes -> straight, lower case) and every
regex runs with IGNORECASE | MULTILINE, exactly like tools/check_lessons.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

FLAGS = re.IGNORECASE | re.MULTILINE


def norm(text: str) -> str:
    return (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').lower()


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", norm(text)).strip(" .,!?")


def words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9',.%-]*", text or ""))


def matches_any(patterns: list[str], text: str) -> bool:
    t = norm(text)
    return any(re.search(p, t, FLAGS) for p in patterns)


# ---------------------------------------------------------------- write-in and fill cards
def check_gap(answer: str, accept: list[str]) -> bool:
    return squash(answer) in {squash(a) for a in accept}


def check_fill(inputs: list[str], gaps: list[str], sentence: str, patterns: list[str]) -> bool:
    """Exact gap words pass; so does any filling that makes the sentence use the phrase
    (e.g. 'can you' where the card expected 'could you')."""
    if len(inputs) != len(gaps) or not all(i.strip() for i in inputs):
        return False
    if all(squash(i) == squash(g) for i, g in zip(inputs, gaps)):
        return True
    rebuilt, pos = "", 0
    for i, g in zip(inputs, gaps):
        k = sentence.find(g, pos)
        if k < 0:
            return False
        rebuilt += sentence[pos:k] + i.strip()
        pos = k + len(g)
    rebuilt += sentence[pos:]
    return matches_any(patterns, rebuilt)


# ---------------------------------------------------------------- chat turns
@dataclass
class TurnResult:
    passed: bool
    problems: list[str] = field(default_factory=list)


def check_turn(reply: str, checks: dict) -> TurnResult:
    t = norm(reply)
    problems = []
    if not t.strip():
        return TurnResult(False, ["Write a reply first."])
    for p in checks.get("must_match", []):
        if not re.search(p, t, FLAGS):
            problems.append("missing")
    for p in checks.get("must_not_match", []):
        if re.search(p, t, FLAGS):
            problems.append("avoid")
    mw = checks.get("max_words")
    if mw and words(reply) > mw:
        problems.append(f"Too long: keep it under {mw} words.")
    return TurnResult(not problems, problems)


# ---------------------------------------------------------------- emails
@dataclass
class CheckResult:
    type: str
    passed: bool
    message: str


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


def _phrase_hits(text: str, phrases: list[dict]) -> list[str]:
    return [p["phrase_id"] for p in phrases if any(re.search(pat, text, FLAGS) for pat in p["patterns"])]


def check_email(subject: str, body: str, checks: list[dict], lesson_phrases: list[dict],
                course_phrases: list[dict]) -> list[CheckResult]:
    lines = [l.rstrip() for l in (body or "").splitlines()]
    body_lines = [l for l in lines if l.strip() and not re.match(r"(?i)^\s*(subject|cc):", l)]
    full = norm("Subject: " + (subject or "") + "\n" + body)
    main = norm(" ".join(l for l in body_lines if not re.match(r"(?i)^\s*(hi|dear|hello)\b", l)))
    n_words = words(" ".join(body_lines))
    out = []
    for c in checks:
        t = c["type"]
        if t == "word_range":
            ok = c["min"] <= n_words <= c["max"]
            msg = f"Length {c['min']}–{c['max']} words (yours: {n_words})"
        elif t == "subject_max_chars":
            ok = 0 < len((subject or "").strip()) <= c["max"]
            msg = f"A subject line of up to {c['max']} characters"
        elif t == "regex_present":
            ok = re.search(c["pattern"], full, FLAGS) is not None
            msg = "Includes " + c.get("label", _label(c["pattern"]))
        elif t == "regex_absent":
            ok = re.search(c["pattern"], full, FLAGS) is None
            msg = "Avoids " + c.get("label", _label(c["pattern"]))
        elif t == "regex_in_first_sentences":
            first = " ".join(_sentences(main)[: c["sentences"]])
            ok = re.search(c["pattern"], first, FLAGS) is not None
            where = "first sentence" if c["sentences"] == 1 else f"first {c['sentences']} sentences"
            msg = f"Main point in the {where}: " + _label(c["pattern"])
        elif t == "min_list_lines":
            ok = len([l for l in body_lines if re.match(c["pattern"], l, FLAGS)]) >= c["min"]
            msg = f"At least {c['min']} list lines"
        elif t == "min_count":
            ok = len(re.findall(c["pattern"], full, FLAGS)) >= c["min"]
            msg = f"At least {c['min']} × " + _label(c["pattern"])
        elif t == "max_count":
            n = len(re.findall(c["pattern"], full, FLAGS))
            ok = n <= c["max"]
            msg = f"No more than {c['max']} × " + _label(c["pattern"]) + f" (yours: {n})"
        elif t == "min_lesson_phrases":
            n = len(_phrase_hits(full, lesson_phrases))
            ok = n >= c["min"]
            msg = f"At least {c['min']} phrase{'s' if c['min'] > 1 else ''} from this lesson (yours: {n})"
        elif t == "min_course_phrases":
            n = len(_phrase_hits(full, course_phrases))
            ok = n >= c["min"]
            msg = f"At least {c['min']} course phrases (yours: {n})"
        else:
            ok, msg = True, t
        out.append(CheckResult(t, ok, msg))
    return out


def _label(pattern: str) -> str:
    """Readable version of a regex for learners: '\\b18 may\\b|\\bmay 18\\b' -> '18 may / may 18'."""
    s = pattern.replace("\\?", "\x00").replace("\\b", "").replace("(?:", "(").replace("\\.", ".").replace(",?", ",")
    s = re.sub(r"\[\^[^\]]*\]\*", " … ", s)
    s = s.replace("\\s*", " ").replace("^", "").replace("$", "").replace("?", "")
    s = re.sub(r"\\d\+?", "#", s).replace("\\w+", "…")
    s = s.replace("|", " / ").replace("\\", "").replace("\x00", "?")
    s = re.sub(r"\s+", " ", s).strip()
    for key, friendly in FRIENDLY.items():
        if key in s:
            return friendly
    return "“" + s + "”"


# Learner-friendly names for the longer patterns.
FRIENDLY = {
    "monday / tuesday": "a deadline or time (for example “by Friday”, “today”)",
    "cc:": "a Cc line with Anna Berg",
    "(could / can / would) you": "a polite request (“Could you …?”, “Would it be possible …?”)",
    "why (didn't": "blaming words (“Why didn't you …”, “ASAP”, “still not”)",
    "i'm afraid / i am afraid": "“I'm afraid” or “Unfortunately”",
    "invit(e / ation)": "“invite” or “invitation”",
}


def auto_rating(correct: bool, response_ms: int | None) -> str:
    """Map a typed answer to an FSRS rating name."""
    if not correct:
        return "Again"
    if response_ms is not None and response_ms > 15000:
        return "Hard"
    if response_ms is not None and response_ms < 5000:
        return "Easy"
    return "Good"
