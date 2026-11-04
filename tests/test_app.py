import re

from app import cards, db


def test_pages_render(client):
    for url in ["/today", "/cards", "/lessons", "/me", "/lesson/1.01"] + [f"/lesson/1.07/drill/{n}" for n in range(7)]:
        r = client.get(url)
        assert r.status_code == 200, url
        assert "cdn" not in r.text.lower() and "googleapis" not in r.text, url


def test_login_required(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "x.db"))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        r = c.get("/today", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"


def test_card_flow_meet_fill_use(client):
    uid = db.get_or_create_user("Tester")
    r = client.get("/lesson/1.01/drill/1")
    assert "New phrase" in r.text
    # Meet all eight Lesson 1 phrases
    for _ in range(8):
        pid = re.search(r'name="phrase_id" value="([^"]+)"', r.text).group(1)
        r = client.post("/cards/meet", data={"phrase_id": pid, "lesson": "1.01", "reviewed": 0})
    assert "Cards finished" in r.text or "Fill" in r.text
    assert db.get_card(uid, "P1.01.2") is not None
    # Answer a Fill card correctly twice on different days -> stage becomes Use
    row = db.get_card(uid, "P1.01.2")
    row["success_days"] = ["2026-01-01", "2026-01-02"]
    db.save_card(uid, row)
    assert cards.stage_for(db.get_card(uid, "P1.01.2")) == "use"
    view = cards.build(uid, "P1.01.2")
    assert view["stage"] == "use" and view["task"] and "<" not in view["task"]
    res = cards.answer(uid, "P1.01.2", "use", view["variant"], ["Could you finish it by Thursday?"], view["vars"], 4000)
    assert res["correct"] and res["rating"] == "Easy"
    # A wrong answer sends it back to Fill
    res = cards.answer(uid, "P1.01.2", "use", view["variant"], ["Send it now."], view["vars"], 4000)
    assert not res["correct"]
    assert cards.stage_for(db.get_card(uid, "P1.01.2")) == "fill"


def test_variants_rotate(client):
    uid = db.get_or_create_user("Tester")
    cards.meet_done(uid, "P1.02.3")
    seen = []
    for _ in range(6):
        v = cards.build(uid, "P1.02.3")
        seen.append(v["variant"])
        cards.answer(uid, "P1.02.3", "fill", v["variant"], ["just to confirm"], v["vars"], 8000)
        row = db.get_card(uid, "P1.02.3")
        row["success_days"] = []  # keep it on Fill for the test
        db.save_card(uid, row)
    for a, b in zip(seen, seen[1:]):
        assert a != b
    assert len(set(seen[:4])) == 4  # all four variants before any repeat


def test_hints_fade(client):
    uid = db.get_or_create_user("Tester")
    cards.meet_done(uid, "P1.05.1")
    levels = []
    for _ in range(3):
        v = cards.build(uid, "P1.05.1")
        levels.append(v["hint_level"])
        cards.answer(uid, "P1.05.1", "fill", v["variant"], ["nope"], v["vars"], 8000)
    assert levels == [0, 1, 2]


def test_writein_and_email(client):
    r = client.post("/lesson/1.07/drill/3", data={"item1": "clarify", "item2": "mean", "item3": "x"})
    assert "of 6 correct" in r.text
    body = "Hi Tomas,\nOK no problem.\nBest"
    r = client.post("/lesson/1.07/drill/5", data={"subject": "x", "body": body})
    assert "Revision task" in r.text
    r = client.get("/lesson/1.07/drill/6")
    assert "OK no problem." in r.text


def test_chat_turns_progress(client):
    r = client.post("/lesson/1.07/drill/4/turn", data={"r": 0, "t": 0, "reply": "OK, no problem."})
    assert "Try next time" in r.text and 'name="t" value="1"' in r.text
    client.post("/lesson/1.07/drill/4/turn", data={"r": 0, "t": 1, "reply": "Could you send me an example?"})
    r = client.post("/lesson/1.07/drill/4/turn", data={"r": 0, "t": 2, "reply": "So, if I understand correctly, you want a black box?"})
    assert "Chat finished" in r.text


def test_paste_counts(client):
    client.post("/lesson/1.07/drill/5", data={"subject": "x", "body": "Hi", "pasted": 2})
    assert "pastes tried" in client.get("/today").text
