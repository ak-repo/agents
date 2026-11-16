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
