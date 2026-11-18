# Expense Tracker Agent — Full Implementation (Ollama Cloud, Python)

A chat agent that manages expenses in SQLite through tool calls. Model runs on **Ollama Cloud** (hosted API, API key, no local Ollama install).

```
you> Add 250 for lunch today                -> add_expense
you> How much did I spend on food this week -> sum_by_category
you> Delete the cab one                     -> asks y/N, then delete_expense
```

**Requirements:** Python 3.10+, an Ollama API key (https://ollama.com/settings/keys).

---

## 0. Instructions for the implementer (read first)

1. Create every file below exactly as written, in one folder `expense-agent/`.
2. Do not add stubs, TODOs or placeholder code. All code here is complete.
3. After creating files, run the verification steps in section 9 in order and fix any failure before moving on.
4. Never hardcode the API key. It is read from the `OLLAMA_API_KEY` environment variable only.
5. Layering rule (do not break it):
   - `db.py` — SQL only. Knows nothing about AI.
   - `tools.py` — validation + tool schemas + dispatch. Wraps `db.py`.
   - `agent.py` — the model loop. Knows nothing about expenses.
   - `main.py` / `api.py` — user interfaces. Only call `agent.run_agent`.

---

## 1. How it works (the whole idea)

```
user message
     │
     ▼
 ┌─► send messages + tool list to model (Ollama cloud)
 │        │
 │        ▼
 │   model replies with:
 │     (a) tool_calls  ──► your code validates + runs the function ──► append result as role "tool" ─┐
 │     (b) plain text  ──► final answer, stop                                                        │
 └───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- The model never touches the database. It only **asks** for a tool call. Your code decides whether to run it.
- Tool = name + description + JSON schema (the model picks tools by reading the description) + the real function.
- Writes that destroy data (`delete_expense`) need human confirmation, enforced in code, not in the prompt.

### Build levels (what each part is for)

| Level | Capability | Where in this code |
|---|---|---|
| 1 | One tool + the loop | `add_expense`, `agent.run_agent`, `main.py` |
| 2 | Read tools | `list_expenses`, `sum_by_category` |
| 3 | Guardrails for writes | `NEEDS_CONFIRMATION`, `confirm` callback, `delete_expense` |
| 4 | Conversation memory | `messages` list kept across turns in `main.py`, `update_expense` |
| 5 | Tests + API | `tests.py`, `api.py` |

If you are learning, type the files yourself in that order. The code below is the finished version of all five levels.

---

## 2. Project structure

```
expense-agent/
├── requirements.txt
├── .gitignore
├── db.py
├── tools.py
├── agent.py
├── main.py
├── api.py
└── tests.py
```

---

## 3. Setup

```bash
mkdir expense-agent && cd expense-agent
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export OLLAMA_API_KEY="your_key_here"        # required
export OLLAMA_MODEL="gpt-oss:120b"           # optional, this is the default
```

List the models your key can use (pick one that supports tool calling):

```bash
curl -H "Authorization: Bearer $OLLAMA_API_KEY" https://ollama.com/api/tags
```

For the hosted API the model name has **no** `:cloud` suffix (use `gpt-oss:120b`, not `gpt-oss:120b-cloud`).

---

## 4. Files

### `requirements.txt`

```
ollama
fastapi
uvicorn
```

### `.gitignore`

```
.venv/
__pycache__/
*.db
.env
```

### `db.py`

```python
"""SQLite access layer. SQL only — no AI, no validation of model input."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

DB_PATH = os.environ.get("EXPENSE_DB", "expenses.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    amount   REAL NOT NULL CHECK (amount > 0),
    category TEXT NOT NULL,
    note     TEXT,
    spent_on TEXT NOT NULL
)
"""

# Columns that update_expense may touch. Column names are never taken from input.
_UPDATABLE = ("amount", "category", "note", "spent_on")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as c:
        c.execute(SCHEMA)


def _fetch(conn, expense_id: int):
    row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    return dict(row) if row else None


def get_expense(expense_id: int):
    with get_conn() as c:
        return _fetch(c, expense_id)


def add_expense(amount: float, category: str, note: str | None = None,
                spent_on: str | None = None) -> dict:
    spent_on = spent_on or date.today().isoformat()
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO expenses (amount, category, note, spent_on) VALUES (?, ?, ?, ?)",
            (amount, category, note, spent_on),
        )
        return _fetch(c, cur.lastrowid)


def list_expenses(days: int, limit: int = 100) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM expenses WHERE spent_on >= ? "
            "ORDER BY spent_on DESC, id DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def sum_by_category(days: int) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as c:
        rows = c.execute(
            "SELECT category, ROUND(SUM(amount), 2) AS total, COUNT(*) AS count "
            "FROM expenses WHERE spent_on >= ? "
            "GROUP BY category ORDER BY total DESC",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_expense(expense_id: int, fields: dict):
    cols = [k for k in _UPDATABLE if k in fields]
    if not cols:
        return get_expense(expense_id)
    assignments = ", ".join(f"{k} = ?" for k in cols)  # k comes from the whitelist above
    values = [fields[k] for k in cols] + [expense_id]
    with get_conn() as c:
        cur = c.execute(f"UPDATE expenses SET {assignments} WHERE id = ?", values)
        if cur.rowcount == 0:
            return None
        return _fetch(c, expense_id)


def delete_expense(expense_id: int) -> bool:
    with get_conn() as c:
        cur = c.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        return cur.rowcount > 0
```

### `tools.py`

```python
"""Tool layer: input validation, tool schemas for the model, and dispatch.

The model can send wrong types, bad dates, negative amounts, extra arguments.
Everything is validated here. Tool functions return plain dicts and signal
problems with {"error": "..."} so the model can read the error and recover.
"""
import json
import logging
import math
from datetime import datetime

import db

log = logging.getLogger("expense-agent")

# Tools that change data destructively. The agent loop will not run these
# without an explicit decision from the user interface.
NEEDS_CONFIRMATION = {"delete_expense"}


# ---------- validators (raise ValueError with a model-readable message) ----------

def _amount(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError("amount must be a number")
    if not math.isfinite(x) or x <= 0:
        raise ValueError("amount must be greater than 0")
    if x > 10_000_000:
        raise ValueError("amount too large")
    return round(x, 2)


def _category(v) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError("category is required")
    c = v.strip().lower()
    if len(c) > 40:
        raise ValueError("category too long (max 40 characters)")
    return c


def _note(v):
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("note must be text")
    v = v.strip()
    if len(v) > 200:
        raise ValueError("note too long (max 200 characters)")
    return v or None


def _date(v):
    if v is None:
        return None
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError("spent_on must be a date in YYYY-MM-DD format")
    return v


def _days(v, default: int = 30) -> int:
    if v is None:
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError("days must be an integer")
    if not 1 <= n <= 3650:
        raise ValueError("days must be between 1 and 3650")
    return n


def _id(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError("id must be an integer")


# ---------- tool functions ----------

def add_expense(amount, category, note=None, spent_on=None):
    row = db.add_expense(_amount(amount), _category(category), _note(note), _date(spent_on))
    return {"added": row}


def list_expenses(days=30):
    rows = db.list_expenses(_days(days))
    return {"count": len(rows), "expenses": rows}


def sum_by_category(days=30):
    d = _days(days)
    rows = db.sum_by_category(d)
    return {
        "days": d,
        "grand_total": round(sum(r["total"] for r in rows), 2),
        "by_category": rows,
    }


def update_expense(id, amount=None, category=None, note=None, spent_on=None):
    fields = {}
    if amount is not None:
        fields["amount"] = _amount(amount)
    if category is not None:
        fields["category"] = _category(category)
    if note is not None:
        fields["note"] = _note(note)
    if spent_on is not None:
        fields["spent_on"] = _date(spent_on)
    if not fields:
        raise ValueError("nothing to update: provide amount, category, note or spent_on")
    row = db.update_expense(_id(id), fields)
    if row is None:
        return {"error": f"no expense with id {id}"}
    return {"updated": row}


def delete_expense(id):
    eid = _id(id)
    if not db.delete_expense(eid):
        return {"error": f"no expense with id {eid}"}
    return {"deleted_id": eid}


TOOL_FNS = {
    "add_expense": add_expense,
    "list_expenses": list_expenses,
    "sum_by_category": sum_by_category,
    "update_expense": update_expense,
    "delete_expense": delete_expense,
}


# ---------- schemas sent to the model ----------

def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SCHEMAS = [
    _tool(
        "add_expense",
        "Record a new expense. Use when the user says they spent money.",
        {
            "amount": {"type": "number", "description": "Amount spent, greater than 0"},
            "category": {"type": "string", "description": "Short category such as food, transport, rent, groceries"},
            "note": {"type": "string", "description": "Optional short description"},
            "spent_on": {"type": "string", "description": "Date as YYYY-MM-DD. Omit for today."},
        },
        ["amount", "category"],
    ),
    _tool(
        "list_expenses",
        "List individual expenses (with ids) from the last N days, newest first. "
        "Use to show expenses or to find an expense id before updating or deleting.",
        {"days": {"type": "integer", "description": "How many days back, default 30"}},
        [],
    ),
    _tool(
        "sum_by_category",
        "Total spent per category over the last N days, plus a grand total. "
        "Use for questions about totals, breakdowns or how much was spent.",
        {"days": {"type": "integer", "description": "How many days back, default 30"}},
        [],
    ),
    _tool(
        "update_expense",
        "Change fields of an existing expense by id. Provide only the fields to change.",
        {
            "id": {"type": "integer", "description": "Expense id from list_expenses"},
            "amount": {"type": "number"},
            "category": {"type": "string"},
            "note": {"type": "string"},
            "spent_on": {"type": "string", "description": "YYYY-MM-DD"},
        },
        ["id"],
    ),
    _tool(
        "delete_expense",
        "Permanently delete an expense by id. The user is asked to confirm automatically.",
        {"id": {"type": "integer", "description": "Expense id from list_expenses"}},
        ["id"],
    ),
]


# ---------- dispatch ----------

def execute(name: str, args: dict) -> dict:
    """Run a tool safely. Always returns a dict, never raises."""
    fn = TOOL_FNS.get(name)
    if fn is None:
        return {"error": f"unknown tool '{name}'"}
    try:
        return fn(**args)
    except ValueError as e:                 # validation problem: tell the model
        return {"error": str(e)}
    except TypeError as e:                  # wrong/missing/extra argument names
        return {"error": f"bad arguments: {e}"}
    except Exception as e:                  # real bug or DB failure: log it, hide details
        log.exception("tool %s failed", name)
        return {"error": f"internal error ({type(e).__name__})"}


def describe_action(name: str, args: dict) -> str:
    """Human-readable text for a confirmation prompt."""
    if name == "delete_expense":
        try:
            eid = int(args.get("id"))
        except (TypeError, ValueError):
            return f"Delete expense with id {args.get('id')!r}"
        row = db.get_expense(eid)
        if row is None:
            return f"Delete expense #{eid} (not found)"
        note = f" '{row['note']}'" if row["note"] else ""
        return f"Delete expense #{eid}: {row['amount']} {row['category']}{note} on {row['spent_on']}"
    return f"{name} {json.dumps(args)}"
```

### `agent.py`

```python
"""The agent loop. Knows about the model and tool calling, nothing about expenses."""
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date

from ollama import Client

import tools

MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b")
HOST = os.environ.get("OLLAMA_HOST", "https://ollama.com")
MAX_STEPS = 8  # hard cap on model<->tool round trips per user message

SYSTEM_PROMPT = """You are an expense tracking assistant. Today is {weekday}, {today}.

Rules:
- Use tools for all data. Never invent expenses, totals or ids.
- To update or delete an expense you need its id. If you do not know it, call list_expenses first.
- If more than one expense could match the user's request, ask the user which one. Do not guess.
- Convert relative dates ("yesterday", "last Friday") to YYYY-MM-DD using today's date.
- Deleting needs user confirmation, which the system handles. Just call delete_expense once you know the id.
- If a tool result says awaiting_user_confirmation, tell the user what needs confirming and stop.
- If a tool returns an error, fix the arguments once or explain the problem. Never repeat the same failing call.
- Report totals exactly as returned by tools. Keep replies short.
- If the request is not about expenses, say what you can do: add, list, total, update and delete expenses."""

_client: Client | None = None


def check_config() -> None:
    if not os.environ.get("OLLAMA_API_KEY"):
        raise RuntimeError("OLLAMA_API_KEY is not set. Export it before running.")


def _get_client() -> Client:
    global _client
    if _client is None:
        check_config()
        _client = Client(
            host=HOST,
            headers={"Authorization": "Bearer " + os.environ["OLLAMA_API_KEY"]},
        )
    return _client


def new_session() -> list:
    """Fresh conversation history containing only the system prompt."""
    today = date.today()
    prompt = SYSTEM_PROMPT.format(weekday=today.strftime("%A"), today=today.isoformat())
    return [{"role": "system", "content": prompt}]


@dataclass
class AgentResult:
    text: str
    calls: list = field(default_factory=list)  # [(tool_name, args, result), ...]


def _run_tool(name: str, args: dict, confirm) -> dict:
    if name in tools.NEEDS_CONFIRMATION:
        # No confirm callback means no way to ask the user, so refuse (safe default).
        decision = confirm(name, args) if confirm else "declined"
        if decision == "declined":
            return {"error": "the user declined this action"}
        if decision == "pending":
            return {
                "status": "awaiting_user_confirmation",
                "message": "Ask the user to confirm this action. Do not call it again yet.",
            }
        if decision != "approved":
            return {"error": "invalid confirmation decision"}
    return tools.execute(name, args)


def run_agent(messages: list, confirm=None, verbose: bool = False) -> AgentResult:
    """Run the loop until the model gives a final text answer.

    messages: the full history (mutated in place: assistant + tool messages are appended).
    confirm:  callable(name, args) -> "approved" | "declined" | "pending".
    """
    client = _get_client()
    calls = []

    for _ in range(MAX_STEPS):
        resp = client.chat(model=MODEL, messages=messages, tools=tools.TOOL_SCHEMAS)
        msg = resp.message
        messages.append(msg)

        if not msg.tool_calls:  # model is done
            return AgentResult(msg.content or "", calls)

        for call in msg.tool_calls:
            name = call.function.name
            args = dict(call.function.arguments or {})
            result = _run_tool(name, args, confirm)
            calls.append((name, args, result))
            if verbose:
                print(f"  [tool] {name}({json.dumps(args)}) -> {json.dumps(result)}", file=sys.stderr)
            messages.append({
                "role": "tool",
                "tool_name": name,
                "content": json.dumps(result),
            })

    return AgentResult("Stopped: too many steps without a final answer.", calls)
```

### `main.py`

```python
"""Terminal chat. Run: python main.py [--verbose]"""
import sys

import agent
import db
import tools


def confirm_cli(name: str, args: dict) -> str:
    answer = input(f"\n  ! {tools.describe_action(name, args)}\n  Proceed? [y/N] ").strip().lower()
    return "approved" if answer in ("y", "yes") else "declined"


def main() -> None:
    try:
        agent.check_config()
    except RuntimeError as e:
        sys.exit(str(e))

    db.init_db()
    verbose = "--verbose" in sys.argv
    messages = agent.new_session()  # created ONCE: this list is the conversation memory

    print(f"Expense agent ({agent.MODEL}). Commands: /reset  /quit")
    while True:
        try:
            user = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user in ("/quit", "/exit"):
            break
        if user == "/reset":
            messages = agent.new_session()
            print("history cleared")
            continue

        checkpoint = len(messages)
        messages.append({"role": "user", "content": user})
        try:
            result = agent.run_agent(messages, confirm=confirm_cli, verbose=verbose)
        except Exception as e:  # auth, network, model errors
            del messages[checkpoint:]  # drop the half-finished turn so history stays valid
            print(f"error: {e}")
            continue
        print(f"\nagent> {result.text}")


if __name__ == "__main__":
    main()
```

### `api.py`

HTTP wrapper. Run: `uvicorn api:app --reload`

Confirmation over HTTP works in two steps: when the model asks to delete, the response includes `pending`; the client then calls `POST /confirm`.

```python
"""HTTP API around the agent. Sessions are kept in memory (lost on restart)."""
import json
import threading
import uuid
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import agent
import db
import tools

db.init_db()
app = FastAPI(title="Expense Agent")


@dataclass
class Session:
    messages: list = field(default_factory=agent.new_session)
    pending: dict | None = None
    approved: set = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)


SESSIONS: dict[str, Session] = {}


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)


class ConfirmIn(BaseModel):
    session_id: str
    approve: bool


def _key(name: str, args: dict) -> str:
    return json.dumps([name, args], sort_keys=True)


def _turn(session: Session, text: str) -> dict:
    def confirm(name: str, args: dict) -> str:
        key = _key(name, args)
        if key in session.approved:
            session.approved.discard(key)
            return "approved"
        session.pending = {
            "key": key,
            "tool": name,
            "args": args,
            "description": tools.describe_action(name, args),
        }
        return "pending"

    checkpoint = len(session.messages)
    session.messages.append({"role": "user", "content": text})
    try:
        result = agent.run_agent(session.messages, confirm=confirm)
    except Exception as e:
        del session.messages[checkpoint:]
        raise HTTPException(status_code=502, detail=f"model call failed: {e}")

    pending = None
    if session.pending:
        pending = {k: v for k, v in session.pending.items() if k != "key"}
    return {
        "reply": result.text,
        "pending": pending,
        "tool_calls": [{"tool": n, "args": a} for n, a, _ in result.calls],
    }


@app.post("/chat")
def chat(body: ChatIn):
    sid = body.session_id or uuid.uuid4().hex
    session = SESSIONS.setdefault(sid, Session())
    with session.lock:
        session.pending = None  # a new message means the user moved on
        out = _turn(session, body.message)
    return {"session_id": sid, **out}


@app.post("/confirm")
def confirm(body: ConfirmIn):
    session = SESSIONS.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown session")
    with session.lock:
        if session.pending is None:
            raise HTTPException(status_code=400, detail="nothing is awaiting confirmation")
        if body.approve:
            session.approved.add(session.pending["key"])
            text = "Yes, go ahead."
        else:
            text = "No, cancel that."
        session.pending = None
        out = _turn(session, text)
    return {"session_id": body.session_id, **out}


@app.get("/health")
def health():
    return {"ok": True}
```

### `tests.py`

Runs 10 cases against a fresh seeded temporary database each time. Run: `python tests.py` (or `TEST_RUNS=3 python tests.py` to check stability).

```python
"""Agent tests. Each case: fresh seeded DB, one user message, checks on tool calls + DB state."""
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

import agent
import db

RUNS = int(os.environ.get("TEST_RUNS", "1"))
TODAY = date.today()
TMP = tempfile.mkdtemp(prefix="expense-agent-test-")
db.DB_PATH = os.path.join(TMP, "test.db")


def d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def reset_db() -> None:
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()
    db.add_expense(250, "food", "lunch", d(0))        # id 1
    db.add_expense(1200, "transport", "cab", d(2))    # id 2
    db.add_expense(80, "food", "tea", d(0))           # id 3


def rows() -> list[dict]:
    return db.list_expenses(365)


def called(result, name: str) -> bool:
    return any(c[0] == name for c in result.calls)


approve = lambda name, args: "approved"
decline = lambda name, args: "declined"


@dataclass
class Case:
    name: str
    prompt: str
    check: Callable  # (AgentResult) -> error string or None
    confirm: Callable = decline


def _t(cond: bool, msg: str):
    return None if cond else msg


CASES = [
    Case("add expense", "I spent 350 on groceries",
         lambda r: _t(called(r, "add_expense") and any(x["amount"] == 350 for x in rows()),
                      "expected add_expense and a 350 row")),
    Case("sum by category", "How much did I spend on food in the last 7 days?",
         lambda r: _t(called(r, "sum_by_category") and "330" in r.text,
                      "expected sum_by_category and 330 in the answer")),
    Case("list expenses", "Show my expenses from the last 7 days",
         lambda r: _t(called(r, "list_expenses"), "expected list_expenses")),
    Case("no tool needed", "What can you do?",
         lambda r: _t(not r.calls, "expected no tool calls")),
    Case("rejects negative amount", "Add -50 for snacks",
         lambda r: _t(len(rows()) == 3, "negative expense must not be stored")),
    Case("delete with approval", "Delete the cab expense",
         lambda r: _t(called(r, "delete_expense") and db.get_expense(2) is None,
                      "expected expense 2 deleted"),
         confirm=approve),
    Case("delete declined", "Delete the cab expense",
         lambda r: _t(db.get_expense(2) is not None, "expense 2 must still exist"),
         confirm=decline),
    Case("update amount", "Change the tea expense to 100",
         lambda r: _t((db.get_expense(3) or {}).get("amount") == 100, "expense 3 amount should be 100")),
    Case("relative date", "I spent 500 on fuel yesterday",
         lambda r: _t(any(x["amount"] == 500 and x["spent_on"] == d(1) for x in rows()),
                      f"expected a 500 row dated {d(1)}")),
    Case("ambiguous delete", "Delete my food expense",
         lambda r: _t(not called(r, "delete_expense"),
                      "two food expenses exist; agent must ask, not delete")),
]


def run_case(case: Case) -> str | None:
    reset_db()
    messages = agent.new_session()
    messages.append({"role": "user", "content": case.prompt})
    try:
        result = agent.run_agent(messages, confirm=case.confirm)
    except Exception as e:
        return f"exception: {e}"
    return case.check(result)


def main() -> None:
    try:
        agent.check_config()
    except RuntimeError as e:
        sys.exit(str(e))

    failed = 0
    for case in CASES:
        errors = [e for e in (run_case(case) for _ in range(RUNS)) if e]
        passed = RUNS - len(errors)
        status = "PASS" if not errors else "FAIL"
        print(f"{status}  {case.name}  ({passed}/{RUNS})")
        if errors:
            failed += 1
            print(f"      {errors[0]}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} cases passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
```

---

## 5. Run it

```bash
python main.py              # chat in the terminal
python main.py --verbose    # also print every tool call to stderr
uvicorn api:app --reload    # HTTP API on http://127.0.0.1:8000
python tests.py             # run the 10 cases
```

API example:

```bash
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message":"I spent 250 on lunch"}'
# -> {"session_id":"...","reply":"...","pending":null,"tool_calls":[...]}

curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"session_id":"<id>","message":"delete that"}'
# -> "pending": {"tool":"delete_expense", ... "description":"Delete expense #1: ..."}

curl -s localhost:8000/confirm -H 'content-type: application/json' \
  -d '{"session_id":"<id>","approve":true}'
```

---

## 6. Manual checks per level

Inspect the database directly: `sqlite3 expenses.db "select * from expenses"`

| Level | Type this | Expect |
|---|---|---|
| 1 | `Add 250 for lunch` | row appears in DB, agent confirms |
| 2 | `How much did I spend on food this week?` | `--verbose` shows `sum_by_category`; number matches SQL |
| 3 | `Delete the lunch one` | y/N prompt; `n` keeps row, `y` removes it |
| 4 | `Add 100 for tea` then `make that 120` | second message updates the same row (history works) |
| 5 | `python tests.py` | at least 9/10 pass on 3 runs: `TEST_RUNS=3 python tests.py` |

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `OLLAMA_API_KEY is not set` | `export OLLAMA_API_KEY=...` in the same shell |
| 401 / 403 from the API | Wrong or revoked key. Validate with the `curl .../api/tags` command in section 3 |
| 404 model not found | Wrong model name. Use a name from `/api/tags`, no `:cloud` suffix |
| Model never calls a tool | Model has no tool-calling support. Switch to another model; also check tool descriptions |
| Tool called with wrong args | Read the `error` in `--verbose`. Improve the tool description or validator message |
| Loop hits "too many steps" | Model keeps retrying a failing call. Check the tool error text; lower ambiguity in the prompt |
| Wrong "this week" results | Date missing from the system prompt. `new_session()` injects it; run `/reset` if the session is days old |
| Test case flaky | Run `TEST_RUNS=3`. Fix the tool description or system prompt first, never loosen the test |
| `TypeError` on `str | None` type hints | Python older than 3.10. Upgrade Python |

---

## 8. Rules to keep as you extend it

1. One job per tool, clear description, 2–6 tools total.
2. Validate every argument in `tools.py`. Never trust model output.
3. Destructive tools go in `NEEDS_CONFIRMATION`. Never rely on the prompt alone.
4. Keep `MAX_STEPS`.
5. Scope data per user/tenant **inside tool code** (add the user id to every query), never by asking the model to filter.
6. When behaviour is wrong, fix tool descriptions and the system prompt, then add a test case for it.
7. Session storage in `api.py` is in memory. For production, persist `messages` per session and expire old sessions.

---

## 9. Verification order for the implementer

1. `python -c "import db; db.init_db(); print(db.add_expense(1, 'x'))"` — prints a row dict. Then delete `expenses.db`.
2. `python -c "import tools; print(tools.execute('add_expense', {'amount': -5, 'category': 'x'}))"` — prints an error dict.
3. `python main.py --verbose`, run the Level 1–4 checks from section 6.
4. `python tests.py` — all 10 cases run; review any failures.
5. `uvicorn api:app` and run the curl examples.
