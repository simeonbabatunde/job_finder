"""add worker heartbeat table

Revision ID: 0002_worker_heartbeat
Revises: 0001_baseline_current_schema
Create Date: 2026-06-03 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002_worker_heartbeat"
down_revision: Union[str, Sequence[str], None] = "0001_baseline_current_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    id_column = "SERIAL PRIMARY KEY" if bind.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS workerheartbeat (
            id {id_column},
            worker_id VARCHAR NOT NULL UNIQUE,
            status VARCHAR NOT NULL DEFAULT 'starting',
            last_seen_at TIMESTAMP NOT NULL,
            current_agent_run_id INTEGER,
            details JSON,
            FOREIGN KEY(current_agent_run_id) REFERENCES agentrun (id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workerheartbeat_worker_id "
        "ON workerheartbeat (worker_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workerheartbeat_status "
        "ON workerheartbeat (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workerheartbeat_last_seen_at "
        "ON workerheartbeat (last_seen_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workerheartbeat_current_agent_run_id "
        "ON workerheartbeat (current_agent_run_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_workerheartbeat_current_agent_run_id")
    op.execute("DROP INDEX IF EXISTS ix_workerheartbeat_last_seen_at")
    op.execute("DROP INDEX IF EXISTS ix_workerheartbeat_status")
    op.execute("DROP INDEX IF EXISTS ix_workerheartbeat_worker_id")
    op.execute("DROP TABLE IF EXISTS workerheartbeat")
