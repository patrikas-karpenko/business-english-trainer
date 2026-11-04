from app import content, grading


def test_every_model_email_passes_its_checks():
    for les in content.lessons():
        d5 = content.drill(les, 5)
        model = content.drill(les, 6)["model_answer"]
        subject = next((l.split(":", 1)[1] for l in model if l.lower().startswith("subject:")), "")
        body = "\n".join(l for l in model if not l.lower().startswith("subject:"))
        res = grading.check_email(subject, body, d5["checks"], les["phrases"], content.phrases_up_to(les["lesson_id"]))
        failed = [r.message for r in res if not r.passed]
        assert not failed, (les["lesson_id"], failed)


def test_every_model_chat_reply_passes():
    for les in content.lessons():
        for rnd in content.drill(les, 4)["rounds"]:
            for t in rnd["turns"]:
                assert grading.check_turn(t["model_reply"], t["checks"]).passed, (les["lesson_id"], t["turn_no"])


def test_weak_replies_fail():
    turn = content.drill(content.lesson("1.07"), 4)["rounds"][0]["turns"][0]
    assert not grading.check_turn("OK, no problem.", turn["checks"]).passed
    turn = content.drill(content.lesson("1.11"), 4)["rounds"][0]["turns"][0]
    assert not grading.check_turn("No problem, 12 June is fine.", turn["checks"]).passed


def test_fill_accepts_exact_and_valid_variants():
    card = content.card("P1.01.2")
    fv = card["fill_variants"][0]
    assert grading.check_fill(["could you", "by"], fv["gaps"], fv["text"], card["grade_with"])
    assert grading.check_fill(["Can you", "by"], fv["gaps"], fv["text"], card["grade_with"])
    assert not grading.check_fill(["please", "by"], fv["gaps"], fv["text"], card["grade_with"])
    assert grading.check_fill(["Could you", "by"], fv["gaps"], fv["text"].replace("could", "Could"), card["grade_with"])


def test_gap_normalises_apostrophes():
    assert grading.check_gap("I’m", ["I'm"])
    assert grading.check_gap("  Thanks ", ["thanks"])


def test_auto_rating():
    assert grading.auto_rating(False, 1000) == "Again"
    assert grading.auto_rating(True, 3000) == "Easy"
    assert grading.auto_rating(True, 9000) == "Good"
    assert grading.auto_rating(True, 20000) == "Hard"


def test_card_variables_fill_every_placeholder():
    for pid in content.all_phrase_ids():
        c = content.card(pid)
        for v in c["fill_variants"]:
            filled = content.fill_vars(v["text"], content.pick_vars())
            assert "<" not in filled, (pid, filled)
            assert grading.matches_any(c["grade_with"], filled), (pid, filled)
