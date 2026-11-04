"""Load the lessons JSON, compile every regex, and run the model answers through the grader rules.

Usage: python check_lessons.py lessons.json
Every model answer should pass its own checks; anything that fails is printed.
"""
import json
import re
import sys

FLAGS = re.IGNORECASE | re.MULTILINE


def norm(text: str) -> str:
    return text.replace("’", "'").lower()


def body_lines(lines):
    return [l for l in lines if l and not re.match(r"(?i)^(subject|cc):", l)]


def sentences(text: str):
    return [s for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


def words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9',.%-]*", text))


def lesson_phrase_hits(text, phrases):
    return [p["phrase_id"] for p in phrases if any(re.search(pat, text, FLAGS) for pat in p["patterns"])]


def run_email_checks(model_lines, checks, phrases, course_phrases=()):
    full = norm("\n".join(model_lines))
    body = body_lines(model_lines)
    subject = next((l for l in model_lines if l.lower().startswith("subject:")), "")
    # Skip the greeting line ("Hi Tomas,") when finding the first sentences.
    main = norm(" ".join(l for l in body if not re.match(r"(?i)^(hi|dear|hello)\b", l)))
    fails = []
    for c in checks:
        t = c["type"]
        if t == "word_range":
            n = words(" ".join(body))
            ok = c["min"] <= n <= c["max"]
        elif t == "subject_max_chars":
            ok = 0 < len(subject.split(":", 1)[-1].strip()) <= c["max"]
        elif t == "regex_present":
            ok = re.search(c["pattern"], full, FLAGS) is not None
        elif t == "regex_absent":
            ok = re.search(c["pattern"], full, FLAGS) is None
        elif t == "regex_in_first_sentences":
            ok = re.search(c["pattern"], " ".join(sentences(main)[: c["sentences"]]), FLAGS) is not None
        elif t == "min_list_lines":
            ok = len([l for l in body if re.match(c["pattern"], l, FLAGS)]) >= c["min"]
        elif t == "min_count":
            ok = len(re.findall(c["pattern"], full, FLAGS)) >= c["min"]
        elif t == "min_course_phrases":
            ok = len(lesson_phrase_hits(full, course_phrases)) >= c["min"]
        elif t == "max_count":
            ok = len(re.findall(c["pattern"], full, FLAGS)) <= c["max"]
        elif t == "min_lesson_phrases":
            ok = len(lesson_phrase_hits(full, phrases)) >= c["min"]
        else:
            ok = False
        if not ok:
            fails.append(c)
    return fails


def run_turn_checks(reply, checks):
    text = norm(reply)
    fails = []
    for p in checks["must_match"]:
        if not re.search(p, text, FLAGS):
            fails.append(("must_match", p))
    for p in checks["must_not_match"]:
        if re.search(p, text, FLAGS):
            fails.append(("must_not_match", p))
    if checks["max_words"] and words(reply) > checks["max_words"]:
        fails.append(("max_words", checks["max_words"]))
    return fails


def main(path):
    data = json.load(open(path, encoding="utf-8"))
    problems = 0
    course = []
    for les in data["lessons"]:
        course += les["phrases"]
        # 1) every pattern compiles
        for p in les["phrases"]:
            for pat in p["patterns"]:
                re.compile(pat, FLAGS)
        drills = {d["drill_no"]: d for d in les["drills"]}
        # 1b) phrase cards: every example and every fill sentence uses the phrase (its pattern matches),
        #     the highlighted / gapped words really appear in the sentence, and every fill card has a gap
        for card in drills[1].get("cards", []):
            pid = card["phrase_id"]
            texts = [("example", e["text"], e["highlight"]) for e in card["meet"]["examples"]]
            for fv in card["fill_variants"]:
                texts.append((f"fill v{fv['variant']}", fv["text"], fv["gaps"]))
            seen = set()
            for kind, text, parts in texts:
                if text in seen:
                    problems += 1
                    print(f"{les['lesson_id']} {pid} {kind}: duplicate sentence: {text}")
                seen.add(text)
                # fill the app variables with every possible value; all versions must still pass
                for name in re.findall(r"<([A-Z]+)>", text):
                    if name not in data["card_variables"]:
                        problems += 1
                        print(f"{les['lesson_id']} {pid} {kind}: unknown variable <{name}>")
                t = norm(re.sub(r"<([A-Z]+)>", lambda m: data["card_variables"].get(m.group(1), ["x"])[-1], text))
                if not any(re.search(p, t, FLAGS) for p in card["grade_with"]):
                    problems += 1
                    print(f"{les['lesson_id']} {pid} {kind}: pattern does not match: {text}")
                if not parts or any(norm(x) not in t for x in parts):
                    problems += 1
                    print(f"{les['lesson_id']} {pid} {kind}: highlight/gap missing: {text}")
            if len(card["fill_variants"]) < 4 or len(card["use_variants"]) < 3 or not all(u["task"] for u in card["use_variants"]):
                problems += 1
                print(f"{les['lesson_id']} {pid}: needs 4 fill and 3 use variants, each with a task")
        # 2) chat model replies pass their own turn checks
        for rnd in drills[4]["rounds"]:
            for turn in rnd["turns"]:
                f = run_turn_checks(turn["model_reply"], turn["checks"])
                if f:
                    problems += 1
                    print(f"{les['lesson_id']} chat round {rnd['round_no']} turn {turn['turn_no']}: {f}")
        # 3) the model email passes the email checks
        f = run_email_checks(drills[6]["model_answer"], drills[5]["checks"], les["phrases"], course)
        if f:
            problems += 1
            print(f"{les['lesson_id']} email: {f}")
        hits = lesson_phrase_hits(norm("\n".join(drills[6]["model_answer"])), les["phrases"])
        print(f"{les['lesson_id']} OK checks run · model email uses {len(hits)} lesson phrases: {', '.join(hits)}")
    print("problems:", problems)
    return problems


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1]) else 0)
