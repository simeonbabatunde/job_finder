import asyncio
import os
import socket
from contextlib import suppress

from sqlmodel import Session, select

from app.api.endpoints import claim_next_queued_agent_run, execute_agent_run
from app.database import create_db_and_tables, engine
from app.models import WorkerHeartbeat
from app.time_utils import utc_now


def get_poll_seconds() -> float:
    try:
        return max(float(os.getenv("AGENT_WORKER_POLL_SECONDS", "2")), 0.2)
    except ValueError:
        return 2.0


def get_heartbeat_seconds() -> float:
    try:
        return max(float(os.getenv("AGENT_WORKER_HEARTBEAT_SECONDS", "10")), 1.0)
    except ValueError:
        return 10.0


def get_worker_id() -> str:
    configured_id = os.getenv("AGENT_WORKER_ID", "").strip()
    if configured_id:
        return configured_id
    return f"{socket.gethostname()}-{os.getpid()}"


def record_worker_heartbeat(
    worker_id: str,
    status: str,
    current_agent_run_id: int | None = None,
    details: dict | None = None,
):
    try:
        with Session(engine) as session:
            heartbeat = session.exec(
                select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id)
            ).first()
            if not heartbeat:
                heartbeat = WorkerHeartbeat(worker_id=worker_id)
            heartbeat.status = status
            heartbeat.last_seen_at = utc_now()
            heartbeat.current_agent_run_id = current_agent_run_id
            heartbeat.details = details or {}
            session.add(heartbeat)
            session.commit()
    except Exception as exc:
        print(f"Agent worker heartbeat failed: {exc}")


async def maintain_running_heartbeat(
    worker_id: str,
    agent_run_id: int,
    heartbeat_seconds: float,
):
    while True:
        record_worker_heartbeat(
            worker_id,
            "running",
            current_agent_run_id=agent_run_id,
            details={"heartbeat_seconds": heartbeat_seconds},
        )
        await asyncio.sleep(heartbeat_seconds)


async def run_worker_loop():
    create_db_and_tables()
    poll_seconds = get_poll_seconds()
    heartbeat_seconds = get_heartbeat_seconds()
    worker_id = get_worker_id()
    record_worker_heartbeat(
        worker_id,
        "starting",
        details={"poll_seconds": poll_seconds, "heartbeat_seconds": heartbeat_seconds},
    )
    print(f"Agent worker {worker_id} started; polling every {poll_seconds:g}s")

    while True:
        record_worker_heartbeat(
            worker_id,
            "polling",
            details={"poll_seconds": poll_seconds, "heartbeat_seconds": heartbeat_seconds},
        )
        claim = claim_next_queued_agent_run()
        if not claim:
            record_worker_heartbeat(
                worker_id,
                "idle",
                details={"poll_seconds": poll_seconds, "heartbeat_seconds": heartbeat_seconds},
            )
            await asyncio.sleep(poll_seconds)
            continue

        agent_run_id = claim["agent_run_id"]
        record_worker_heartbeat(
            worker_id,
            "running",
            current_agent_run_id=agent_run_id,
            details={"heartbeat_seconds": heartbeat_seconds},
        )
        heartbeat_task = asyncio.create_task(
            maintain_running_heartbeat(worker_id, agent_run_id, heartbeat_seconds)
        )
        try:
            await execute_agent_run(
                agent_run_id,
                claim["user_id"],
                claim["auto_apply"],
            )
            record_worker_heartbeat(
                worker_id,
                "idle",
                details={"last_agent_run_id": agent_run_id},
            )
        except Exception as exc:
            record_worker_heartbeat(
                worker_id,
                "error",
                current_agent_run_id=agent_run_id,
                details={"error": str(exc)},
            )
            raise
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task


if __name__ == "__main__":
    asyncio.run(run_worker_loop())
