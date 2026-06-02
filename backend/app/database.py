from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine, Session
from typing import Callable, Generator

import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/job_hunter")

engine = create_engine(DATABASE_URL, echo=True)

def migrate_user_scope_resume_preferences(connection):
    """Add ownership columns for databases created before user-scoped setup data."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())

    for table_name, index_name, date_column in (
        ("resume", "ix_resume_user_upload", "upload_date"),
        ("jobpreference", "ix_jobpreference_user_created", "created_at"),
    ):
        if table_name not in table_names:
            continue

        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "user_id" not in columns:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN user_id INTEGER"))

        connection.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON {table_name} (user_id, {date_column} DESC)"
            )
        )

        if "user" in table_names:
            connection.execute(
                text(
                    f"""
                    UPDATE {table_name}
                    SET user_id = (SELECT id FROM "user" LIMIT 1)
                    WHERE user_id IS NULL
                    AND (SELECT COUNT(*) FROM "user") = 1
                    """
                )
            )

def migrate_application_link_resolution(connection):
    """Add source/resolved URL metadata for auto-apply link resolution."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "application" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("application")}
    column_defs = {
        "source_url": "VARCHAR",
        "resolved_url": "VARCHAR",
        "source_type": "VARCHAR",
        "ats_type": "VARCHAR",
        "resolution_status": "VARCHAR DEFAULT 'unresolved'",
        "resolution_notes": "VARCHAR",
    }
    for column_name, column_def in column_defs.items():
        if column_name not in columns:
            connection.execute(text(f"ALTER TABLE application ADD COLUMN {column_name} {column_def}"))

    connection.execute(
        text(
            """
            UPDATE application
            SET source_url = job_url
            WHERE source_url IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE application
            SET resolution_status = 'unresolved'
            WHERE resolution_status IS NULL
            """
        )
    )

def migrate_application_answer_profile(connection):
    """Ensure application answer vault tables have the expected user index."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "applicationanswerprofile" not in table_names:
        return

    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "ix_applicationanswerprofile_user_unique "
            "ON applicationanswerprofile (user_id)"
        )
    )

def migrate_application_fill_review(connection):
    """Ensure fill-review attempts are indexed for application history lookups."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "applicationfillreview" not in table_names:
        return

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_applicationfillreview_application_created "
            "ON applicationfillreview (application_id, created_at DESC)"
        )
    )

SCHEMA_MIGRATIONS: tuple[tuple[str, Callable], ...] = (
    ("0001_user_scope_resume_preferences", migrate_user_scope_resume_preferences),
    ("0002_application_link_resolution", migrate_application_link_resolution),
    ("0003_application_answer_profile", migrate_application_answer_profile),
    ("0004_application_fill_review", migrate_application_fill_review),
)

def ensure_schema_migrations_table(connection):
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )

def has_migration(connection, migration_id: str):
    return connection.execute(
        text("SELECT 1 FROM schema_migrations WHERE id = :id"),
        {"id": migration_id},
    ).first() is not None

def record_migration(connection, migration_id: str):
    connection.execute(
        text("INSERT INTO schema_migrations (id) VALUES (:id)"),
        {"id": migration_id},
    )

def run_schema_migrations():
    with engine.begin() as connection:
        ensure_schema_migrations_table(connection)
        for migration_id, migration in SCHEMA_MIGRATIONS:
            if has_migration(connection, migration_id):
                continue
            migration(connection)
            record_migration(connection, migration_id)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    run_schema_migrations()

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
