from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine, Session
from typing import Callable, Generator
from pathlib import Path

import json
import os

from app.observability import log_event

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/jobmatchkit")
USE_ALEMBIC_MIGRATIONS = os.getenv("USE_ALEMBIC_MIGRATIONS", "").lower() in {"1", "true", "yes"}
BACKEND_DIR = Path(__file__).resolve().parents[1]
STARTUP_MIGRATION_LOCK_ID = 741319502

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

def migrate_application_fill_review_artifacts(connection):
    """Add local artifact references for fill-review screenshots and traces."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "applicationfillreview" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("applicationfillreview")}
    for column_name in ("screenshot_path", "trace_path"):
        if column_name not in columns:
            connection.execute(
                text(f"ALTER TABLE applicationfillreview ADD COLUMN {column_name} VARCHAR")
            )

def migrate_agent_run_claims(connection):
    """Add worker-claim metadata for durable queued agent runs."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "agentrun" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("agentrun")}
    if "claimed_at" not in columns:
        connection.execute(text("ALTER TABLE agentrun ADD COLUMN claimed_at TIMESTAMP"))
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_agentrun_status_claimed "
            "ON agentrun (status, claimed_at)"
        )
    )

def migrate_auth_sessions(connection):
    """Create server-side auth session records for token invalidation."""
    id_column = "SERIAL PRIMARY KEY" if connection.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS authsession (
                id {id_column},
                user_id INTEGER NOT NULL,
                token_id VARCHAR NOT NULL UNIQUE,
                refresh_token_hash VARCHAR,
                expires_at TIMESTAMP NOT NULL,
                refresh_expires_at TIMESTAMP,
                revoked_at TIMESTAMP,
                rotated_at TIMESTAMP,
                created_at TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES "user" (id)
            )
            """
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_authsession_token_id "
            "ON authsession (token_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_authsession_user_id "
            "ON authsession (user_id)"
        )
    )

def migrate_auth_session_refresh_tokens(connection):
    """Add refresh-token rotation metadata to auth sessions."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "authsession" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("authsession")}
    if "refresh_token_hash" not in columns:
        connection.execute(text("ALTER TABLE authsession ADD COLUMN refresh_token_hash VARCHAR"))
    if "refresh_expires_at" not in columns:
        connection.execute(text("ALTER TABLE authsession ADD COLUMN refresh_expires_at TIMESTAMP"))
    if "rotated_at" not in columns:
        connection.execute(text("ALTER TABLE authsession ADD COLUMN rotated_at TIMESTAMP"))

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_authsession_refresh_expires_at "
            "ON authsession (refresh_expires_at)"
        )
    )

def migrate_application_submit_settings(connection):
    """Create user-scoped guardrails for future final-submit confirmation."""
    id_column = "SERIAL PRIMARY KEY" if connection.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    bool_false = "FALSE" if connection.dialect.name == "postgresql" else "0"
    bool_true = "TRUE" if connection.dialect.name == "postgresql" else "1"
    connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS applicationsubmitsettings (
                id {id_column},
                user_id INTEGER NOT NULL UNIQUE,
                true_submit_enabled BOOLEAN NOT NULL DEFAULT {bool_false},
                require_human_confirmation BOOLEAN NOT NULL DEFAULT {bool_true},
                min_fit_score INTEGER NOT NULL DEFAULT 80,
                max_submits_per_day INTEGER NOT NULL DEFAULT 5,
                allowed_companies JSON,
                denied_companies JSON,
                allowed_domains JSON,
                denied_domains JSON,
                allowed_job_title_keywords JSON,
                consented_at TIMESTAMP,
                updated_at TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES "user" (id)
            )
            """
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "ix_applicationsubmitsettings_user_unique "
            "ON applicationsubmitsettings (user_id)"
        )
    )

def migrate_auto_apply_attempts(connection):
    """Create auditable workflow records for fill-review and final-confirmation attempts."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    id_column = "SERIAL PRIMARY KEY" if connection.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    timestamp_default = "CURRENT_TIMESTAMP"
    if "autoapplyattempt" not in table_names:
        connection.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS autoapplyattempt (
                    id {id_column},
                    user_id INTEGER NOT NULL,
                    application_id INTEGER NOT NULL,
                    agent_run_id INTEGER,
                    fill_review_id INTEGER,
                    job_url VARCHAR NOT NULL,
                    job_title VARCHAR,
                    company VARCHAR,
                    ats_type VARCHAR,
                    mode VARCHAR NOT NULL DEFAULT 'fill_for_review',
                    status VARCHAR NOT NULL DEFAULT 'queued',
                    confidence_score FLOAT NOT NULL DEFAULT 0,
                    blocked_reason VARCHAR,
                    filled_fields JSON,
                    missing_fields JSON,
                    blockers JSON,
                    readiness_snapshot JSON,
                    submit_control JSON,
                    screenshot_path VARCHAR,
                    trace_path VARCHAR,
                    submitted_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT {timestamp_default},
                    updated_at TIMESTAMP DEFAULT {timestamp_default},
                    FOREIGN KEY(user_id) REFERENCES "user" (id),
                    FOREIGN KEY(application_id) REFERENCES application (id),
                    FOREIGN KEY(agent_run_id) REFERENCES agentrun (id),
                    FOREIGN KEY(fill_review_id) REFERENCES applicationfillreview (id)
                )
                """
            )
        )

    for index_name, columns in (
        ("ix_autoapplyattempt_user_created", "user_id, created_at DESC"),
        ("ix_autoapplyattempt_application_created", "application_id, created_at DESC"),
        ("ix_autoapplyattempt_status", "status"),
        ("ix_autoapplyattempt_fill_review", "fill_review_id"),
    ):
        connection.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON autoapplyattempt ({columns})"
            )
        )

    if "autoapplyaudit" in table_names:
        columns = {column["name"] for column in inspector.get_columns("autoapplyaudit")}
        if "auto_apply_attempt_id" not in columns:
            connection.execute(text("ALTER TABLE autoapplyaudit ADD COLUMN auto_apply_attempt_id INTEGER"))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_autoapplyaudit_attempt "
                "ON autoapplyaudit (auto_apply_attempt_id)"
            )
        )

def migrate_application_prescreen(connection):
    """Add conservative pre-screen metadata used before full AI analysis."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "application" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("application")}
    if "pre_screen_status" not in columns:
        connection.execute(
            text("ALTER TABLE application ADD COLUMN pre_screen_status VARCHAR DEFAULT 'not_screened'")
        )
    if "pre_screen_reasons" not in columns:
        connection.execute(text("ALTER TABLE application ADD COLUMN pre_screen_reasons JSON"))

    empty_json = "'[]'::json" if connection.dialect.name == "postgresql" else "'[]'"
    connection.execute(
        text(
            """
            UPDATE application
            SET pre_screen_status = 'not_screened'
            WHERE pre_screen_status IS NULL
            """
        )
    )
    connection.execute(
        text(
            f"""
            UPDATE application
            SET pre_screen_reasons = {empty_json}
            WHERE pre_screen_reasons IS NULL
            """
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_application_user_prescreen_score "
            "ON application (user_id, pre_screen_status, fit_score DESC)"
        )
    )

def migrate_auto_apply_attempt_steps(connection):
    """Add step-level workflow telemetry to auto-apply attempts."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "autoapplyattempt" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("autoapplyattempt")}
    if "steps" not in columns:
        connection.execute(text("ALTER TABLE autoapplyattempt ADD COLUMN steps JSON"))

    empty_json = "'[]'::json" if connection.dialect.name == "postgresql" else "'[]'"
    connection.execute(
        text(
            f"""
            UPDATE autoapplyattempt
            SET steps = {empty_json}
            WHERE steps IS NULL
            """
        )
    )

def migrate_worker_heartbeat(connection):
    """Create worker liveness records for deployment health checks."""
    id_column = "SERIAL PRIMARY KEY" if connection.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    json_type = "JSON"
    connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS workerheartbeat (
                id {id_column},
                worker_id VARCHAR NOT NULL UNIQUE,
                status VARCHAR NOT NULL DEFAULT 'starting',
                last_seen_at TIMESTAMP NOT NULL,
                current_agent_run_id INTEGER,
                details {json_type},
                FOREIGN KEY(current_agent_run_id) REFERENCES agentrun (id)
            )
            """
        )
    )
    for index_name, columns in (
        ("ix_workerheartbeat_worker_id", "worker_id"),
        ("ix_workerheartbeat_status", "status"),
        ("ix_workerheartbeat_last_seen_at", "last_seen_at"),
        ("ix_workerheartbeat_current_agent_run_id", "current_agent_run_id"),
    ):
        connection.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON workerheartbeat ({columns})"
            )
        )

def migrate_application_answer_audit(connection):
    """Create answer-vault access audit records without storing answer values."""
    id_column = "SERIAL PRIMARY KEY" if connection.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    connection.execute(
        text(
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
    )
    for index_name, columns in (
        ("ix_applicationansweraudit_user_created", "user_id, created_at DESC"),
        ("ix_applicationansweraudit_user_id", "user_id"),
        ("ix_applicationansweraudit_application_id", "application_id"),
        ("ix_applicationansweraudit_action", "action"),
        ("ix_applicationansweraudit_created_at", "created_at"),
    ):
        connection.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON applicationansweraudit ({columns})"
            )
        )

def migrate_user_billing_fields(connection):
    """Add Stripe billing metadata and subscription state to users."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "user" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("user")}
    column_defs = {
        "subscription_status": "VARCHAR",
        "subscription_current_period_end": "TIMESTAMP",
        "subscription_cancel_at_period_end": "BOOLEAN DEFAULT FALSE",
        "stripe_customer_id": "VARCHAR",
        "stripe_subscription_id": "VARCHAR",
        "stripe_price_id": "VARCHAR",
        "billing_updated_at": "TIMESTAMP",
    }
    for column_name, column_def in column_defs.items():
        if column_name not in columns:
            connection.execute(text(f"ALTER TABLE \"user\" ADD COLUMN {column_name} {column_def}"))

    connection.execute(
        text(
            """
            UPDATE "user"
            SET subscription_cancel_at_period_end = FALSE
            WHERE subscription_cancel_at_period_end IS NULL
            """
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_user_subscription_status "
            "ON \"user\" (subscription_status)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_user_stripe_customer_id "
            "ON \"user\" (stripe_customer_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_user_stripe_subscription_id "
            "ON \"user\" (stripe_subscription_id)"
        )
    )


def migrate_matching_profiles(connection):
    """Create saved matching profiles and backfill a default profile per user."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "user" not in table_names:
        return

    id_column = "SERIAL PRIMARY KEY" if connection.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    bool_false = "FALSE" if connection.dialect.name == "postgresql" else "0"
    json_type = "JSON"
    connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS matchingprofile (
                id {id_column},
                user_id INTEGER NOT NULL,
                name VARCHAR NOT NULL DEFAULT 'Default profile',
                resume_id INTEGER,
                role {json_type},
                experience_level {json_type},
                location {json_type},
                job_type {json_type},
                target_companies {json_type},
                min_match_score INTEGER NOT NULL DEFAULT 70,
                posted_within_days INTEGER NOT NULL DEFAULT 7,
                is_default BOOLEAN NOT NULL DEFAULT {bool_false},
                is_archived BOOLEAN NOT NULL DEFAULT {bool_false},
                last_used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES "user" (id),
                FOREIGN KEY(resume_id) REFERENCES resume (id)
            )
            """
        )
    )

    for index_name, columns in (
        ("ix_matchingprofile_user_default", "user_id, is_default"),
        ("ix_matchingprofile_user_archived", "user_id, is_archived"),
        ("ix_matchingprofile_resume_id", "resume_id"),
    ):
        connection.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON matchingprofile ({columns})"
            )
        )

    for table_name, column_defs in (
        (
            "agentrun",
            {
                "matching_profile_id": "INTEGER",
                "resume_id": "INTEGER",
            },
        ),
        (
            "application",
            {
                "matching_profile_id": "INTEGER",
                "agent_run_id": "INTEGER",
            },
        ),
    ):
        if table_name not in table_names:
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, column_def in column_defs.items():
            if column_name not in columns:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"))
        for index_name, columns_sql in (
            (f"ix_{table_name}_matching_profile", "matching_profile_id"),
            (f"ix_{table_name}_agent_run", "agent_run_id") if table_name == "application" else (f"ix_{table_name}_resume", "resume_id"),
        ):
            connection.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON {table_name} ({columns_sql})"
                )
            )

    empty_json = "[]"
    default_experience = '["Intermediate"]'
    default_job_type = '["Full-time"]'

    def json_value(value, fallback):
        if value is None:
            return fallback
        return value if isinstance(value, str) else json.dumps(value)

    users = connection.execute(text('SELECT id FROM "user"')).mappings().all()
    for user in users:
        user_id = user["id"]
        existing = connection.execute(
            text("SELECT id FROM matchingprofile WHERE user_id = :user_id LIMIT 1"),
            {"user_id": user_id},
        ).first()
        if existing:
            continue

        resume_row = None
        if "resume" in table_names:
            resume_row = connection.execute(
                text(
                    "SELECT id FROM resume WHERE user_id = :user_id "
                    "ORDER BY upload_date DESC LIMIT 1"
                ),
                {"user_id": user_id},
            ).mappings().first()

        pref_row = None
        if "jobpreference" in table_names:
            pref_row = connection.execute(
                text(
                    "SELECT role, experience_level, location, job_type, target_companies, "
                    "min_match_score, posted_within_days FROM jobpreference "
                    "WHERE user_id = :user_id ORDER BY created_at DESC LIMIT 1"
                ),
                {"user_id": user_id},
            ).mappings().first()

        connection.execute(
            text(
                """
                INSERT INTO matchingprofile (
                    user_id, name, resume_id, role, experience_level, location,
                    job_type, target_companies, min_match_score, posted_within_days,
                    is_default, is_archived, created_at, updated_at
                ) VALUES (
                    :user_id, :name, :resume_id, :role, :experience_level, :location,
                    :job_type, :target_companies, :min_match_score, :posted_within_days,
                    :is_default, :is_archived, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "user_id": user_id,
                "name": "Default profile",
                "resume_id": resume_row["id"] if resume_row else None,
                "role": json_value(pref_row["role"] if pref_row else None, empty_json),
                "experience_level": json_value(pref_row["experience_level"] if pref_row else None, default_experience),
                "location": json_value(pref_row["location"] if pref_row else None, empty_json),
                "job_type": json_value(pref_row["job_type"] if pref_row else None, default_job_type),
                "target_companies": json_value(pref_row["target_companies"] if pref_row else None, empty_json),
                "min_match_score": pref_row["min_match_score"] if pref_row and pref_row["min_match_score"] is not None else 70,
                "posted_within_days": pref_row["posted_within_days"] if pref_row and pref_row["posted_within_days"] is not None else 7,
                "is_default": True,
                "is_archived": False,
            },
        )

        profile_row = connection.execute(
            text(
                """
                SELECT id, resume_id FROM matchingprofile
                WHERE user_id = :user_id
                ORDER BY is_default DESC, updated_at DESC, id ASC
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).mappings().first()
        if not profile_row:
            continue

        if "agentrun" in table_names:
            connection.execute(
                text(
                    """
                    UPDATE agentrun
                    SET matching_profile_id = :profile_id,
                        resume_id = COALESCE(resume_id, :resume_id)
                    WHERE user_id = :user_id
                    AND matching_profile_id IS NULL
                    """
                ),
                {
                    "profile_id": profile_row["id"],
                    "resume_id": profile_row["resume_id"],
                    "user_id": user_id,
                },
            )

        if "application" in table_names:
            connection.execute(
                text(
                    """
                    UPDATE application
                    SET matching_profile_id = :profile_id
                    WHERE user_id = :user_id
                    AND matching_profile_id IS NULL
                    """
                ),
                {"profile_id": profile_row["id"], "user_id": user_id},
            )

SCHEMA_MIGRATIONS: tuple[tuple[str, Callable], ...] = (
    ("0001_user_scope_resume_preferences", migrate_user_scope_resume_preferences),
    ("0002_application_link_resolution", migrate_application_link_resolution),
    ("0003_application_answer_profile", migrate_application_answer_profile),
    ("0004_application_fill_review", migrate_application_fill_review),
    ("0005_application_fill_review_artifacts", migrate_application_fill_review_artifacts),
    ("0006_agent_run_claims", migrate_agent_run_claims),
    ("0007_auth_sessions", migrate_auth_sessions),
    ("0008_application_submit_settings", migrate_application_submit_settings),
    ("0009_auto_apply_attempts", migrate_auto_apply_attempts),
    ("0010_application_prescreen", migrate_application_prescreen),
    ("0011_auto_apply_attempt_steps", migrate_auto_apply_attempt_steps),
    ("0012_auth_session_refresh_tokens", migrate_auth_session_refresh_tokens),
    ("0013_worker_heartbeat", migrate_worker_heartbeat),
    ("0014_application_answer_audit", migrate_application_answer_audit),
    ("0015_user_billing_fields", migrate_user_billing_fields),
    ("0016_matching_profiles", migrate_matching_profiles),
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

def run_alembic_migrations() -> bool:
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:
        log_event("database.alembic_unavailable", level="warning", reason="import_error")
        return False

    alembic_ini = BACKEND_DIR / "alembic.ini"
    if not alembic_ini.exists():
        log_event("database.alembic_unavailable", level="warning", reason="missing_config")
        return False

    config = Config(str(alembic_ini))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    lock_connection = engine.connect()
    try:
        if lock_connection.dialect.name == "postgresql":
            lock_connection.execute(
                text("SELECT pg_advisory_lock(:lock_id)"),
                {"lock_id": STARTUP_MIGRATION_LOCK_ID},
            )
        command.upgrade(config, "head")
    finally:
        if lock_connection.dialect.name == "postgresql":
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": STARTUP_MIGRATION_LOCK_ID},
            )
        lock_connection.close()
    return True

def create_db_and_tables():
    if USE_ALEMBIC_MIGRATIONS and run_alembic_migrations():
        return
    SQLModel.metadata.create_all(engine)
    run_schema_migrations()

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
