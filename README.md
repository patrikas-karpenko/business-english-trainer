# Commerce English — Business English Trainer (pilot)

A phrase-first business English course: learners write their own work emails and
chats without ChatGPT. Level 1 (A2–B1) has 12 lessons and 70 phrases.

Each lesson has two sessions of about 10–15 minutes:

| Session | Drill | What happens |
|---|---|---|
| 1 | 0 | Warm-up: recall older phrases (or an "instinct check" sentence) |
| 1 | 1 | **Phrase cards**: Meet → Fill → Use, scheduled with FSRS |
| 1 | 2 | Reading |
| 1 | 3 | Write-in (gap-fill, graded) |
| 2 | 4 | **Chat simulator**: scripted customer or colleague, timer, rule-based checks |
| 2 | 5 | Email task with a plan card and automatic checks |
| 2 | 6 | Revision of one named problem, then the model answer |

## Phrase cards

* **Meet** — the phrase with the fixed part highlighted, plus an email and a chat example. No test.
* **Fill** — a new sentence with the fixed words missing. Hints fade: first letters → number of words → none.
* **Use** — a message from Tomas, Kevin, Daniel… and a task. Any reply that uses the phrase passes.

Each phrase is one FSRS item. Every phrase has 4 Fill sentences and 3 Use messages; the app never repeats
one of the last two, and fills names, days, times and numbers at random, so answers can't be memorised.
Answers are rated automatically (wrong = Again, slow = Hard, normal = Good, fast = Easy).

Pasting is blocked in every writing field and counted ("pastes tried" on the Today screen).

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional settings
UNLOCK_ALL=1 uvicorn app.main:app --reload
```

Open http://localhost:8000 and sign in with any name. Light and dark mode follow the phone's setting;
learners can switch on the Me tab or with the moon button.

## Tests

```bash
pip install pytest httpx
pytest -q
python tools/check_lessons.py content/level1_lessons_1-12.json   # content checks
```

## Content

`content/level1_lessons_1-12.json` is the single source of truth (lessons, phrases, cards, chats, email checks).
Regexes in it are JSON-escaped (`\\b`); edit it with a JSON-aware editor and run `tools/check_lessons.py`.

## Settings (.env)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs the login cookie. **Set a long random value on the server.** |
| `PILOT_CODE` | If set, learners need this code to sign in. |
| `UNLOCK_ALL` | `1` opens all lessons (testing). Otherwise each lesson opens after the previous one. |
| `DATABASE_PATH` | SQLite file (default `data/trainer.db`). |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | Optional coaching comments from any OpenAI-compatible API. Without them the app uses rule-based checks only. |

## Sharing with testers in mainland China

* Host on a small server in **Singapore or Hong Kong** with your own domain and HTTPS. No ICP licence is needed outside the mainland.
* The app loads **nothing from outside the server**: no Google Fonts, no CDNs (htmx is in `app/static/`). Keep it that way.
* For AI comments, use a model the server can reach from that region (Qwen via Alibaba Cloud Singapore, or DeepSeek). The Gemini API is not available from Hong Kong.
* Share the link in WeChat. If WeChat's browser warns about an unknown site, open it in Safari or Chrome.

A minimal server setup (Ubuntu):

```bash
sudo apt install python3-venv caddy
git clone https://github.com/patrikas-karpenko/business-english-trainer && cd business-english-trainer
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env          # SECRET_KEY, PILOT_CODE
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
# /etc/caddy/Caddyfile:   your-domain.com { reverse_proxy 127.0.0.1:8000 }
```

Run uvicorn as a systemd service so it restarts on reboot.
