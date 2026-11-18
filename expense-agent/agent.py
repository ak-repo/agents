"""The agent loop. Knows about the model and tool calling, nothing about expenses.

Talks to OpenRouter (or any OpenAI-compatible endpoint) with the `openai` SDK.
"""
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date

from openai import OpenAI

import config  # noqa: F401  (loads .env before the settings below are read)
import tools

MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")
BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
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

_client: OpenAI | None = None


def check_config() -> None:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key or key.startswith("your_"):  # empty, or the .env.example placeholder
        raise RuntimeError("OPENROUTER_API_KEY is not set. Put it in .env or export it before running.")


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        check_config()
        _client = OpenAI(
            base_url=BASE_URL,
            api_key=os.environ["OPENROUTER_API_KEY"],
            default_headers={"X-Title": "Expense Agent"},  # optional app name shown on OpenRouter
            max_retries=2,
            timeout=60,
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


def _parse_args(raw) -> tuple[dict, str | None]:
    """Tool arguments arrive as a JSON string. Returns (args, error_or_None)."""
    if not raw:
        return {}, None
    try:
        args = json.loads(raw)
    except (TypeError, ValueError):
        return {}, "tool arguments were not valid JSON"
    if not isinstance(args, dict):
        return {}, "tool arguments must be a JSON object"
    return args, None


def run_agent(messages: list, confirm=None, verbose: bool = False) -> AgentResult:
    """Run the loop until the model gives a final text answer.

    messages: the full history (mutated in place: assistant + tool messages are appended).
    confirm:  callable(name, args) -> "approved" | "declined" | "pending".
    """
    client = _get_client()
    calls = []

    for _ in range(MAX_STEPS):
        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=tools.TOOL_SCHEMAS)
        if not resp.choices:  # OpenRouter can answer 200 with an error body and no choices
            raise RuntimeError(f"model returned no answer: {getattr(resp, 'error', None) or 'unknown error'}")
        msg = resp.choices[0].message

        entry = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"},
                }
                for c in msg.tool_calls
            ]
        messages.append(entry)

        if not msg.tool_calls:  # model is done
            return AgentResult(msg.content or "", calls)

        for call in msg.tool_calls:
            name = call.function.name
            args, bad = _parse_args(call.function.arguments)
            result = {"error": bad} if bad else _run_tool(name, args, confirm)
            calls.append((name, args, result))
            if verbose:
                print(f"  [tool] {name}({json.dumps(args)}) -> {json.dumps(result)}", file=sys.stderr)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result),
            })

    return AgentResult("Stopped: too many steps without a final answer.", calls)
