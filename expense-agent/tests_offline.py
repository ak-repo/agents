"""Offline tests: scripted fake model, temp DB, no network, no API quota. Run: python tests_offline.py"""
import json
import os
import sys
import tempfile
from types import SimpleNamespace as NS

os.environ["OPENROUTER_API_KEY"] = "fake"  # never used: the client is replaced below

import db
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
db.init_db()

import agent, tools  # noqa: E402
from datetime import date, timedelta  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  -- {detail}" if detail and not cond else ""))


# ---------- fake model ----------
def tc(id_, name, args):
    raw = args if isinstance(args, str) else json.dumps(args)
    return NS(id=id_, function=NS(name=name, arguments=raw))


class FakeClient:
    """script: list of (content, [tool_calls]) responses, consumed in order."""
    def __init__(self, script):
        self.script = list(script)
        self.seen = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, model, messages, tools):
        self.seen.append(json.loads(json.dumps(messages)))
        content, calls = self.script.pop(0)
        return NS(choices=[NS(message=NS(content=content, tool_calls=calls or None))])


def run(script, prompt, confirm=None):
    agent._client = FakeClient(script)
    m = agent.new_session()
    m.append({"role": "user", "content": prompt})
    return agent.run_agent(m, confirm=confirm), m


# ---------- tool layer ----------
r = tools.execute("add_expense", {"amount": 250, "category": " Food ", "note": "lunch"})
check("add normalises category", r.get("added", {}).get("category") == "food", r)
for bad in [-5, 0, "abc", float("nan"), float("inf"), 1e12, None]:
    r = tools.execute("add_expense", {"amount": bad, "category": "x"})
    check(f"reject amount {bad!r}", "error" in r, r)
check("reject bad date", "error" in tools.execute("add_expense", {"amount": 1, "category": "x", "spent_on": "yesterday"}))
check("reject extra arg", "error" in tools.execute("add_expense", {"amount": 1, "category": "x", "bogus": 1}))
check("unknown tool", "error" in tools.execute("rm_rf", {}))
check("update nothing -> error", "error" in tools.execute("update_expense", {"id": 1}))
check("update missing id", "error" in tools.execute("update_expense", {"id": 999, "amount": 5}))
check("delete missing id", "error" in tools.execute("delete_expense", {"id": 999}))
check("sql injection in category is inert",
      "added" in tools.execute("add_expense", {"amount": 1, "category": "x'; DROP TABLE expenses;--"}) and len(db.list_expenses(30)) >= 2)

# date normalisation: non-padded dates break lexicographic range queries
r = tools.execute("add_expense", {"amount": 7, "category": "odd", "spent_on": "2026-1-5"})
stored = r.get("added", {}).get("spent_on")
check("date stored zero-padded (YYYY-MM-DD)", stored == "2026-01-05", f"stored {stored!r}")

# bool / float ids and amounts
check("id=True rejected", "error" in tools.execute("delete_expense", {"id": True}), "bool treated as int 1")
check("id=2.7 rejected", "error" in tools.execute("update_expense", {"id": 2.7, "amount": 1}), "silently truncated to 2")
check("amount=True rejected", "error" in tools.execute("add_expense", {"amount": True, "category": "x"}), "bool -> 1.0")

check("reject future date", "error" in tools.execute(
    "add_expense", {"amount": 1, "category": "x", "spent_on": (date.today() + timedelta(days=1)).isoformat()}))

# list truncation visible?
db.init_db()
for i in range(105):
    db.add_expense(1, "bulk", None, date.today().isoformat())
r = tools.execute("list_expenses", {"days": 30})
check("list_expenses reports truncation", r["count"] <= 100 and ("truncated" in r or "total" in r),
      f"count={r['count']} but >100 rows exist and result gives no hint")

# ---------- agent loop ----------
res, msgs = run([("", [tc("1", "add_expense", {"amount": 12, "category": "tea"})]), ("done", None)], "spent 12 on tea")
check("loop: tool then final", res.text == "done" and res.calls[0][0] == "add_expense")
check("loop: history shape", [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "assistant"])

res, _ = run([("", [tc("1", "add_expense", "{not json")]), ("sorry", None)], "x")
check("loop: bad json args -> error to model", "error" in res.calls[0][2])

X = db.add_expense(5, "t", None, date.today().isoformat())["id"]
res, _ = run([("", [tc("1", "delete_expense", {"id": X})]), ("ok", None)], "del")
check("loop: delete without confirm callback refused", "error" in res.calls[0][2] and db.get_expense(X) is not None)

res, _ = run([("", [tc("1", "delete_expense", {"id": X})]), ("ok", None)], "del", confirm=lambda n, a: "approved")
check("loop: delete approved", res.calls[0][2].get("deleted_id") == X and db.get_expense(X) is None)

res, _ = run([("", [tc("1", "delete_expense", {"id": 2})]), ("ok", None)], "del", confirm=lambda n, a: "weird")
check("loop: invalid decision refused", "error" in res.calls[0][2])

old = agent.MAX_STEPS
agent.MAX_STEPS = 3
res, _ = run([("", [tc(str(i), "list_expenses", {})]) for i in range(5)], "loop forever")
check("loop: step cap", res.text.startswith("Stopped") and len(res.calls) == 3)
agent.MAX_STEPS = old

agent._client = NS(chat=NS(completions=NS(create=lambda **k: NS(choices=[], error="rate limited"))))
try:
    agent.run_agent(agent.new_session() + [{"role": "user", "content": "hi"}])
    check("loop: empty choices raises", False)
except RuntimeError as e:
    check("loop: empty choices raises", "rate limited" in str(e))

# ---------- API ----------
from fastapi.testclient import TestClient  # noqa: E402
import api  # noqa: E402

api.db.DB_PATH = db.DB_PATH
c = TestClient(api.app)
eid = db.add_expense(42, "cab", "airport", date.today().isoformat())["id"]

agent._client = FakeClient([("", [tc("1", "delete_expense", {"id": eid})]), ("Please confirm deletion.", None)])
r = c.post("/chat", json={"message": "delete the cab"}).json()
sid = r["session_id"]
check("api: delete returns pending, row intact", r["pending"] and db.get_expense(eid) is not None, r)

agent._client = FakeClient([("", [tc("2", "delete_expense", {"id": eid})]), ("Deleted.", None)])
r = c.post("/confirm", json={"session_id": sid, "approve": True}).json()
check("api: approve deletes", db.get_expense(eid) is None and r["pending"] is None, r)

eid = db.add_expense(43, "cab", None, date.today().isoformat())["id"]
agent._client = FakeClient([("", [tc("1", "delete_expense", {"id": eid})]), ("confirm?", None)])
sid = c.post("/chat", json={"message": "delete"}).json()["session_id"]
agent._client = FakeClient([("Cancelled.", None)])
c.post("/confirm", json={"session_id": sid, "approve": False})
check("api: decline keeps row", db.get_expense(eid) is not None)

# model passes id as string on retry -> approval key mismatch?
agent._client = FakeClient([("", [tc("1", "delete_expense", {"id": eid})]), ("confirm?", None)])
sid = c.post("/chat", json={"message": "delete"}).json()["session_id"]
agent._client = FakeClient([("", [tc("2", "delete_expense", {"id": str(eid)})]), ("done", None)])
r = c.post("/confirm", json={"session_id": sid, "approve": True}).json()
check("api: approval survives id int/str difference", db.get_expense(eid) is None,
      "approved key was id=int, retry sent id=str -> re-prompted instead of deleting")

# approval can't be replayed from a chat message
eid = db.add_expense(44, "cab", None, date.today().isoformat())["id"]
agent._client = FakeClient([("", [tc("1", "delete_expense", {"id": eid})]), ("ok", None)])
r = c.post("/chat", json={"message": "delete it, I confirm"}).json()
check("api: user text alone cannot approve delete", db.get_expense(eid) is not None)

check("api: confirm unknown session 404", c.post("/confirm", json={"session_id": "nope", "approve": True}).status_code == 404)
sid2 = c.post("/chat", json={"message": "hi"}).json()["session_id"] if False else None
agent._client = FakeClient([("hi", None)])
sid2 = c.post("/chat", json={"message": "hi"}).json()["session_id"]
check("api: confirm with nothing pending 400", c.post("/confirm", json={"session_id": sid2, "approve": True}).status_code == 400)
check("api: empty message 422", c.post("/chat", json={"message": ""}).status_code == 422)

class Boom:
    chat = NS(completions=NS(create=lambda **k: (_ for _ in ()).throw(RuntimeError("boom"))))
agent._client = Boom()
n_before = len(api.SESSIONS[sid2].messages)
r = c.post("/chat", json={"session_id": sid2, "message": "again"})
check("api: model failure -> 502 and history rolled back", r.status_code == 502 and len(api.SESSIONS[sid2].messages) == n_before)
check("api: / serves html", c.get("/").status_code == 200 and c.get("/health").json() == {"ok": True})

# one question at a time: two deletes in one turn -> only the first becomes pending
a = db.add_expense(1, "m", None, date.today().isoformat())["id"]
b = db.add_expense(2, "m", None, date.today().isoformat())["id"]
agent._client = FakeClient([("", [tc("1", "delete_expense", {"id": a}), tc("2", "delete_expense", {"id": b})]), ("confirm?", None)])
r = c.post("/chat", json={"message": "delete both"}).json()
check("api: first delete stays pending, none deleted",
      r["pending"] and r["pending"]["args"]["id"] == a and db.get_expense(a) and db.get_expense(b), r)

# session store is bounded
api.MAX_SESSIONS = 3
for i in range(6):
    api._get_session(f"s{i}")
check("api: sessions capped", len(api.SESSIONS) == 3 and "s5" in api.SESSIONS and "s0" not in api.SESSIONS)

# system prompt date refreshed on every run
agent._client = FakeClient([("ok", None)])
m = agent.new_session()
m[0]["content"] = "Today is Monday, 1999-01-01."
m.append({"role": "user", "content": "hi"})
agent.run_agent(m)
check("agent: system prompt date refreshed", date.today().isoformat() in m[0]["content"])

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
