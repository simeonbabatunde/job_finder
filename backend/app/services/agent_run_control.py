from __future__ import annotations

from typing import Optional

from sqlmodel import Session

from app.database import engine
from app.models import AgentRun
from app.time_utils import utc_now


CANCEL_REQUESTED_STATUS = "cancel_requested"
CANCELED_STATUS = "canceled"
CANCELABLE_AGENT_RUN_STATUSES = {"queued", "running", CANCEL_REQUESTED_STATUS}


def cancellation_log_message() -> str:
    return "Matching workflow stopped by user."


def is_agent_run_cancel_requested(agent_run_id: Optional[int]) -> bool:
    if not agent_run_id:
        return False

    with Session(engine) as session:
        run = session.get(AgentRun, agent_run_id)
        return bool(run and run.status in {CANCEL_REQUESTED_STATUS, CANCELED_STATUS})


def canceled_agent_state(logs: list[str] | None = None) -> dict:
    existing_logs = logs or []
    message = cancellation_log_message()
    if existing_logs and existing_logs[-1] == message:
        next_logs = existing_logs
    else:
        next_logs = existing_logs + [message]
    return {
        "application_status": CANCELED_STATUS,
        "logs": next_logs,
    }


def mark_run_canceled(session: Session, run: AgentRun, *, message: str | None = None) -> AgentRun:
    log_message = message or cancellation_log_message()
    run.status = CANCELED_STATUS
    run.error = None
    run.completed_at = run.completed_at or utc_now()
    if not run.logs or run.logs[-1] != log_message:
        run.logs = (run.logs or []) + [log_message]
    session.add(run)
    return run
