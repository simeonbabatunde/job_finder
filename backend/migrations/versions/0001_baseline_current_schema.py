"""baseline current schema

Revision ID: 0001_baseline_current_schema
Revises:
Create Date: 2026-06-03 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
from sqlmodel import SQLModel

from app import models  # noqa: F401

revision: str = "0001_baseline_current_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    SQLModel.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    SQLModel.metadata.drop_all(bind=op.get_bind())
