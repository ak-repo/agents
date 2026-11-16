# Expense Agent

A chat agent that manages your expenses in SQLite through tool calls. The model runs on **OpenRouter** (one API key, many models, including free ones). Any other OpenAI-compatible endpoint also works. Use it from a **web chat page**, the **terminal**, or an **HTTP API**.

```
you> Add 250 for lunch today                -> add_expense
you> How much did I spend on food this week -> sum_by_category
you> Delete the cab one                     -> asks for confirmation, then delete_expense
```

The model never touches the database. It only asks for tool calls, and the code validates and runs them. Deletes always need your confirmation, enforced in code and not in the prompt.

## Quick start

Requires Python 3.10+ and an OpenRouter API key from <https://openrouter.ai/keys>. Models whose id ends in `:free` cost nothing, but they have rate limits. Paid models need credits on your OpenRouter account.

```bash
make setup          # creates .venv, installs dependencies, creates .env
# edit .env and set OPENROUTER_API_KEY
make web            # open http://127.0.0.1:8000
```

No `make`? Do it by hand:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # then set OPENROUTER_API_KEY inside
uvicorn api:app --port 8000
```

## Configuration (`.env`)

The app reads `.env` automatically. Variables already set in your shell take priority. `.env` is git-ignored, so keep your key there and never commit it.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `OPENROUTER_API_KEY` | yes | none | Your OpenRouter API key |
| `OPENROUTER_MODEL` | no | `google/gemma-4-31b-it:free` | Model id. It must support tool calling. Run `make models` for free ones |
| `OPENROUTER_BASE_URL` | no | `https://openrouter.ai/api/v1` | API base URL. Change it to use another OpenAI-compatible server, e.g. `http://localhost:11434/v1` for a local Ollama |
| `EXPENSE_DB` | no | `expenses.db` | SQLite file path |

## How to operate

### Web chat

```bash
make web            # http://127.0.0.1:8000
make dev            # same, but reloads when you edit code
make web PORT=9000  # different port
```

- Type a message and press **Enter** (**Shift+Enter** for a new line). The small grey chips under each reply show which tools ran.
- For a delete, a yellow card appears with the exact expense. Click **Yes, do it** or **Cancel**.
- **New chat** starts a fresh conversation. The chat memory lives in the server process, so restarting the server also clears it.

### Terminal chat

```bash
make chat           # commands: /reset  /quit
make verbose        # also prints every tool call
```

### HTTP API

```bash
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message":"I spent 250 on lunch"}'
# -> {"session_id":"...","reply":"...","pending":null,"tool_calls":[...]}

curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"session_id":"<id>","message":"delete that"}'
# -> "pending": {"tool":"delete_expense", ..., "description":"Delete expense #1: ..."}

curl -s localhost:8000/confirm -H 'content-type: application/json' \
  -d '{"session_id":"<id>","approve":true}'
```

Other endpoints: `GET /` (web chat), `GET /health`, `GET /docs` (interactive API docs).

### Make targets

| Command | What it does |
|---|---|
| `make setup` | Create `.venv`, install dependencies, create `.env` if missing |
| `make web` / `make dev` | Web chat (`dev` auto-reloads) |
| `make chat` / `make verbose` | Terminal chat (`verbose` prints tool calls) |
| `make test` | Run the 10 live-model test cases (`TEST_RUNS=3 make test` for stability) |
| `make models` | List the free OpenRouter models that support tool calling |
| `make db` | Print every row in the expenses database |
| `make clean` | Remove caches (keeps `.venv`, `.env`, `expenses.db`) |

Dependencies reinstall automatically when `requirements.txt` changes.

## Project layout

```
db.py        SQL only. Knows nothing about AI.
tools.py     Input validation, tool schemas for the model, dispatch.
agent.py     The model loop. Knows nothing about expenses.
main.py      Terminal chat.
api.py       HTTP API + serves the web chat.
static/      index.html, the web chat page (plain HTML/CSS/JS, no build step).
config.py    Loads .env.
tests.py     10 live-model test cases on a temporary seeded database.
Makefile     Shortcuts for everything above.
```

Layering rule: `db` -> `tools` -> `agent` -> `main` / `api`. The UIs only call `agent.run_agent`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `OPENROUTER_API_KEY is not set` | Add it to `.env` |
| `401` | Wrong or revoked key. Create a new one at <https://openrouter.ai/keys> |
| `402` | A paid model and no credits. Use a `:free` model or add credits at <https://openrouter.ai/credits> |
| `404` "No endpoints found" | That model id is gone or has no tool support. Pick one from `make models` |
| `429` rate limited | Free models allow only a few requests per minute and a daily cap. Wait, switch to another `:free` model, or add credits. `make test` makes many calls and can hit this |
| Model never calls a tool, or sends bad arguments | The model is weak at tool calling. Switch `OPENROUTER_MODEL`. `make verbose` shows the calls |
| "Too many steps" reply | The model kept retrying a failing call. Run `make verbose` and read the tool error |
| "This week" gives wrong results in a long-running session | The date is fixed when the chat starts. Use **New chat** or `/reset` |
| Web page can't reach the server | Check that `make web` is running and the port matches |

## Notes

- The web chat has no login. It is meant for local use on `127.0.0.1`. Do not expose it to a network without adding authentication.
- API sessions are in memory. For production, persist them and expire old ones.
- When behaviour is wrong, fix the tool descriptions or the system prompt first, then add a test case. Don't loosen the tests.

The original design spec is in `expense-agent-implementation.md`. It was written for Ollama Cloud, and the model client in `agent.py` has since moved to OpenRouter. Everything else matches.
