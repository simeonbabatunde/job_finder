import base64
import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from uuid import uuid4

os.environ["AUTH_SECRET_KEY"] = "test-secret"
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/job_finder_test.db"
os.environ["FILL_REVIEW_ARTIFACT_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.api import endpoints
from app.agent import nodes
from app.agent.nodes import apply_browser, submit_application
from app.database import engine, run_schema_migrations
from app.models import Application, ApplicationAnswerProfile, Profile, User
from app.services.application_fill_review import FillReviewResult
from app.services.application_link_resolver import ApplicationLinkResolver, LinkResolutionResult
from app.services.persistence import PersistenceService
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
    min_match_score = 70


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


def test_application_link_resolver_classifies_ats_and_aggregators():
    greenhouse = ApplicationLinkResolver.classify_url("https://boards.greenhouse.io/acme/jobs/123")
    assert greenhouse.source_type == "ats"
    assert greenhouse.ats_type == "greenhouse"
    assert greenhouse.resolution_status == "resolved"
    assert greenhouse.resolved_url == "https://boards.greenhouse.io/acme/jobs/123"

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

        screenshot = client.get(body["screenshot_url"], headers=headers)
        assert screenshot.status_code == 200, screenshot.text
        assert screenshot.content == b"fake-png"

        trace = client.get(body["trace_url"], headers=headers)
        assert trace.status_code == 200, trace.text
        assert trace.content == b"fake-zip"

        _, other_headers = register_user(client, "fill-review-record-other")
        denied = client.get(f"/applications/{app_body['id']}/fill-reviews", headers=other_headers)
        assert denied.status_code == 404
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
                    job_title="Ashby Role",
                    company="Beta",
                    job_url="https://jobs.ashbyhq.com/beta/123",
                    resolved_url="https://jobs.ashbyhq.com/beta/123",
                    source_type="ats",
                    ats_type="ashby",
                    resolution_status="resolved",
                    status="Analyzed",
                    fit_score=0.9,
                )
            )
            session.commit()

        apps = client.get("/applications?sort=role&direction=asc", headers=headers).json()
        linkedin_app = next(item for item in apps if item["job_title"] == "LinkedIn Role")
        ashby_app = next(item for item in apps if item["job_title"] == "Ashby Role")

        unresolved = client.post(f"/applications/{linkedin_app['id']}/fill-review", headers=headers)
        assert unresolved.status_code == 400
        assert "Resolve" in unresolved.json()["detail"]

        unsupported = client.post(f"/applications/{ashby_app['id']}/fill-review", headers=headers)
        assert unsupported.status_code == 400
        assert "Greenhouse and Lever" in unsupported.json()["detail"]


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

        _, other_headers = register_user(client, "answer-profile-other")
        other_response = client.get("/application-profile", headers=other_headers)
        assert other_response.status_code == 200, other_response.text
        assert other_response.json() is None

        delete_response = client.delete("/application-profile", headers=headers)
        assert delete_response.status_code == 200, delete_response.text
        assert client.get("/application-profile", headers=headers).json() is None
        assert client.get("/user/status", headers=headers).json()["application_profile"] is None


def test_application_answer_profile_stores_demographics_with_explicit_consent():
    with TestClient(app) as client:
        _, headers = register_user(client, "answer-profile-consent")

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


def test_browser_fill_review_requires_pro_plan(monkeypatch):
    monkeypatch.setattr(endpoints, "agent_graph", FakeAgentGraph())

    with TestClient(app) as client:
        _, headers = register_user(client, "auto-apply-free")
        prepare_agent_setup(client, headers)

        response = client.post("/agent/run?auto_apply=true", headers=headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "Browser fill-for-review requires a pro plan."
