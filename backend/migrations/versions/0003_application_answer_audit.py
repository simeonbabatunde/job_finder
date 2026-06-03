"""add application answer audit table

Revision ID: 0003_application_answer_audit
Revises: 0002_worker_heartbeat
Create Date: 2026-06-03 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003_application_answer_audit"
down_revision: Union[str, Sequence[str], None] = "0002_worker_heartbeat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    id_column = "SERIAL PRIMARY KEY" if bind.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS applicationansweraudit (
            id {id_column},
            user_id INTEGER NOT NULL,
            application_id INTEGER,
            action VARCHAR NOT NULL,
            access_reason VARCHAR,
            source VARCHAR,
            fields JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES "user" (id),
            FOREIGN KEY(application_id) REFERENCES application (id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_applicationansweraudit_user_created "
        "ON applicationansweraudit (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_applicationansweraudit_user_id "
        "ON applicationansweraudit (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_applicationansweraudit_application_id "
        "ON applicationansweraudit (application_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_applicationansweraudit_action "
        "ON applicationansweraudit (action)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_applicationansweraudit_created_at "
        "ON applicationansweraudit (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_applicationansweraudit_created_at")
    op.execute("DROP INDEX IF EXISTS ix_applicationansweraudit_action")
    op.execute("DROP INDEX IF EXISTS ix_applicationansweraudit_application_id")
    op.execute("DROP INDEX IF EXISTS ix_applicationansweraudit_user_id")
    op.execute("DROP INDEX IF EXISTS ix_applicationansweraudit_user_created")
    op.execute("DROP TABLE IF EXISTS applicationansweraudit")
