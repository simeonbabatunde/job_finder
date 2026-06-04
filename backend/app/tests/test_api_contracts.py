import base64
import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

os.environ["AUTH_SECRET_KEY"] = "test-secret"
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/job_finder_test.db"
os.environ["FILL_REVIEW_ARTIFACT_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from app.api import endpoints
from app.agent import nodes
from app.agent.nodes import apply_browser, submit_application
from app.database import engine, run_schema_migrations
from app.models import (
    AgentRun,
    Application,
    ApplicationAnswerAudit,
    ApplicationAnswerProfile,
    ApplicationFillReview,
    ApplicationSubmitSettings,
    AutoApplyAudit,
    AutoApplyAttempt,
    Profile,
    ScraperConfig,
    User,
    WorkerHeartbeat,
)
from app.services import job_search as job_search_module
from app.services.application_fill_review import ApplicationFillReviewService, FillReviewResult, SubmitControlDetection
from app.services.application_link_resolver import ApplicationLinkResolver, LinkResolutionResult
from app.services.browser_apply import BrowserApplyService
from app.services.application_answer_rotation import reencrypt_application_answer_profiles
from app.services.field_encryption import (
    ENCRYPTED_VALUE_PREFIX,
    decrypt_text,
    decrypt_text_with_key_status,
    encrypt_text,
)
from app.services.fill_review_artifacts import FillReviewArtifactStore
from app.time_utils import utc_now
from app.services.job_pre_screen import JobPreScreenService
from app.services.persistence import PersistenceService
import main as api_main
from main import app


def unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}@example.test"


def register_user(client: TestClient, prefix: str = "user"):
    email = unique_email(prefix)
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "Password123!",
            "profile": {
                "first_name": "Test",
                "last_name": "User",
                "phone": "555-0100",
                "location": "Remote",
            },
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return data, {"Authorization": f"Bearer {data['access_token']}"}


def prepare_agent_setup(client: TestClient, headers: dict):
    prefs_response = client.post(
        "/preferences",
        json={
            "role": ["Software Engineer"],
            "experience_level": ["Senior"],
            "location": ["Remote"],
            "job_type": ["Full-time"],
            "target_companies": [],
            "min_match_score": 75,
            "posted_within_days": 7,
        },
        headers=headers,
    )
    assert prefs_response.status_code == 200, prefs_response.text

    resume_response = client.post(
        "/upload-resume",
        files={"file": ("resume.txt", b"Python FastAPI SQL", "text/plain")},
        headers=headers,
    )
    assert resume_response.status_code == 200, resume_response.text


class FakeAgentGraph:
    async def ainvoke(self, state):
        return {
            "logs": state.get("logs", []) + ["Fake search complete"],
            "applications_submitted": ["https://example.test/fake-role"],
            "found_jobs": [
                {
                    "title": "Fake Role",
                    "company": "Acme",
                    "url": "https://example.test/fake-role",
                    "fit_score": 0.94,
                }
            ],
            "application_status": "completed",
            "extracted_skills": ["Python", "FastAPI"],
            "resume_summary": "Experienced backend candidate.",
            "auto_apply_audit": [
                {
                    "job_url": "https://example.test/fake-role",
                    "job_title": "Fake Role",
                    "company": "Acme",
                    "action": "submit",
                    "status": "success",
                    "message": "Submitted in fake graph",
                }
            ] if state.get("auto_apply") else [],
        }


class FakePrefs:
    role = ["Software Engineer"]
    experience_level = ["Senior"]
    location = ["Remote"]
    job_type = ["Full-time"]
    target_companies = []
    posted_within_days = 7
    min_match_score = 70


def test_job_pre_screen_rejects_only_clear_conflicts_and_keeps_uncertain_jobs():
    prefs = FakePrefs()

    rejected = JobPreScreenService.screen(
        {
            "title": "Junior Software Engineer Internship",
            "company": "Acme",
            "location": "Remote",
            "description": "Campus program for students.",
            "url": "https://example.test/junior",
        },
        prefs,
    )
    assert rejected.status == "reject"
    assert any("entry-level" in reason or "internship" in reason for reason in rejected.reasons)

    uncertain = JobPreScreenService.screen(
        {
            "title": "Platform Analyst",
            "company": "Acme",
            "location": "Boston, MA",
            "description": "Build internal tooling and automate reporting.",
            "url": "https://example.test/analyst",
        },
        prefs,
    )
    assert uncertain.status == "maybe"
    assert any("kept for full" in reason.lower() for reason in uncertain.reasons)

    passed = JobPreScreenService.screen(
        {
            "title": "Senior Software Engineer",
            "company": "Acme",
            "location": "Remote",
            "description": "Build backend services and APIs.",
            "url": "https://example.test/senior",
        },
        prefs,
    )
    assert passed.status == "pass"


def test_search_jobs_prescreens_before_ai_analysis(monkeypatch):
    def fake_search_jobs(query: str, location: str, posted_within_days: int = 7):
        return [
            {
                "title": "Senior Software Engineer",
                "company": "Acme",
                "location": "Remote",
                "description": "Build backend APIs.",
                "url": "https://example.test/senior",
                "fit_score": 0.0,
            },
            {
                "title": "Junior Software Engineer Internship",
                "company": "Beta",
                "location": "Remote",
                "description": "Campus internship program.",
                "url": "https://example.test/intern",
                "fit_score": 0.0,
            },
            {
                "title": "Platform Analyst",
                "company": "Core",
                "location": "Boston, MA",
                "description": "Automate internal reporting.",
                "url": "https://example.test/analyst",
                "fit_score": 0.0,
            },
        ]

    saved_jobs = []
    monkeypatch.setattr(nodes.JobSearchService, "search_jobs", staticmethod(fake_search_jobs))
    monkeypatch.setattr(
        PersistenceService,
        "save_job",
        staticmethod(lambda user_id, job, status: saved_jobs.append((user_id, job.copy(), status))),
    )

    result = asyncio.run(nodes.search_jobs({
        "preferences": FakePrefs(),
        "logs": [],
        "user_id": 42,
    }))

    assert [job["title"] for job in result["found_jobs"]] == [
        "Senior Software Engineer",
        "Platform Analyst",
    ]
    assert result["total_found_jobs"] == 3
    assert result["screened_out_jobs_count"] == 1
    saved_by_title = {job["title"]: (job, status) for _, job, status in saved_jobs}
    assert saved_by_title["Junior Software Engineer Internship"][1] == "Screened Out"
    assert saved_by_title["Junior Software Engineer Internship"][0]["pre_screen_status"] == "reject"
    assert saved_by_title["Senior Software Engineer"][1] == "Identified"
    assert saved_by_title["Platform Analyst"][0]["pre_screen_status"] == "maybe"
    assert "screened out 1 obvious non-fits" in result["logs"][-1]


def test_search_jobs_returns_empty_list_when_scraper_fails(monkeypatch):
    def fake_scrape_jobs(*_args, **_kwargs):
        raise RuntimeError("jobspy unavailable")

    monkeypatch.setattr(job_search_module, "scrape_jobs", fake_scrape_jobs)

    with TestClient(app) as client:
        response = client.get("/search-jobs?query=Python&location=Remote")

    assert response.status_code == 200, response.text
    assert response.json() == []


def test_api_errors_include_structured_error_object():
    with TestClient(app) as client:
        response = client.get("/user/status")

    assert response.status_code == 401, response.text
    body = response.json()
    assert body["detail"] == "Authentication required"
    assert body["error"] == {
        "code": "http_401",
        "message": "Authentication required",
        "status_code": 401,
        "path": "/user/status",
    }


def test_validation_errors_include_structured_error_object():
    with TestClient(app) as client:
        response = client.post("/auth/register", json={"email": "missing-password@example.test"})

    assert response.status_code == 422, response.text
    body = response.json()
    assert isinstance(body["detail"], list)
    assert body["error"] == {
        "code": "validation_error",
        "message": "Request validation failed",
        "status_code": 422,
        "path": "/auth/register",
    }


def test_health_endpoints_report_database_and_background_worker(monkeypatch):
    monkeypatch.setenv("AGENT_RUNNER_MODE", "background")

    with TestClient(app) as client:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM workerheartbeat"))

        health = client.get("/health")
        assert health.status_code == 200, health.text
        assert health.json()["status"] == "ok"

        database = client.get("/health/db")
        assert database.status_code == 200, database.text
        assert database.json()["database"] == "reachable"
        assert database.json()["migration_mode"] in {"lightweight", "alembic"}

        worker = client.get("/health/worker")
        assert worker.status_code == 200, worker.text
        body = worker.json()
        assert body["status"] == "ok"
        assert body["runner_mode"] == "background"
        assert body["worker_expected"] is False
        assert body["heartbeat_status"] == "not_expected"


def test_cors_origins_are_local_by_default_and_strict_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    assert api_main.get_cors_allowed_origins() == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FRONTEND_URL", "https://jobs.example.com/app")
    assert api_main.get_cors_allowed_origins() == ["https://jobs.example.com"]

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://jobs.example.com,https://preview.example.com")
    monkeypatch.setenv("FRONTEND_URL", "https://jobs.example.com")
    assert api_main.get_cors_allowed_origins() == [
        "https://jobs.example.com",
        "https://preview.example.com",
    ]

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    with pytest.raises(RuntimeError):
        api_main.get_cors_allowed_origins()

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "jobs.example.com")
    with pytest.raises(RuntimeError):
        api_main.get_cors_allowed_origins()

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    with pytest.raises(RuntimeError):
        api_main.get_cors_allowed_origins()


def test_worker_health_reports_fresh_heartbeat_and_queue_counts(monkeypatch):
    monkeypatch.setenv("AGENT_RUNNER_MODE", "worker")
    monkeypatch.setenv("AGENT_WORKER_HEARTBEAT_STALE_SECONDS", "30")
    queued_run_id = None

    with TestClient(app) as client:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM workerheartbeat"))

        auth, _headers = register_user(client, "worker-health")
        with Session(engine) as session:
            session.add(
                WorkerHeartbeat(
                    worker_id="test-worker",
                    status="idle",
                    last_seen_at=utc_now(),
                    details={"source": "test"},
                )
            )
            queued_run = AgentRun(
                user_id=auth["user"]["id"],
                status="queued",
                auto_apply=False,
                started_at=utc_now() - timedelta(minutes=2),
            )
            session.add(queued_run)
            session.commit()
            session.refresh(queued_run)
            queued_run_id = queued_run.id

        response = client.get("/health/worker")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["runner_mode"] == "worker"
        assert body["worker_expected"] is True
        assert body["heartbeat_status"] == "fresh"
        assert body["heartbeat_worker_id"] == "test-worker"
        assert body["heartbeat_worker_status"] == "idle"
        assert body["heartbeat_age_seconds"] >= 0
        assert body["queued_runs"] >= 1
        assert body["oldest_queued_at"] is not None

        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM agentrun WHERE id = :id"),
                {"id": queued_run_id},
            )


def test_worker_health_degrades_when_expected_worker_is_stale(monkeypatch):
    monkeypatch.setenv("AGENT_RUNNER_MODE", "worker")
    monkeypatch.setenv("AGENT_WORKER_HEARTBEAT_STALE_SECONDS", "5")

    with TestClient(app) as client:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM workerheartbeat"))

        with Session(engine) as session:
            session.add(
                WorkerHeartbeat(
                    worker_id="stale-worker",
                    status="idle",
                    last_seen_at=utc_now() - timedelta(seconds=30),
                )
            )
            session.commit()

        response = client.get("/health/worker")
        assert response.status_code == 503, response.text
        body = response.json()
        assert body["status"] == "degraded"
        assert body["heartbeat_status"] == "stale"
        assert body["heartbeat_worker_id"] == "stale-worker"


SUBMIT_DETECTION_FIXTURES = Path(__file__).parent / "fixtures" / "submit_detection"


def test_bearer_auth_and_user_status_contract():
    with TestClient(app) as client:
        assert client.get("/user/status").status_code == 401

        auth, headers = register_user(client, "status")
        assert auth["token_type"] == "bearer"
        assert auth["refresh_token"]
        assert auth["expires_in"] > 0
        assert auth["refresh_expires_in"] > auth["expires_in"]
        assert "hashed_password" not in auth["user"]

        response = client.get("/user/status", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["user"]["email"] == auth["user"]["email"]
        assert body["resume"] is None
        assert body["preferences"] is None
        assert body["profile"]["location"] == "Remote"

        logout_response = client.post("/auth/logout", headers=headers)
        assert logout_response.status_code == 200, logout_response.text
        assert logout_response.json()["message"] == "Signed out successfully"
        assert client.get("/user/status", headers=headers).status_code == 401

        login_response = client.post(
            "/auth/login",
            json={"email": auth["user"]["email"], "password": "Password123!"},
        )
        assert login_response.status_code == 200, login_response.text
        login_body = login_response.json()
        assert login_body["refresh_token"]
        new_headers = {"Authorization": f"Bearer {login_body['access_token']}"}
        assert client.get("/user/status", headers=new_headers).status_code == 200

        refresh_response = client.post(
            "/auth/refresh",
            json={"refresh_token": login_body["refresh_token"]},
        )
        assert refresh_response.status_code == 200, refresh_response.text
        refreshed = refresh_response.json()
        assert refreshed["access_token"] != login_body["access_token"]
        assert refreshed["refresh_token"] != login_body["refresh_token"]
        assert client.get("/user/status", headers=new_headers).status_code == 401
        assert client.post(
            "/auth/refresh",
            json={"refresh_token": login_body["refresh_token"]},
        ).status_code == 401

        refreshed_headers = {"Authorization": f"Bearer {refreshed['access_token']}"}
        assert client.get("/user/status", headers=refreshed_headers).status_code == 200
        assert body["quota"]["agent_run_limit"] == 3
        assert body["quota"]["agent_runs_remaining"] == 3
        assert body["quota"]["auto_apply_enabled"] is False


def test_auth_secret_insecurity_detector_flags_dev_defaults():
    assert endpoints.auth_secret_is_insecure("")
    assert endpoints.auth_secret_is_insecure("change-me-in-production")
    assert endpoints.auth_secret_is_insecure("short")
    assert not endpoints.auth_secret_is_insecure("a-production-secret-with-enough-entropy")


def test_answer_encryption_supports_previous_key_rotation(monkeypatch):
    monkeypatch.setenv("APP_DATA_ENCRYPTION_KEY", "old-answer-key")
    monkeypatch.delenv("APP_DATA_PREVIOUS_ENCRYPTION_KEYS", raising=False)
    encrypted = encrypt_text("yes")
    assert encrypted.startswith(ENCRYPTED_VALUE_PREFIX)

    monkeypatch.setenv("APP_DATA_ENCRYPTION_KEY", "new-answer-key")
    assert decrypt_text(encrypted, fallback="unreadable") == "unreadable"

    monkeypatch.setenv("APP_DATA_PREVIOUS_ENCRYPTION_KEYS", "older-key,old-answer-key")
    assert decrypt_text(encrypted, fallback="unreadable") == "yes"
    assert encrypt_text("yes") != encrypted


def test_answer_reencryption_job_rotates_previous_key_and_plaintext_values(monkeypatch):
    with TestClient(app):
        pass
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM applicationanswerprofile"))

    monkeypatch.setenv("APP_DATA_ENCRYPTION_KEY", "old-answer-key")
    monkeypatch.delenv("APP_DATA_PREVIOUS_ENCRYPTION_KEYS", raising=False)
    old_authorization = encrypt_text("yes")
    old_salary = encrypt_text("$150k")
    assert decrypt_text_with_key_status(old_authorization)[1] == "current"

    monkeypatch.setenv("APP_DATA_ENCRYPTION_KEY", "new-answer-key")
    monkeypatch.setenv("APP_DATA_PREVIOUS_ENCRYPTION_KEYS", "old-answer-key")

    with Session(engine) as session:
        user = User(email=unique_email("reencrypt"), subscription_tier="free")
        session.add(user)
        session.commit()
        session.refresh(user)

        answer_profile = ApplicationAnswerProfile(
            user_id=user.id,
            work_authorized_us=old_authorization,
            requires_sponsorship_now="no",
            desired_salary=old_salary,
            consent_to_use_answers=True,
        )
        session.add(answer_profile)
        session.commit()
        session.refresh(answer_profile)

        dry_run = reencrypt_application_answer_profiles(session, dry_run=True)
        assert dry_run["scanned_records"] == 1
        assert dry_run["previous_key_records"] == 1
        assert dry_run["plaintext_records"] == 1
        assert dry_run["reencrypted_records"] == 1
        session.refresh(answer_profile)
        assert answer_profile.work_authorized_us == old_authorization

        applied = reencrypt_application_answer_profiles(session, dry_run=False)
        assert applied["scanned_records"] == 1
        assert applied["reencrypted_records"] == 1
        session.refresh(answer_profile)
        new_authorization = answer_profile.work_authorized_us
        new_salary = answer_profile.desired_salary
        new_sponsorship = answer_profile.requires_sponsorship_now

    assert new_authorization != old_authorization
    assert new_salary != old_salary

    monkeypatch.setenv("APP_DATA_ENCRYPTION_KEY", "new-answer-key")
    monkeypatch.delenv("APP_DATA_PREVIOUS_ENCRYPTION_KEYS", raising=False)
    assert decrypt_text(new_authorization, fallback="unreadable") == "yes"
    assert decrypt_text(new_salary, fallback="unreadable") == "$150k"
    assert decrypt_text(new_sponsorship, fallback="unreadable") == "no"
    assert decrypt_text_with_key_status(new_authorization)[1] == "current"


def test_answer_reencryption_job_reports_unreadable_rows_without_partial_update(monkeypatch):
    with TestClient(app):
        pass
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM applicationanswerprofile"))

    monkeypatch.setenv("APP_DATA_ENCRYPTION_KEY", "new-answer-key")
    monkeypatch.delenv("APP_DATA_PREVIOUS_ENCRYPTION_KEYS", raising=False)

    with Session(engine) as session:
        user = User(email=unique_email("reencrypt-unreadable"), subscription_tier="free")
        session.add(user)
        session.commit()
        session.refresh(user)

        answer_profile = ApplicationAnswerProfile(
            user_id=user.id,
            work_authorized_us=f"{ENCRYPTED_VALUE_PREFIX}not-a-valid-token",
            desired_salary="$150k",
            consent_to_use_answers=True,
        )
        session.add(answer_profile)
        session.commit()
        session.refresh(answer_profile)

        result = reencrypt_application_answer_profiles(session, dry_run=False)
        assert result["scanned_records"] == 1
        assert result["unreadable_records"] == 1
        assert result["reencrypted_records"] == 0
        assert result["unreadable_fields"][0]["fields"] == ["work_authorized_us"]

        session.refresh(answer_profile)
        assert answer_profile.desired_salary == "$150k"


def test_admin_config_requires_admin_and_persists_updates():
    with TestClient(app) as client:
        auth, headers = register_user(client, "admin-config")
        user_id = auth["user"]["id"]

        forbidden = client.get("/admin/config", headers=headers)
        assert forbidden.status_code == 403

        with Session(engine) as session:
            user = session.get(User, user_id)
            user.role = "admin"
            session.add(user)
            session.commit()

        payload = {
            "site_names": ["linkedin", "google", "motion_recruitment"],
            "results_wanted": 8,
            "country_indeed": "USA",
        }
        update = client.put("/admin/config", json=payload, headers=headers)
        assert update.status_code == 200, update.text
        assert update.json()["message"] == "Configuration updated"

        current = client.get("/admin/config", headers=headers)
        assert current.status_code == 200, current.text
        body = current.json()
        assert body["site_names"] == payload["site_names"]
        assert body["results_wanted"] == 8
        assert body["country_indeed"] == "USA"

        with Session(engine) as session:
            saved = session.exec(select(ScraperConfig).order_by(ScraperConfig.updated_at.desc())).first()
        assert saved.site_names == payload["site_names"]


def test_resume_and_preferences_are_scoped_to_current_user():
    with TestClient(app) as client:
        _, user_a_headers = register_user(client, "owner-a")
        _, user_b_headers = register_user(client, "owner-b")

        preferences = {
            "role": ["Product Manager"],
            "experience_level": ["Senior"],
            "location": ["New York"],
            "job_type": ["Full-time"],
            "target_companies": ["Acme"],
            "min_match_score": 82,
            "posted_within_days": 14,
        }
        prefs_response = client.post("/preferences", json=preferences, headers=user_a_headers)
        assert prefs_response.status_code == 200, prefs_response.text
        assert prefs_response.json()["role"] == ["Product Manager"]
        assert "user_id" not in prefs_response.json()

        resume_response = client.post(
            "/upload-resume",
            files={"file": ("resume.txt", b"Python SQL product leadership", "text/plain")},
            headers=user_a_headers,
        )
        assert resume_response.status_code == 200, resume_response.text

        user_a_status = client.get("/user/status", headers=user_a_headers).json()
        assert user_a_status["resume"]["filename"] == "resume.txt"
        assert user_a_status["preferences"]["min_match_score"] == 82

        user_b_status = client.get("/user/status", headers=user_b_headers).json()
        assert user_b_status["resume"] is None
        assert user_b_status["preferences"] is None


def test_application_history_query_contracts():
    with TestClient(app) as client:
        auth, headers = register_user(client, "apps")
        user_id = auth["user"]["id"]
        now = utc_now()

        with Session(engine) as session:
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Old Role",
                    company="Beta",
                    job_url="https://example.test/old",
                    status="Analyzed",
                    fit_score=0.91,
                    created_at=now - timedelta(days=3),
                )
            )
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Recent Role",
                    company="Acme",
                    job_url="https://example.test/recent",
                    status="Applied",
                    fit_score=0.72,
                    created_at=now,
                )
            )
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Middle Role",
                    company="Core",
                    job_url="https://example.test/middle",
                    status="Applied",
                    fit_score=0.83,
                    created_at=now - timedelta(days=1),
                )
            )
            session.commit()

        recent = client.get("/applications?limit=2&sort=date&direction=desc", headers=headers)
        assert recent.status_code == 200, recent.text
        recent_body = recent.json()
        assert [item["job_title"] for item in recent_body] == ["Recent Role", "Middle Role"]
        assert "user_id" not in recent_body[0]

        filtered = client.get(
            "/applications?status=Applied&sort=score&direction=desc",
            headers=headers,
        )
        assert filtered.status_code == 200, filtered.text
        filtered_body = filtered.json()
        assert [item["job_title"] for item in filtered_body] == ["Middle Role", "Recent Role"]


def test_application_match_bucket_filters_use_latest_threshold():
    with TestClient(app) as client:
        auth, headers = register_user(client, "match-buckets")
        user_id = auth["user"]["id"]

        prefs_response = client.post(
            "/preferences",
            json={
                "role": ["Software Engineer"],
                "experience_level": ["Senior"],
                "location": ["Remote"],
                "job_type": ["Full-time"],
                "target_companies": [],
                "min_match_score": 75,
                "posted_within_days": 7,
            },
            headers=headers,
        )
        assert prefs_response.status_code == 200, prefs_response.text

        with Session(engine) as session:
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Strong Role",
                    company="Acme",
                    job_url="https://example.test/strong",
                    status="Analyzed",
                    fit_score=0.91,
                    pre_screen_status="pass",
                    pre_screen_reasons=["Compatible role signals."],
                )
            )
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Low Role",
                    company="Beta",
                    job_url="https://example.test/low",
                    status="Analyzed",
                    fit_score=0.62,
                    pre_screen_status="maybe",
                    pre_screen_reasons=["Kept for full review."],
                )
            )
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Screened Role",
                    company="Core",
                    job_url="https://example.test/screened",
                    status="Screened Out",
                    fit_score=0.0,
                    pre_screen_status="reject",
                    pre_screen_reasons=["Title is clearly not full-time."],
                )
            )
            session.commit()

        strong = client.get("/applications?match_bucket=strong&sort=role&direction=asc", headers=headers)
        assert strong.status_code == 200, strong.text
        assert [item["job_title"] for item in strong.json()] == ["Strong Role"]

        below = client.get("/applications?match_bucket=below_threshold", headers=headers)
        assert below.status_code == 200, below.text
        assert [item["job_title"] for item in below.json()] == ["Low Role"]

        screened = client.get("/applications?match_bucket=screened_out", headers=headers)
        assert screened.status_code == 200, screened.text
        screened_body = screened.json()
        assert [item["job_title"] for item in screened_body] == ["Screened Role"]
        assert screened_body[0]["pre_screen_status"] == "reject"
        assert screened_body[0]["pre_screen_reasons"] == ["Title is clearly not full-time."]

        all_apps = client.get("/applications?match_bucket=all", headers=headers)
        assert all_apps.status_code == 200, all_apps.text
        assert {item["job_title"] for item in all_apps.json()} == {
            "Strong Role",
            "Low Role",
            "Screened Role",
        }

        invalid = client.get("/applications?match_bucket=unknown", headers=headers)
        assert invalid.status_code == 400


def test_application_package_generation_requires_threshold_match():
    with TestClient(app) as client:
        auth, headers = register_user(client, "package-threshold")
        user_id = auth["user"]["id"]
        prepare_agent_setup(client, headers)

        with Session(engine) as session:
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Below Threshold Role",
                    company="Acme",
                    job_url="https://example.test/below-package",
                    status="Analyzed",
                    fit_score=0.61,
                    pre_screen_status="maybe",
                )
            )
            session.commit()

        app_body = client.get("/applications", headers=headers).json()[0]
        response = client.post(
            "/agent/prepare-application",
            json={
                "app_id": app_body["id"],
                "title": app_body["job_title"],
                "company": app_body["company"],
                "description": "Backend platform role.",
            },
            headers=headers,
        )

        assert response.status_code == 400
        assert "below your 75% minimum match score" in response.json()["detail"]


def test_application_package_generation_persists_cover_letter_with_fake_llm(monkeypatch):
    class FakeChain:
        def __init__(self, kind: str):
            self.kind = kind

        def __or__(self, _other):
            return self

        async def ainvoke(self, _payload):
            if self.kind == "package":
                return {
                    "cover_letter": "Dear Hiring Manager,\n\nI am excited about Acme.\n\nSincerely,\nTest User",
                    "tailored_summary": "Backend engineer with FastAPI and SQL experience.",
                    "talking_points": ["FastAPI", "SQL", "Automation", "Ownership"],
                    "qa_answers": [{"question": "Why Acme?", "answer": "Strong platform fit."}],
                }
            return {
                "interview_questions": [{"question": "Tell me about yourself", "suggested_answer": "Backend builder."}],
                "company_brief": {"overview": "Acme builds platform tools.", "questions_to_ask": ["How is success measured?"]},
            }

    def fake_from_messages(messages):
        system_message = messages[0][1]
        kind = "interview" if "interview coach" in system_message else "package"
        return FakeChain(kind)

    monkeypatch.setattr(endpoints, "get_llm", lambda model_type="openai": object())
    monkeypatch.setattr(endpoints.ChatPromptTemplate, "from_messages", staticmethod(fake_from_messages))

    with TestClient(app) as client:
        auth, headers = register_user(client, "package-success")
        user_id = auth["user"]["id"]
        prepare_agent_setup(client, headers)

        with Session(engine) as session:
            app_record = Application(
                user_id=user_id,
                job_title="Backend Engineer",
                company="Acme",
                job_url="https://example.test/backend",
                status="Analyzed",
                fit_score=0.91,
                pre_screen_status="pass",
            )
            session.add(app_record)
            session.commit()
            session.refresh(app_record)
            app_id = app_record.id

        response = client.post(
            "/agent/prepare-application",
            json={
                "app_id": app_id,
                "title": "Backend Engineer",
                "company": "Acme",
                "description": "Build FastAPI services and SQL-backed automation.",
            },
            headers=headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["cover_letter"].startswith("Dear Hiring Manager")
        assert body["tailored_summary"] == "Backend engineer with FastAPI and SQL experience."
        assert body["talking_points"] == ["FastAPI", "SQL", "Automation", "Ownership"]
        assert body["qa_answers"][0]["answer"] == "Strong platform fit."
        assert body["interview_questions"][0]["question"] == "Tell me about yourself"
        assert body["company_brief"]["overview"] == "Acme builds platform tools."

        with Session(engine) as session:
            saved_app = session.get(Application, app_id)
        assert saved_app.cover_letter == body["cover_letter"]


def test_account_export_includes_owned_records_and_artifact_links():
    with TestClient(app) as client:
        auth, headers = register_user(client, "account-export")
        user_id = auth["user"]["id"]
        other_auth, _other_headers = register_user(client, "account-export-other")
        other_user_id = other_auth["user"]["id"]
        prepare_agent_setup(client, headers)

        answer_response = client.post(
            "/application-profile",
            headers=headers,
            json={
                "work_authorized_us": "yes",
                "requires_sponsorship_now": "no",
                "requires_sponsorship_future": "no",
                "willing_to_relocate": "yes",
                "remote_preference": "remote",
                "earliest_start_date": "2026-07-01",
                "notice_period": "2 weeks",
                "desired_salary": "$140k",
                "work_authorization_notes": "Authorized without sponsorship.",
                "consent_to_use_answers": True,
                "gender": "woman",
                "race_ethnicity": "black_or_african_american",
                "veteran_status": "not_a_veteran",
                "disability_status": "prefer_not_to_answer",
                "consent_to_use_demographics": False,
            },
        )
        assert answer_response.status_code == 200, answer_response.text

        with Session(engine) as session:
            agent_run = AgentRun(
                user_id=user_id,
                status="completed",
                auto_apply=True,
                logs=["queued", "completed"],
                applications_count=1,
                found_jobs_count=1,
                completed_at=utc_now(),
            )
            session.add(agent_run)
            app_record = Application(
                user_id=user_id,
                job_title="Export Role",
                company="Acme",
                job_url="https://boards.greenhouse.io/acme/jobs/export",
                resolved_url="https://boards.greenhouse.io/acme/jobs/export",
                source_type="ats",
                ats_type="greenhouse",
                resolution_status="resolved",
                status="Needs Review",
                fit_score=0.94,
                explanation="Strong backend match.",
                cover_letter="Dear Hiring Manager,\n\nExportable cover letter.",
                pre_screen_status="pass",
            )
            other_app = Application(
                user_id=other_user_id,
                job_title="Other User Role",
                company="OtherCo",
                job_url="https://example.test/other-user-role",
                status="Analyzed",
                fit_score=0.99,
            )
            settings = ApplicationSubmitSettings(
                user_id=user_id,
                true_submit_enabled=True,
                require_human_confirmation=True,
                min_fit_score=85,
                max_submits_per_day=3,
                allowed_companies=["Acme"],
                allowed_domains=["greenhouse.io"],
                allowed_job_title_keywords=["Export"],
                consented_at=utc_now(),
            )
            session.add(app_record)
            session.add(other_app)
            session.add(settings)
            session.commit()
            session.refresh(agent_run)
            session.refresh(app_record)

            review = ApplicationFillReview(
                user_id=user_id,
                application_id=app_record.id,
                ats_type="greenhouse",
                application_url=app_record.resolved_url,
                status="ready_for_review",
                message="Prepared in account export test.",
                fields_filled=["First name", "Last name", "Email", "Resume"],
                fields_missing=[],
                blockers=[],
            )
            session.add(review)
            session.commit()
            session.refresh(review)

            screenshot_path = FillReviewArtifactStore.save_base64(
                user_id=user_id,
                application_id=app_record.id,
                review_id=review.id,
                kind="screenshot",
                payload_base64=base64.b64encode(b"export-png").decode("ascii"),
                extension="png",
            )
            trace_path = FillReviewArtifactStore.save_base64(
                user_id=user_id,
                application_id=app_record.id,
                review_id=review.id,
                kind="trace",
                payload_base64=base64.b64encode(b"export-zip").decode("ascii"),
                extension="zip",
            )
            review.screenshot_path = screenshot_path
            review.trace_path = trace_path
            session.add(review)

            attempt = AutoApplyAttempt(
                user_id=user_id,
                application_id=app_record.id,
                agent_run_id=agent_run.id,
                fill_review_id=review.id,
                job_url=app_record.job_url,
                job_title=app_record.job_title,
                company=app_record.company,
                ats_type=app_record.ats_type,
                mode="fill_for_review",
                status="ready_for_confirmation",
                confidence_score=0.91,
                filled_fields=["First name", "Last name", "Email", "Resume"],
                missing_fields=[],
                blockers=[],
                readiness_snapshot={"ready": True},
                submit_control={"detected": True, "label": "Submit Application"},
                steps=[{"name": "fill_review_completed", "status": "ready_for_confirmation", "at": "2026-06-03T00:00:00"}],
                screenshot_path=screenshot_path,
                trace_path=trace_path,
            )
            session.add(attempt)
            session.commit()
            session.refresh(attempt)

            session.add(
                AutoApplyAudit(
                    user_id=user_id,
                    agent_run_id=agent_run.id,
                    auto_apply_attempt_id=attempt.id,
                    job_url=app_record.job_url,
                    job_title=app_record.job_title,
                    company=app_record.company,
                    action="fill_review",
                    status="ready_for_confirmation",
                    message="Prepared for review.",
                )
            )
            session.commit()

        response = client.get("/account/export", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        body_text = json.dumps(body)

        assert body["user"]["email"] == auth["user"]["email"]
        assert body["message"] == "Account data exported."
        assert body["counts"]["resumes"] == 1
        assert body["counts"]["applications"] == 1
        assert body["counts"]["generated_packages"] == 1
        assert body["counts"]["fill_reviews"] == 1
        assert body["counts"]["automation_attempts"] == 1

        assert body["resumes"][0]["filename"] == "resume.txt"
        assert body["resumes"][0]["content_text"] == "Python FastAPI SQL"
        assert base64.b64decode(body["resumes"][0]["file_content_base64"]) == b"Python FastAPI SQL"
        assert body["application_profile"]["desired_salary"] == "$140k"
        assert body["application_profile"]["gender"] == "prefer_not_to_answer"
        assert body["submission_settings"]["allowed_companies"] == ["Acme"]

        assert [item["job_title"] for item in body["applications"]] == ["Export Role"]
        assert body["generated_packages"][0]["cover_letter"].startswith("Dear Hiring Manager")
        assert body["generated_packages"][0]["cover_letter_pdf_url"] == (
            f"/applications/{body['applications'][0]['id']}/cover-letter.pdf"
        )
        assert body["fill_reviews"][0]["screenshot_url"] == (
            f"/applications/{body['applications'][0]['id']}/fill-reviews/{body['fill_reviews'][0]['id']}/screenshot"
        )
        assert body["fill_reviews"][0]["trace_url"].endswith("/trace")
        assert body["automation_attempts"][0]["screenshot_url"] == body["fill_reviews"][0]["screenshot_url"]
        assert body["automation_attempts"][0]["submit_control"]["label"] == "Submit Application"
        assert body["agent_runs"][0]["auto_apply_audit"][0]["status"] == "ready_for_confirmation"
        assert body["auto_apply_audit"][0]["job_title"] == "Export Role"

        answer_actions = {entry["action"] for entry in body["application_answer_audit"]}
        assert {"upsert", "export"}.issubset(answer_actions)
        assert "$140k" not in json.dumps(body["application_answer_audit"])
        assert "Other User Role" not in body_text
        assert "user_id" not in body_text

        assert client.get("/account/export").status_code == 401


def test_application_link_resolver_classifies_ats_and_aggregators():
    greenhouse = ApplicationLinkResolver.classify_url("https://boards.greenhouse.io/acme/jobs/123")
    assert greenhouse.source_type == "ats"
    assert greenhouse.ats_type == "greenhouse"
    assert greenhouse.resolution_status == "resolved"
    assert greenhouse.resolved_url == "https://boards.greenhouse.io/acme/jobs/123"

    workday = ApplicationLinkResolver.classify_url("https://acme.wd1.myworkdayjobs.com/en-US/jobs/job/123")
    assert workday.source_type == "ats"
    assert workday.ats_type == "workday"
    assert workday.resolution_status == "resolved"
    assert workday.resolved_url == "https://acme.wd1.myworkdayjobs.com/en-US/jobs/job/123"

    bamboohr = ApplicationLinkResolver.classify_url("https://acme.bamboohr.com/careers/123")
    assert bamboohr.source_type == "ats"
    assert bamboohr.ats_type == "bamboohr"
    assert bamboohr.resolution_status == "resolved"

    icims = ApplicationLinkResolver.classify_url("https://careers-acme.icims.com/jobs/123/job")
    assert icims.source_type == "ats"
    assert icims.ats_type == "icims"
    assert icims.resolution_status == "resolved"

    recruitee = ApplicationLinkResolver.classify_url("https://acme.recruitee.com/o/backend-engineer")
    assert recruitee.source_type == "ats"
    assert recruitee.ats_type == "recruitee"
    assert recruitee.resolution_status == "resolved"

    taleo = ApplicationLinkResolver.classify_url("https://acme.taleo.net/careersection/jobdetail.ftl?job=123")
    assert taleo.source_type == "ats"
    assert taleo.ats_type == "taleo"
    assert taleo.resolution_status == "resolved"

    linkedin = ApplicationLinkResolver.classify_url("https://www.linkedin.com/jobs/view/123")
    assert linkedin.source_type == "linkedin"
    assert linkedin.ats_type is None
    assert linkedin.resolution_status == "needs_resolution"
    assert linkedin.resolved_url is None

    company_site = ApplicationLinkResolver.classify_url("https://careers.example.com/jobs/123")
    assert company_site.source_type == "company_site"
    assert company_site.resolution_status == "resolved"


def test_persisted_applications_include_link_resolution_metadata():
    with TestClient(app) as client:
        auth, headers = register_user(client, "link-resolution")
        user_id = auth["user"]["id"]

        PersistenceService.save_job(
            user_id,
            {
                "title": "External Role",
                "company": "LinkedIn Source",
                "url": "https://www.linkedin.com/jobs/view/999",
                "fit_score": 0.88,
            },
            "Analyzed",
        )

        response = client.get("/applications", headers=headers)
        assert response.status_code == 200, response.text
        app_body = response.json()[0]
        assert app_body["job_url"] == "https://www.linkedin.com/jobs/view/999"
        assert app_body["source_url"] == "https://www.linkedin.com/jobs/view/999"
        assert app_body["resolved_url"] is None
        assert app_body["source_type"] == "linkedin"
        assert app_body["ats_type"] is None
        assert app_body["resolution_status"] == "needs_resolution"
        assert "user_id" not in app_body


def test_resolve_application_link_endpoint_updates_owned_application(monkeypatch):
    async def fake_resolve_url(url: str, timeout_ms: int = 30000):
        assert url == "https://www.linkedin.com/jobs/view/999"
        return LinkResolutionResult(
            original_url=url,
            resolved_url="https://boards.greenhouse.io/acme/jobs/999",
            source_type="linkedin",
            ats_type="greenhouse",
            resolution_status="resolved",
            notes="Resolved in test.",
        )

    monkeypatch.setattr(endpoints.ApplicationLinkResolver, "resolve_url", staticmethod(fake_resolve_url))

    with TestClient(app) as client:
        auth, headers = register_user(client, "resolve-link")
        user_id = auth["user"]["id"]

        PersistenceService.save_job(
            user_id,
            {
                "title": "Resolved Role",
                "company": "Acme",
                "url": "https://www.linkedin.com/jobs/view/999",
                "fit_score": 0.9,
            },
            "Analyzed",
        )

        app_body = client.get("/applications", headers=headers).json()[0]
        response = client.post(f"/applications/{app_body['id']}/resolve-link", headers=headers)

        assert response.status_code == 200, response.text
        resolved = response.json()
        assert resolved["source_url"] == "https://www.linkedin.com/jobs/view/999"
        assert resolved["resolved_url"] == "https://boards.greenhouse.io/acme/jobs/999"
        assert resolved["source_type"] == "linkedin"
        assert resolved["ats_type"] == "greenhouse"
        assert resolved["resolution_status"] == "resolved"
        assert resolved["resolution_notes"] == "Resolved in test."

        _, other_headers = register_user(client, "resolve-other")
        denied = client.post(f"/applications/{app_body['id']}/resolve-link", headers=other_headers)
        assert denied.status_code == 404


def test_greenhouse_fill_review_endpoint_updates_application_status(monkeypatch):
    async def fake_fill_application_for_review(**kwargs):
        assert kwargs["application_url"] == "https://boards.greenhouse.io/acme/jobs/123"
        assert kwargs["ats_type"] == "greenhouse"
        assert kwargs["profile"].email.endswith("@example.test")
        assert kwargs["resume_bytes"] == b"Python FastAPI SQL"
        assert kwargs["answer_profile"].work_authorized_us == "yes"
        return FillReviewResult(
            status="ready_for_review",
            ats_type="greenhouse",
            application_url=kwargs["application_url"],
            fields_filled=["First name", "Last name", "Email", "Resume", "Work authorization"],
            fields_missing=[],
            blockers=[],
            message="Prepared in test.",
            screenshot_base64=base64.b64encode(b"fake-png").decode("ascii"),
            trace_base64=base64.b64encode(b"fake-zip").decode("ascii"),
        )

    monkeypatch.setattr(
        endpoints.ApplicationFillReviewService,
        "fill_application_for_review",
        staticmethod(fake_fill_application_for_review),
    )

    with TestClient(app) as client:
        auth, headers = register_user(client, "fill-review")
        user_id = auth["user"]["id"]
        prepare_agent_setup(client, headers)

        with Session(engine) as session:
            session.add(
                ApplicationAnswerProfile(
                    user_id=user_id,
                    work_authorized_us="yes",
                    requires_sponsorship_now="no",
                    requires_sponsorship_future="no",
                    consent_to_use_answers=True,
                )
            )
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Greenhouse Role",
                    company="Acme",
                    job_url="https://boards.greenhouse.io/acme/jobs/123",
                    resolved_url="https://boards.greenhouse.io/acme/jobs/123",
                    source_type="ats",
                    ats_type="greenhouse",
                    resolution_status="resolved",
                    status="Analyzed",
                    fit_score=0.92,
                )
            )
            session.commit()

        app_body = client.get("/applications", headers=headers).json()[0]
        response = client.post(f"/applications/{app_body['id']}/fill-review", headers=headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ready_for_review"
        assert body["ats_type"] == "greenhouse"
        assert "Resume" in body["fields_filled"]
        assert body["application_status"] == "Needs Review"
        assert isinstance(body["review_id"], int)
        assert isinstance(body["attempt_id"], int)
        assert body["screenshot_url"] == f"/applications/{app_body['id']}/fill-reviews/{body['review_id']}/screenshot"
        assert body["trace_url"] == f"/applications/{app_body['id']}/fill-reviews/{body['review_id']}/trace"

        updated_app = client.get("/applications", headers=headers).json()[0]
        assert updated_app["status"] == "Needs Review"

        reviews = client.get(f"/applications/{app_body['id']}/fill-reviews", headers=headers)
        assert reviews.status_code == 200, reviews.text
        review_body = reviews.json()
        assert review_body[0]["id"] == body["review_id"]
        assert review_body[0]["application_id"] == app_body["id"]
        assert review_body[0]["fields_filled"] == body["fields_filled"]
        assert review_body[0]["screenshot_url"] == body["screenshot_url"]
        assert review_body[0]["trace_url"] == body["trace_url"]
        assert "user_id" not in review_body[0]

        attempts = client.get(f"/applications/{app_body['id']}/automation-attempts", headers=headers)
        assert attempts.status_code == 200, attempts.text
        attempt_body = attempts.json()
        assert attempt_body[0]["id"] == body["attempt_id"]
        assert attempt_body[0]["fill_review_id"] == body["review_id"]
        assert attempt_body[0]["status"] == "ready_for_confirmation"
        assert attempt_body[0]["filled_fields"] == body["fields_filled"]
        assert attempt_body[0]["screenshot_url"] == body["screenshot_url"]
        assert [step["name"] for step in attempt_body[0]["steps"]] == [
            "attempt_created",
            "inputs_validated",
            "browser_fill_started",
            "fill_review_completed",
        ]
        assert attempt_body[0]["steps"][-1]["status"] == "ready_for_confirmation"
        assert "user_id" not in attempt_body[0]

        screenshot = client.get(body["screenshot_url"], headers=headers)
        assert screenshot.status_code == 200, screenshot.text
        assert screenshot.content == b"fake-png"

        trace = client.get(body["trace_url"], headers=headers)
        assert trace.status_code == 200, trace.text
        assert trace.content == b"fake-zip"

        _, other_headers = register_user(client, "fill-review-record-other")
        denied = client.get(f"/applications/{app_body['id']}/fill-reviews", headers=other_headers)
        assert denied.status_code == 404
        denied_attempts = client.get(f"/applications/{app_body['id']}/automation-attempts", headers=other_headers)
        assert denied_attempts.status_code == 404
        denied_screenshot = client.get(body["screenshot_url"], headers=other_headers)
        assert denied_screenshot.status_code == 404
        denied_trace = client.get(body["trace_url"], headers=other_headers)
        assert denied_trace.status_code == 404
        denied_clear = client.delete(f"/applications/{app_body['id']}/fill-reviews", headers=other_headers)
        assert denied_clear.status_code == 404

        clear_response = client.delete(f"/applications/{app_body['id']}/fill-reviews", headers=headers)
        assert clear_response.status_code == 200, clear_response.text
        assert client.get(f"/applications/{app_body['id']}/fill-reviews", headers=headers).json() == []
        assert client.get(body["screenshot_url"], headers=headers).status_code == 404
        assert client.get(body["trace_url"], headers=headers).status_code == 404


def test_fill_review_artifact_store_prunes_expired_files(monkeypatch, tmp_path):
    monkeypatch.setenv("FILL_REVIEW_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("FILL_REVIEW_ARTIFACT_RETENTION_DAYS", "1")

    old_file = tmp_path / "1" / "2" / "old-trace.zip"
    recent_file = tmp_path / "1" / "2" / "recent-trace.zip"
    old_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"old")
    recent_file.write_bytes(b"recent")
    old_timestamp = time.time() - (3 * 24 * 60 * 60)
    os.utime(old_file, (old_timestamp, old_timestamp))

    assert FillReviewArtifactStore.prune_expired() == 1
    assert not old_file.exists()
    assert recent_file.exists()


def test_lever_fill_review_endpoint_uses_supported_adapter(monkeypatch):
    async def fake_fill_application_for_review(**kwargs):
        assert kwargs["application_url"] == "https://jobs.lever.co/acme/123"
        assert kwargs["ats_type"] == "lever"
        return FillReviewResult(
            status="ready_for_review",
            ats_type="lever",
            application_url=kwargs["application_url"],
            fields_filled=["Name", "Email", "Resume"],
            fields_missing=["Work authorization"],
            blockers=[],
            message="Lever prepared in test.",
        )

    monkeypatch.setattr(
        endpoints.ApplicationFillReviewService,
        "fill_application_for_review",
        staticmethod(fake_fill_application_for_review),
    )

    with TestClient(app) as client:
        auth, headers = register_user(client, "lever-fill-review")
        user_id = auth["user"]["id"]
        prepare_agent_setup(client, headers)

        with Session(engine) as session:
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Lever Role",
                    company="Acme",
                    job_url="https://jobs.lever.co/acme/123",
                    resolved_url="https://jobs.lever.co/acme/123",
                    source_type="ats",
                    ats_type="lever",
                    resolution_status="resolved",
                    status="Analyzed",
                    fit_score=0.92,
                )
            )
            session.commit()

        app_body = client.get("/applications", headers=headers).json()[0]
        response = client.post(f"/applications/{app_body['id']}/fill-review", headers=headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ats_type"] == "lever"
        assert body["fields_filled"] == ["Name", "Email", "Resume"]


def test_new_supported_ats_fill_review_use_supported_adapters(monkeypatch):
    calls = []

    async def fake_fill_application_for_review(**kwargs):
        calls.append((kwargs["application_url"], kwargs["ats_type"]))
        return FillReviewResult(
            status="ready_for_review",
            ats_type=kwargs["ats_type"],
            application_url=kwargs["application_url"],
            fields_filled=["First name", "Last name", "Email", "Resume"],
            fields_missing=[],
            blockers=[],
            message=f"{kwargs['ats_type']} prepared in test.",
        )

    monkeypatch.setattr(
        endpoints.ApplicationFillReviewService,
        "fill_application_for_review",
        staticmethod(fake_fill_application_for_review),
    )

    with TestClient(app) as client:
        auth, headers = register_user(client, "new-ats-fill-review")
        user_id = auth["user"]["id"]
        prepare_agent_setup(client, headers)

        ats_apps = [
            ("Ashby Role", "https://jobs.ashbyhq.com/beta/123", "ashby"),
            ("BambooHR Role", "https://acme.bamboohr.com/careers/123", "bamboohr"),
            ("ICIMS Role", "https://careers-acme.icims.com/jobs/123/job", "icims"),
            ("Recruitee Role", "https://acme.recruitee.com/o/backend-engineer", "recruitee"),
            ("SmartRecruiters Role", "https://jobs.smartrecruiters.com/acme/123", "smartrecruiters"),
            ("Taleo Role", "https://acme.taleo.net/careersection/jobdetail.ftl?job=123", "taleo"),
            ("Workday Role", "https://acme.wd1.myworkdayjobs.com/jobs/job/123", "workday"),
        ]
        with Session(engine) as session:
            for title, url, ats_type in ats_apps:
                session.add(
                    Application(
                        user_id=user_id,
                        job_title=title,
                        company="Acme",
                        job_url=url,
                        resolved_url=url,
                        source_type="ats",
                        ats_type=ats_type,
                        resolution_status="resolved",
                        status="Analyzed",
                        fit_score=0.92,
                    )
                )
            session.commit()

        apps = client.get("/applications?sort=role&direction=asc", headers=headers).json()
        for app_body in apps:
            response = client.post(f"/applications/{app_body['id']}/fill-review", headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["ats_type"] == app_body["ats_type"]

        assert sorted(ats_type for _, ats_type in calls) == [
            "ashby",
            "bamboohr",
            "icims",
            "recruitee",
            "smartrecruiters",
            "taleo",
            "workday",
        ]


def test_fill_review_requires_resolved_supported_ats_link():
    with TestClient(app) as client:
        auth, headers = register_user(client, "fill-review-guard")
        user_id = auth["user"]["id"]
        prepare_agent_setup(client, headers)

        with Session(engine) as session:
            session.add(
                Application(
                    user_id=user_id,
                    job_title="LinkedIn Role",
                    company="Acme",
                    job_url="https://www.linkedin.com/jobs/view/123",
                    source_type="linkedin",
                    resolution_status="needs_resolution",
                    status="Analyzed",
                    fit_score=0.92,
                )
            )
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Unsupported ATS Role",
                    company="Beta",
                    job_url="https://jobs.unsupportedats.test/123",
                    resolved_url="https://jobs.unsupportedats.test/123",
                    source_type="ats",
                    ats_type="oracle",
                    resolution_status="resolved",
                    status="Analyzed",
                    fit_score=0.9,
                )
            )
            session.commit()

        apps = client.get("/applications?sort=role&direction=asc", headers=headers).json()
        linkedin_app = next(item for item in apps if item["job_title"] == "LinkedIn Role")
        unsupported_ats_app = next(item for item in apps if item["job_title"] == "Unsupported ATS Role")

        unresolved = client.post(f"/applications/{linkedin_app['id']}/fill-review", headers=headers)
        assert unresolved.status_code == 400
        assert "Resolve" in unresolved.json()["detail"]

        unsupported = client.post(f"/applications/{unsupported_ats_app['id']}/fill-review", headers=headers)
        assert unsupported.status_code == 400
        assert "Greenhouse, Lever, Ashby, SmartRecruiters, Workday, BambooHR, iCIMS, Recruitee, and Taleo" in unsupported.json()["detail"]


def test_submit_control_detection_uses_html_fixtures():
    ready_html = (SUBMIT_DETECTION_FIXTURES / "greenhouse_ready.html").read_text()
    ready = ApplicationFillReviewService.detect_final_submit_control_from_html(
        ready_html,
        ats_type="greenhouse",
        current_url="https://boards.greenhouse.io/acme/jobs/123",
    )
    assert ready.status == "detected"
    assert ready.detected is True
    assert ready.confidence >= 0.85
    assert ready.selector == "#submit_application"
    assert ready.label == "Submit Application"

    bamboohr_ready_html = (SUBMIT_DETECTION_FIXTURES / "bamboohr_ready.html").read_text()
    bamboohr_ready = ApplicationFillReviewService.detect_final_submit_control_from_html(
        bamboohr_ready_html,
        ats_type="bamboohr",
        current_url="https://acme.bamboohr.com/careers/123",
    )
    assert bamboohr_ready.status == "detected"
    assert bamboohr_ready.detected is True
    assert bamboohr_ready.confidence >= 0.85
    assert bamboohr_ready.selector == "#submitApplication"
    assert bamboohr_ready.label == "Submit Application"

    icims_ready_html = (SUBMIT_DETECTION_FIXTURES / "icims_ready.html").read_text()
    icims_ready = ApplicationFillReviewService.detect_final_submit_control_from_html(
        icims_ready_html,
        ats_type="icims",
        current_url="https://careers-acme.icims.com/jobs/123/job",
    )
    assert icims_ready.status == "detected"
    assert icims_ready.detected is True
    assert icims_ready.confidence >= 0.85
    assert icims_ready.selector == "#submitApplication"
    assert icims_ready.label == "Submit Application"

    recruitee_ready_html = (SUBMIT_DETECTION_FIXTURES / "recruitee_ready.html").read_text()
    recruitee_ready = ApplicationFillReviewService.detect_final_submit_control_from_html(
        recruitee_ready_html,
        ats_type="recruitee",
        current_url="https://acme.recruitee.com/o/backend-engineer",
    )
    assert recruitee_ready.status == "detected"
    assert recruitee_ready.detected is True
    assert recruitee_ready.confidence >= 0.85
    assert recruitee_ready.selector == "#submitApplication"
    assert recruitee_ready.label == "Submit Application"

    taleo_ready_html = (SUBMIT_DETECTION_FIXTURES / "taleo_ready.html").read_text()
    taleo_ready = ApplicationFillReviewService.detect_final_submit_control_from_html(
        taleo_ready_html,
        ats_type="taleo",
        current_url="https://acme.taleo.net/careersection/jobdetail.ftl?job=123",
    )
    assert taleo_ready.status == "detected"
    assert taleo_ready.detected is True
    assert taleo_ready.confidence >= 0.85
    assert taleo_ready.selector == "#submitApplication"
    assert taleo_ready.label == "Submit Application"

    workday_ready_html = (SUBMIT_DETECTION_FIXTURES / "workday_ready.html").read_text()
    workday_ready = ApplicationFillReviewService.detect_final_submit_control_from_html(
        workday_ready_html,
        ats_type="workday",
        current_url="https://acme.wd1.myworkdayjobs.com/en-US/jobs/job/123",
    )
    assert workday_ready.status == "detected"
    assert workday_ready.detected is True
    assert workday_ready.confidence >= 0.85
    assert workday_ready.selector == 'button[data-automation-id="bottom-navigation-submit-button"]'
    assert workday_ready.label == "Submit"

    workday_gate_html = (SUBMIT_DETECTION_FIXTURES / "workday_account_gate.html").read_text()
    workday_gate = ApplicationFillReviewService.detect_final_submit_control_from_html(
        workday_gate_html,
        ats_type="workday",
        current_url="https://acme.wd1.myworkdayjobs.com/en-US/jobs/job/123",
    )
    assert workday_gate.status == "blocked"
    assert workday_gate.detected is False
    assert "create account" in workday_gate.blockers[0]

    ambiguous_html = (SUBMIT_DETECTION_FIXTURES / "ambiguous_submit.html").read_text()
    ambiguous = ApplicationFillReviewService.detect_final_submit_control_from_html(
        ambiguous_html,
        ats_type="lever",
        current_url="https://jobs.lever.co/acme/123/apply",
    )
    assert ambiguous.status == "ambiguous"
    assert ambiguous.detected is False
    assert "Multiple possible final submit controls" in ambiguous.blockers[0]

    captcha_html = (SUBMIT_DETECTION_FIXTURES / "captcha_blocked.html").read_text()
    blocked = ApplicationFillReviewService.detect_final_submit_control_from_html(
        captcha_html,
        ats_type="greenhouse",
        current_url="https://boards.greenhouse.io/acme/jobs/123",
    )
    assert blocked.status == "blocked"
    assert blocked.detected is False
    assert "captcha" in blocked.blockers[0]


def test_auto_apply_holds_unresolved_aggregator_links_for_review(monkeypatch):
    saved_jobs = []

    monkeypatch.setattr(
        PersistenceService,
        "save_job",
        staticmethod(lambda user_id, job, status: saved_jobs.append((user_id, job, status))),
    )

    state = {
        "preferences": FakePrefs(),
        "found_jobs": [
            {
                "title": "Aggregator Role",
                "company": "LinkedIn Source",
                "url": "https://www.linkedin.com/jobs/view/123",
                "fit_score": 0.9,
            }
        ],
        "applications_submitted": [],
        "logs": [],
        "user_id": 42,
        "auto_apply": True,
        "auto_apply_audit": [],
    }

    result = asyncio.run(submit_application(state))

    assert result["applications_submitted"] == []
    assert result["application_status"] == "completed"
    assert "held for review" in result["logs"][0]
    assert result["auto_apply_audit"][0]["action"] == "resolve"
    assert result["auto_apply_audit"][0]["status"] == "needs_resolution"
    assert saved_jobs[0][2] == "Needs Review"


def test_auto_apply_allows_direct_supported_ats_links(monkeypatch):
    monkeypatch.setattr(PersistenceService, "save_job", staticmethod(lambda *args, **kwargs: None))

    job_url = "https://boards.greenhouse.io/acme/jobs/123"
    state = {
        "preferences": FakePrefs(),
        "found_jobs": [
            {
                "title": "ATS Role",
                "company": "Acme",
                "url": job_url,
                "fit_score": 0.9,
            }
        ],
        "applications_submitted": [],
        "logs": [],
        "user_id": 42,
        "auto_apply": True,
        "auto_apply_audit": [],
    }

    result = asyncio.run(submit_application(state))

    assert result["applications_submitted"] == [job_url]
    assert result["application_status"] == "applying"
    assert state["found_jobs"][0]["application_url"] == job_url


def test_browser_fill_review_never_clicks_final_submit(monkeypatch):
    captured = {}
    saved_jobs = []

    async def fake_apply_to_job(**kwargs):
        captured.update(kwargs)
        return {
            "status": "success",
            "message": "Prepared for review",
        }

    monkeypatch.setattr(nodes.BrowserApplyService, "apply_to_job", staticmethod(fake_apply_to_job))
    monkeypatch.setattr(
        PersistenceService,
        "save_job",
        staticmethod(lambda user_id, job, status: saved_jobs.append((user_id, job, status))),
    )

    job_url = "https://boards.greenhouse.io/acme/jobs/123"
    state = {
        "auto_apply": True,
        "profile": Profile(
            user_id=42,
            first_name="Test",
            last_name="User",
            email="test@example.test",
            phone="555-0100",
            location="Remote",
        ),
        "applications_submitted": [job_url],
        "found_jobs": [
            {
                "title": "ATS Role",
                "company": "Acme",
                "url": job_url,
                "application_url": job_url,
                "fit_score": 0.9,
                "cover_letter": "Hello",
            }
        ],
        "resume_bytes": b"resume",
        "resume_filename": "resume.pdf",
        "logs": [],
        "user_id": 42,
        "auto_apply_audit": [],
    }

    result = asyncio.run(apply_browser(state))

    assert captured["job_url"] == job_url
    assert captured["submit"] is False
    assert saved_jobs == [(42, state["found_jobs"][0], "Needs Review")]
    assert result["application_status"] == "completed"
    assert result["auto_apply_audit"][0]["action"] == "fill_review"
    assert result["auto_apply_audit"][0]["status"] == "success"
    assert "Prepared ATS Role at Acme for review" in result["logs"]


def test_browser_apply_blocks_final_submit_without_pilot_flag(monkeypatch):
    monkeypatch.delenv("ENABLE_TRUE_AUTO_SUBMIT", raising=False)

    result = asyncio.run(
        BrowserApplyService.apply_to_job(
            job_url="https://boards.greenhouse.io/acme/jobs/123",
            profile=Profile(
                user_id=42,
                first_name="Test",
                last_name="User",
                email="test@example.test",
                phone="555-0100",
                location="Remote",
            ),
            resume_bytes=b"resume",
            resume_filename="resume.pdf",
            submit=True,
        )
    )

    assert result["status"] == "blocked"
    assert "Automated final submit is disabled" in result["message"]


def test_application_answer_profile_is_user_scoped_and_sanitizes_sensitive_answers():
    with TestClient(app) as client:
        auth, headers = register_user(client, "answer-profile")

        empty_response = client.get("/application-profile", headers=headers)
        assert empty_response.status_code == 200, empty_response.text
        assert empty_response.json() is None

        payload = {
            "work_authorized_us": "yes",
            "requires_sponsorship_now": "no",
            "requires_sponsorship_future": "no",
            "willing_to_relocate": "no",
            "remote_preference": "remote",
            "earliest_start_date": "2026-07-01",
            "notice_period": "2 weeks",
            "desired_salary": "$140k",
            "work_authorization_notes": "US citizen",
            "consent_to_use_answers": True,
            "gender": "woman",
            "race_ethnicity": "black_or_african_american",
            "veteran_status": "not_a_veteran",
            "disability_status": "no",
            "consent_to_use_demographics": False,
        }
        save_response = client.post("/application-profile", json=payload, headers=headers)
        assert save_response.status_code == 200, save_response.text
        saved = save_response.json()
        assert saved["work_authorized_us"] == "yes"
        assert saved["consent_to_use_answers"] is True
        assert saved["gender"] == "prefer_not_to_answer"
        assert saved["race_ethnicity"] == "prefer_not_to_answer"
        assert saved["veteran_status"] == "prefer_not_to_answer"
        assert saved["disability_status"] == "prefer_not_to_answer"
        assert "user_id" not in saved

        status_response = client.get("/user/status", headers=headers)
        assert status_response.status_code == 200, status_response.text
        assert status_response.json()["application_profile"]["work_authorized_us"] == "yes"

        export_response = client.get("/application-profile/export", headers=headers)
        assert export_response.status_code == 200, export_response.text
        exported = export_response.json()
        assert exported["profile"]["desired_salary"] == "$140k"
        assert exported["profile"]["work_authorization_notes"] == "US citizen"
        assert "user_id" not in exported["profile"]

        with Session(engine) as session:
            stored = session.exec(
                select(ApplicationAnswerProfile).where(ApplicationAnswerProfile.user_id == auth["user"]["id"])
            ).first()
            assert stored.work_authorized_us.startswith(ENCRYPTED_VALUE_PREFIX)
            assert stored.work_authorized_us != "yes"
            assert stored.work_authorization_notes.startswith(ENCRYPTED_VALUE_PREFIX)
            assert stored.gender.startswith(ENCRYPTED_VALUE_PREFIX)
            assert stored.gender != "prefer_not_to_answer"
            audit_rows = session.exec(
                select(ApplicationAnswerAudit)
                .where(ApplicationAnswerAudit.user_id == auth["user"]["id"])
                .order_by(ApplicationAnswerAudit.created_at.asc())
            ).all()
            audit_actions = [row.action for row in audit_rows]
            assert "upsert" in audit_actions
            assert "view" in audit_actions
            assert "export" in audit_actions
            assert all("$140k" not in row.fields for row in audit_rows)
            assert any("desired_salary" in row.fields for row in audit_rows)

        audit_response = client.get("/application-profile/audit?limit=10", headers=headers)
        assert audit_response.status_code == 200, audit_response.text
        audit_body = audit_response.json()
        assert audit_body[0]["action"] == "export"
        assert "desired_salary" in audit_body[0]["fields"]
        assert "user_id" not in audit_body[0]

        _, other_headers = register_user(client, "answer-profile-other")
        other_response = client.get("/application-profile", headers=other_headers)
        assert other_response.status_code == 200, other_response.text
        assert other_response.json() is None

        delete_response = client.delete("/application-profile", headers=headers)
        assert delete_response.status_code == 200, delete_response.text
        assert client.get("/application-profile", headers=headers).json() is None
        assert client.get("/user/status", headers=headers).json()["application_profile"] is None

        audit_after_delete = client.get("/application-profile/audit?limit=10", headers=headers)
        assert audit_after_delete.status_code == 200, audit_after_delete.text
        assert audit_after_delete.json()[0]["action"] == "delete"


def test_application_answer_profile_stores_demographics_with_explicit_consent():
    with TestClient(app) as client:
        auth, headers = register_user(client, "answer-profile-consent")

        response = client.post(
            "/application-profile",
            json={
                "work_authorized_us": "prefer_not_to_answer",
                "consent_to_use_answers": False,
                "gender": "non_binary",
                "race_ethnicity": "prefer_not_to_answer",
                "veteran_status": "not_a_veteran",
                "disability_status": "prefer_not_to_answer",
                "consent_to_use_demographics": True,
            },
            headers=headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["gender"] == "non_binary"
        assert body["veteran_status"] == "not_a_veteran"
        assert body["consent_to_use_demographics"] is True

        with Session(engine) as session:
            stored = session.exec(
                select(ApplicationAnswerProfile).where(ApplicationAnswerProfile.user_id == auth["user"]["id"])
            ).first()
            assert stored.gender.startswith(ENCRYPTED_VALUE_PREFIX)
            assert stored.gender != "non_binary"
            assert stored.veteran_status.startswith(ENCRYPTED_VALUE_PREFIX)
            assert stored.veteran_status != "not_a_veteran"


def test_submission_settings_and_readiness_contract(monkeypatch):
    with TestClient(app) as client:
        auth, headers = register_user(client, "submit-settings")
        user_id = auth["user"]["id"]
        prepare_agent_setup(client, headers)

        with Session(engine) as session:
            user = session.get(User, user_id)
            user.subscription_tier = "pro"
            session.add(user)
            session.add(
                ApplicationAnswerProfile(
                    user_id=user_id,
                    work_authorized_us="yes",
                    requires_sponsorship_now="no",
                    requires_sponsorship_future="no",
                    consent_to_use_answers=True,
                )
            )
            saved_app = Application(
                user_id=user_id,
                job_title="Senior Backend Engineer",
                company="Acme",
                job_url="https://boards.greenhouse.io/acme/jobs/123",
                resolved_url="https://boards.greenhouse.io/acme/jobs/123",
                source_type="ats",
                ats_type="greenhouse",
                resolution_status="resolved",
                status="Needs Review",
                fit_score=0.92,
            )
            session.add(saved_app)
            session.commit()
            session.refresh(saved_app)
            app_id = saved_app.id
            app_url = saved_app.resolved_url
            session.add(
                ApplicationFillReview(
                    user_id=user_id,
                    application_id=app_id,
                    ats_type="greenhouse",
                    application_url=app_url,
                    status="ready_for_review",
                    message="Prepared in test.",
                    fields_filled=["First name", "Last name", "Email", "Resume"],
                    fields_missing=[],
                    blockers=[],
                )
            )
            session.commit()

        default_settings = client.get("/submission-settings", headers=headers)
        assert default_settings.status_code == 200, default_settings.text
        assert default_settings.json()["true_submit_enabled"] is False

        readiness_blocked = client.post(f"/applications/{app_id}/submit-readiness", headers=headers)
        assert readiness_blocked.status_code == 200, readiness_blocked.text
        assert readiness_blocked.json()["ready"] is False
        assert "True-submit pilot flag is off" in readiness_blocked.json()["blockers"][0]

        settings_response = client.post(
            "/submission-settings",
            headers=headers,
            json={
                "true_submit_enabled": True,
                "require_human_confirmation": True,
                "min_fit_score": 85,
                "max_submits_per_day": 3,
                "allowed_companies": ["Acme"],
                "denied_companies": ["Nope"],
                "allowed_domains": ["greenhouse.io"],
                "denied_domains": [],
                "allowed_job_title_keywords": ["Backend"],
                "consent_to_submit": True,
            },
        )
        assert settings_response.status_code == 200, settings_response.text
        settings_body = settings_response.json()
        assert settings_body["true_submit_enabled"] is False
        assert settings_body["true_submit_pilot_enabled"] is False
        assert settings_body["true_submit_pilot_approved"] is False
        assert "True-submit pilot flag is off" in settings_body["true_submit_pilot_blockers"][0]
        assert settings_body["consented_at"] is None

        monkeypatch.setenv("ENABLE_TRUE_AUTO_SUBMIT", "true")
        monkeypatch.setenv("TRUE_SUBMIT_PILOT_USER_EMAILS", auth["user"]["email"])
        monkeypatch.setenv("TRUE_SUBMIT_PILOT_ATS_TYPES", "greenhouse")
        settings_response = client.post(
            "/submission-settings",
            headers=headers,
            json={
                "true_submit_enabled": True,
                "require_human_confirmation": True,
                "min_fit_score": 85,
                "max_submits_per_day": 3,
                "allowed_companies": ["Acme"],
                "denied_companies": ["Nope"],
                "allowed_domains": ["greenhouse.io"],
                "denied_domains": [],
                "allowed_job_title_keywords": ["Backend"],
                "consent_to_submit": True,
            },
        )
        assert settings_response.status_code == 200, settings_response.text
        settings_body = settings_response.json()
        assert settings_body["true_submit_enabled"] is True
        assert settings_body["true_submit_pilot_enabled"] is True
        assert settings_body["true_submit_pilot_approved"] is True
        assert settings_body["consented_at"] is not None
        assert settings_body["allowed_companies"] == ["Acme"]

        readiness = client.post(f"/applications/{app_id}/submit-readiness", headers=headers)
        assert readiness.status_code == 200, readiness.text
        body = readiness.json()
        assert body["ready"] is True
        assert body["can_submit"] is False
        assert body["status"] == "ready_for_confirmation"
        assert body["blockers"] == []
        assert "Fit score meets the submit threshold." in body["checks"]

        with Session(engine) as session:
            readiness_audit = session.exec(
                select(ApplicationAnswerAudit)
                .where(
                    ApplicationAnswerAudit.user_id == user_id,
                    ApplicationAnswerAudit.application_id == app_id,
                    ApplicationAnswerAudit.action == "automation_read",
                    ApplicationAnswerAudit.access_reason == "submit_readiness",
                )
            ).first()
        assert readiness_audit is not None
        assert "work_authorized_us" in readiness_audit.fields

        reset_response = client.delete("/submission-settings", headers=headers)
        assert reset_response.status_code == 200, reset_response.text
        assert reset_response.json()["true_submit_enabled"] is False


def test_submit_confirmation_endpoint_detects_final_control_without_clicking(monkeypatch):
    async def fake_detect_final_submit_control(**kwargs):
        assert kwargs["application_url"] == "https://boards.greenhouse.io/acme/jobs/456"
        assert kwargs["ats_type"] == "greenhouse"
        return SubmitControlDetection(
            status="detected",
            detected=True,
            confidence=0.93,
            label="Submit Application",
            selector="#submit_application",
            button_type="submit",
            current_url=kwargs["application_url"],
            evidence=["fixture-backed high confidence control"],
        )

    monkeypatch.setattr(
        endpoints.ApplicationFillReviewService,
        "detect_final_submit_control",
        staticmethod(fake_detect_final_submit_control),
    )

    with TestClient(app) as client:
        auth, headers = register_user(client, "submit-confirmation")
        user_id = auth["user"]["id"]
        monkeypatch.setenv("ENABLE_TRUE_AUTO_SUBMIT", "true")
        monkeypatch.setenv("TRUE_SUBMIT_PILOT_USER_EMAILS", auth["user"]["email"])
        monkeypatch.setenv("TRUE_SUBMIT_PILOT_ATS_TYPES", "greenhouse")
        prepare_agent_setup(client, headers)

        with Session(engine) as session:
            user = session.get(User, user_id)
            user.subscription_tier = "pro"
            session.add(user)
            session.add(
                ApplicationAnswerProfile(
                    user_id=user_id,
                    work_authorized_us="yes",
                    requires_sponsorship_now="no",
                    requires_sponsorship_future="no",
                    consent_to_use_answers=True,
                )
            )
            saved_app = Application(
                user_id=user_id,
                job_title="Senior Platform Engineer",
                company="Acme",
                job_url="https://boards.greenhouse.io/acme/jobs/456",
                resolved_url="https://boards.greenhouse.io/acme/jobs/456",
                source_type="ats",
                ats_type="greenhouse",
                resolution_status="resolved",
                status="Needs Review",
                fit_score=0.94,
            )
            session.add(saved_app)
            session.commit()
            session.refresh(saved_app)
            app_id = saved_app.id
            session.add(
                ApplicationFillReview(
                    user_id=user_id,
                    application_id=app_id,
                    ats_type="greenhouse",
                    application_url=saved_app.resolved_url,
                    status="ready_for_review",
                    message="Prepared in test.",
                    fields_filled=["First name", "Last name", "Email", "Resume"],
                    fields_missing=[],
                    blockers=[],
                )
            )
            session.commit()

        settings_response = client.post(
            "/submission-settings",
            headers=headers,
            json={
                "true_submit_enabled": True,
                "require_human_confirmation": True,
                "min_fit_score": 85,
                "max_submits_per_day": 3,
                "allowed_companies": ["Acme"],
                "denied_companies": [],
                "allowed_domains": ["greenhouse.io"],
                "denied_domains": [],
                "allowed_job_title_keywords": ["Platform"],
                "consent_to_submit": True,
            },
        )
        assert settings_response.status_code == 200, settings_response.text

        confirmation = client.post(f"/applications/{app_id}/submit-confirmation", headers=headers)
        assert confirmation.status_code == 200, confirmation.text
        body = confirmation.json()
        assert isinstance(body["attempt_id"], int)
        assert body["ready"] is True
        assert body["can_submit"] is False
        assert body["status"] == "ready_for_human_confirmation"
        assert body["submit_control"]["selector"] == "#submit_application"
        assert body["submit_control"]["confidence"] == 0.93
        assert "Final submit control was detected with high confidence." in body["checks"]
        assert "No automated final click was performed." in body["warnings"]

        attempts = client.get(f"/applications/{app_id}/automation-attempts", headers=headers)
        assert attempts.status_code == 200, attempts.text
        attempt = attempts.json()[0]
        assert attempt["id"] == body["attempt_id"]
        assert attempt["status"] == "ready_for_human_confirmation"
        assert attempt["confidence_score"] == 0.93
        assert attempt["submit_control"]["selector"] == "#submit_application"
        assert attempt["readiness_snapshot"]["ready"] is True
        assert [step["name"] for step in attempt["steps"]] == [
            "attempt_created",
            "readiness_checked",
            "submit_control_detection",
            "final_confirmation_prepared",
        ]
        assert attempt["steps"][1]["status"] == "success"
        assert attempt["steps"][2]["details"]["confidence"] == 0.93

        with Session(engine) as session:
            audit = session.exec(
                select(AutoApplyAudit)
                .where(AutoApplyAudit.user_id == user_id)
                .order_by(AutoApplyAudit.created_at.desc())
            ).first()
        assert audit.action == "submit_confirmation"
        assert audit.status == "ready"
        assert audit.auto_apply_attempt_id == body["attempt_id"]


def test_schema_migrations_are_recorded_and_idempotent():
    with TestClient(app):
        run_schema_migrations()
        with engine.begin() as connection:
            rows = connection.execute(
                text("SELECT id FROM schema_migrations ORDER BY id")
            ).all()

    assert ("0001_user_scope_resume_preferences",) in rows
    assert ("0002_application_link_resolution",) in rows
    assert ("0003_application_answer_profile",) in rows
    assert ("0004_application_fill_review",) in rows
    assert ("0005_application_fill_review_artifacts",) in rows
    assert ("0006_agent_run_claims",) in rows
    assert ("0007_auth_sessions",) in rows
    assert ("0008_application_submit_settings",) in rows
    assert ("0009_auto_apply_attempts",) in rows
    assert ("0010_application_prescreen",) in rows
    assert ("0011_auto_apply_attempt_steps",) in rows
    assert ("0012_auth_session_refresh_tokens",) in rows
    assert ("0013_worker_heartbeat",) in rows
    assert ("0014_application_answer_audit",) in rows


def test_agent_run_is_persisted_with_logs_and_auto_apply_audit(monkeypatch):
    monkeypatch.setattr(endpoints, "agent_graph", FakeAgentGraph())

    with TestClient(app) as client:
        auth, headers = register_user(client, "agent-run")
        with Session(engine) as session:
            user = session.get(User, auth["user"]["id"])
            user.subscription_tier = "pro"
            session.add(user)
            session.commit()

        prepare_agent_setup(client, headers)

        response = client.post("/agent/run?auto_apply=true", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "queued"
        assert body["agent_run_id"]
        assert body["quota_remaining"] == 49

        run_response = client.get(f"/agent/runs/{body['agent_run_id']}", headers=headers)
        assert run_response.status_code == 200, run_response.text
        run = run_response.json()
        assert run["status"] == "completed"
        assert run["auto_apply"] is True
        assert run["applications_count"] == 1
        assert run["found_jobs_count"] == 1
        assert run["logs"][-1] == "Fake search complete"
        assert run["auto_apply_audit"][0]["job_url"] == "https://example.test/fake-role"

        runs_response = client.get("/agent/runs", headers=headers)
        assert runs_response.status_code == 200, runs_response.text
        assert runs_response.json()[0]["id"] == body["agent_run_id"]


def test_agent_run_worker_mode_processes_persisted_queue(monkeypatch):
    monkeypatch.setattr(endpoints, "agent_graph", FakeAgentGraph())
    monkeypatch.setenv("AGENT_RUNNER_MODE", "worker")

    with TestClient(app) as client:
        _, headers = register_user(client, "agent-worker")
        prepare_agent_setup(client, headers)

        response = client.post("/agent/run", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "queued"

        queued_run = client.get(f"/agent/runs/{body['agent_run_id']}", headers=headers)
        assert queued_run.status_code == 200, queued_run.text
        assert queued_run.json()["status"] == "queued"
        assert queued_run.json()["logs"] == ["Agent workflow queued for worker"]

        assert asyncio.run(endpoints.run_next_queued_agent_run()) is True

        completed_run = client.get(f"/agent/runs/{body['agent_run_id']}", headers=headers)
        assert completed_run.status_code == 200, completed_run.text
        run_body = completed_run.json()
        assert run_body["status"] == "completed"
        assert run_body["applications_count"] == 1
        assert run_body["logs"][-1] == "Fake search complete"


def test_free_agent_run_quota_is_enforced(monkeypatch):
    monkeypatch.setattr(endpoints, "agent_graph", FakeAgentGraph())

    with TestClient(app) as client:
        _, headers = register_user(client, "quota")
        prepare_agent_setup(client, headers)

        for _ in range(3):
            response = client.post("/agent/run", headers=headers)
            assert response.status_code == 200, response.text

        blocked = client.post("/agent/run", headers=headers)
        assert blocked.status_code == 403
        assert "Daily agent run limit reached" in blocked.json()["detail"]


def test_browser_fill_review_requires_pro_plan(monkeypatch):
    monkeypatch.setattr(endpoints, "agent_graph", FakeAgentGraph())

    with TestClient(app) as client:
        _, headers = register_user(client, "auto-apply-free")
        prepare_agent_setup(client, headers)

        response = client.post("/agent/run?auto_apply=true", headers=headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "Browser fill-for-review requires a pro plan."
