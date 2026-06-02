import asyncio
import os

from app.api.endpoints import run_next_queued_agent_run
from app.database import create_db_and_tables


def get_poll_seconds() -> float:
    try:
        return max(float(os.getenv("AGENT_WORKER_POLL_SECONDS", "2")), 0.2)
    except ValueError:
        return 2.0


async def run_worker_loop():
    create_db_and_tables()
    poll_seconds = get_poll_seconds()
    print(f"Agent worker started; polling every {poll_seconds:g}s")

    while True:
        processed = await run_next_queued_agent_run()
        if not processed:
            await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    asyncio.run(run_worker_loop())
