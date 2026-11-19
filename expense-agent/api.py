"""HTTP API around the agent. Sessions are kept in memory (lost on restart)."""
import json
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
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


MAX_SESSIONS = 500  # oldest idle sessions are dropped beyond this, so memory stays bounded
SESSIONS: OrderedDict[str, Session] = OrderedDict()
_sessions_lock = threading.Lock()


def _get_session(sid: str) -> Session:
    with _sessions_lock:
        session = SESSIONS.get(sid)
        if session is None:
            session = SESSIONS[sid] = Session()
        SESSIONS.move_to_end(sid)
        while len(SESSIONS) > MAX_SESSIONS:
            oldest = next(iter(SESSIONS))
            if oldest == sid or SESSIONS[oldest].lock.locked():
                break  # never evict the session in use
            del SESSIONS[oldest]
        return session


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)


class ConfirmIn(BaseModel):
    session_id: str
    approve: bool


def _key(name: str, args: dict) -> str:
    return json.dumps([name, tools.canonical_args(name, args)], sort_keys=True)


def _turn(session: Session, text: str) -> dict:
    def confirm(name: str, args: dict) -> str:
        key = _key(name, args)
        if key in session.approved:
            session.approved.discard(key)
            return "approved"
        if session.pending is None:  # one question at a time: later calls in the same turn wait
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
    session = _get_session(sid)
    with session.lock:
        session.pending = None  # a new message means the user moved on
        out = _turn(session, body.message)
    return {"session_id": sid, **out}


@app.post("/confirm")
def confirm(body: ConfirmIn):
    with _sessions_lock:
        session = SESSIONS.get(body.session_id)
        if session is not None:
            SESSIONS.move_to_end(body.session_id)
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
        try:
            out = _turn(session, text)
        finally:
            session.approved.clear()  # never leave a stale approval behind
    return {"session_id": body.session_id, **out}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(Path(__file__).resolve().parent / "static" / "index.html")


@app.get("/health")
def health():
    return {"ok": True}
