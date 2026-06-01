import os
import tempfile
from datetime import datetime, timedelta
from uuid import uuid4

os.environ["AUTH_SECRET_KEY"] = "test-secret"
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/job_finder_test.db"

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.api import endpoints
from app.database import engine, run_schema_migrations
from app.models import Application, User
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


def test_bearer_auth_and_user_status_contract():
    with TestClient(app) as client:
        assert client.get("/user/status").status_code == 401

        auth, headers = register_user(client, "status")
        assert auth["token_type"] == "bearer"
        assert "hashed_password" not in auth["user"]

        response = client.get("/user/status", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["user"]["email"] == auth["user"]["email"]
        assert body["resume"] is None
        assert body["preferences"] is None
        assert body["profile"]["location"] == "Remote"
        assert body["quota"]["agent_run_limit"] == 3
        assert body["quota"]["agent_runs_remaining"] == 3
        assert body["quota"]["auto_apply_enabled"] is False


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
        now = datetime.utcnow()

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


def test_schema_migrations_are_recorded_and_idempotent():
    with TestClient(app):
        run_schema_migrations()
        with engine.begin() as connection:
            rows = connection.execute(
                text("SELECT id FROM schema_migrations ORDER BY id")
            ).all()

    assert ("0001_user_scope_resume_preferences",) in rows


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


def test_auto_apply_requires_pro_plan(monkeypatch):
    monkeypatch.setattr(endpoints, "agent_graph", FakeAgentGraph())

    with TestClient(app) as client:
        _, headers = register_user(client, "auto-apply-free")
        prepare_agent_setup(client, headers)

        response = client.post("/agent/run?auto_apply=true", headers=headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "Auto-submit requires a pro plan."
