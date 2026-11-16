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
