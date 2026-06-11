"""add user billing fields

Revision ID: 0004_user_billing_fields
Revises: 0003_application_answer_audit
Create Date: 2026-06-08 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_user_billing_fields"
down_revision: Union[str, Sequence[str], None] = "0003_application_answer_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _user_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user" not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns("user")}


def upgrade() -> None:
    columns = _user_columns()
    additions = (
        ("subscription_status", sa.Column("subscription_status", sa.String(), nullable=True)),
        ("subscription_current_period_end", sa.Column("subscription_current_period_end", sa.DateTime(), nullable=True)),
        ("subscription_cancel_at_period_end", sa.Column("subscription_cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("stripe_customer_id", sa.Column("stripe_customer_id", sa.String(), nullable=True)),
        ("stripe_subscription_id", sa.Column("stripe_subscription_id", sa.String(), nullable=True)),
        ("stripe_price_id", sa.Column("stripe_price_id", sa.String(), nullable=True)),
        ("billing_updated_at", sa.Column("billing_updated_at", sa.DateTime(), nullable=True)),
    )
    for column_name, column in additions:
        if column_name not in columns:
            op.add_column("user", column)

    op.execute(
        """
        UPDATE "user"
        SET subscription_cancel_at_period_end = FALSE
        WHERE subscription_cancel_at_period_end IS NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_subscription_status ON \"user\" (subscription_status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_stripe_customer_id ON \"user\" (stripe_customer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_stripe_subscription_id ON \"user\" (stripe_subscription_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_stripe_subscription_id")
    op.execute("DROP INDEX IF EXISTS ix_user_stripe_customer_id")
    op.execute("DROP INDEX IF EXISTS ix_user_subscription_status")
    columns = _user_columns()
    for column_name in (
        "billing_updated_at",
        "stripe_price_id",
        "stripe_subscription_id",
        "stripe_customer_id",
        "subscription_cancel_at_period_end",
        "subscription_current_period_end",
        "subscription_status",
    ):
        if column_name in columns:
            op.drop_column("user", column_name)
