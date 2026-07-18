import base64
import asyncio
import io
import json
import os
import tempfile
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

os.environ["AUTH_SECRET_KEY"] = "test-secret"
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/jobmatchkit_test.db"
os.environ["FILL_REVIEW_ARTIFACT_DIR"] = tempfile.mkdtemp()
os.environ["OPENAI_API_KEY"] = "test-openai-key"

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
from app.services.application_link_resolver import ApplicationLinkResolver, CareerSearchCandidate, LinkResolutionResult
from app.services.company_discovery import CompanyDiscoveryService
from app.services.company_rankings import CompanyRankingService
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
from app.services.official_job_sources import OfficialJobSourceService
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
    def fake_search_jobs(query: str, location: str, posted_within_days: int = 7, **_kwargs):
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
        staticmethod(lambda user_id, job, status, **_kwargs: saved_jobs.append((user_id, job.copy(), status))),
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
    assert "Junior Software Engineer Internship" not in saved_by_title
    assert saved_by_title["Senior Software Engineer"][1] == "Identified"
    assert saved_by_title["Platform Analyst"][0]["pre_screen_status"] == "maybe"
    assert "skipped 1 obvious non-fits" in result["logs"][-1]

def test_search_jobs_prioritizes_allowed_company_seeds(monkeypatch):
    class Prefs(FakePrefs):
        target_companies = ["PreferenceCo", "AllowedCo", "OtherCo"]

    captured = {}

    def fake_search_jobs(query: str, location: str, posted_within_days: int = 7, **kwargs):
        captured["target_companies"] = list(kwargs.get("target_companies") or [])
        captured["target_roles"] = list(kwargs.get("target_roles") or [])
        return []

    monkeypatch.setattr(nodes.JobSearchService, "search_jobs", staticmethod(fake_search_jobs))

    result = asyncio.run(nodes.search_jobs({
        "preferences": Prefs(),
        "logs": [],
        "user_id": 42,
        "allowed_companies": ["AllowedCo", "GuardCo", "PreferenceCo", "Unknown Company", ""],
    }))

    assert result["found_jobs"] == []
    assert captured["target_companies"] == ["AllowedCo", "GuardCo", "PreferenceCo", "OtherCo"]
    assert captured["target_roles"] == ["Software Engineer"]

def test_search_jobs_passes_multiple_target_roles_and_search_terms(monkeypatch):
    class Prefs(FakePrefs):
        role = ["Software Engineer", "Firmware Engineer", "Data Scientist"]
        experience_level = ["Senior"]
        job_type = ["Full-time"]
        target_companies = []

    captured = {}

    def fake_search_jobs(query: str, location: str, posted_within_days: int = 7, **kwargs):
        captured["query"] = query
        captured["target_roles"] = list(kwargs.get("target_roles") or [])
        captured["search_terms"] = list(kwargs.get("search_terms") or [])
        return []

    monkeypatch.setattr(nodes.JobSearchService, "search_jobs", staticmethod(fake_search_jobs))

    result = asyncio.run(nodes.search_jobs({
        "preferences": Prefs(),
        "logs": [],
        "user_id": 42,
    }))

    assert result["found_jobs"] == []
    assert captured["query"] == "Senior Software Engineer Full-time"
    assert captured["target_roles"] == ["Software Engineer", "Firmware Engineer", "Data Scientist"]
    assert captured["search_terms"] == [
        "Senior Software Engineer Full-time",
        "Senior Firmware Engineer Full-time",
        "Senior Data Scientist Full-time",
    ]


def test_search_jobs_skips_unresolved_source_pages_before_ai(monkeypatch):
    def fake_search_jobs(query: str, location: str, posted_within_days: int = 7, **kwargs):
        return [
            {
                "title": "Senior Software Engineer",
                "company": "LinkedCo",
                "location": "Remote",
                "description": "Build backend APIs.",
                "url": "https://www.linkedin.com/jobs/view/999",
                "fit_score": 0.0,
            },
            {
                "title": "Senior Software Engineer",
                "company": "Acme",
                "location": "Remote",
                "description": "Build backend APIs.",
                "url": "https://careers.acme.com/jobs/senior-software-engineer",
                "fit_score": 0.0,
            },
        ]

    async def fake_resolve_url(url, timeout_ms=30000, company=None, job_title=None, allow_browser=True):
        assert url == "https://www.linkedin.com/jobs/view/999"
        assert allow_browser is False
        return LinkResolutionResult(
            original_url=url,
            resolved_url=None,
            source_type="linkedin",
            ats_type=None,
            resolution_status="needs_resolution",
            notes="Source page needs employer-link resolution.",
        )

    saved_jobs = []
    monkeypatch.setattr(nodes.JobSearchService, "search_jobs", staticmethod(fake_search_jobs))
    monkeypatch.setattr(nodes.ApplicationLinkResolver, "resolve_url", staticmethod(fake_resolve_url))
    monkeypatch.setattr(
        PersistenceService,
        "save_job",
        staticmethod(lambda user_id, job, status, **_kwargs: saved_jobs.append((user_id, job.copy(), status))),
    )

    result = asyncio.run(nodes.search_jobs({
        "preferences": FakePrefs(),
        "logs": [],
        "user_id": 42,
    }))

    assert [job["url"] for job in result["found_jobs"]] == ["https://careers.acme.com/jobs/senior-software-engineer"]
    assert [job["url"] for _, job, _ in saved_jobs] == ["https://careers.acme.com/jobs/senior-software-engineer"]
    assert result["total_found_jobs"] == 2
    assert "Skipped 1 source-page jobs" in result["logs"][-1]


def test_company_discovery_prioritizes_user_and_relevant_role_companies():
    companies = CompanyDiscoveryService.discover_company_names(
        seed_companies=["Afero", "Stripe"],
        target_roles=["Firmware Engineer"],
        query="Senior Firmware Engineer",
        board_results=[
            {"company": "BoardCo", "title": "Firmware Engineer"},
            {"company": "NoisyCo", "title": "Payroll Analyst"},
        ],
        max_companies=8,
    )

    assert companies[:2] == ["Afero", "Stripe"]
    assert "BoardCo" in companies
    assert "NoisyCo" not in companies
    assert any(company in companies for company in ["Datadog", "Cloudflare", "Figma"])


def test_official_job_source_service_falls_back_to_validated_career_page(monkeypatch):
    career_url = "https://careers.example.com/jobs/firmware-engineer"

    monkeypatch.setattr(
        OfficialJobSourceService,
        "discover_sources",
        staticmethod(lambda company, _fetch_cache=None: []),
    )
    monkeypatch.setattr(
        ApplicationLinkResolver,
        "_resolve_company_career_from_search",
        staticmethod(lambda company, job_title: career_url if company == "ExampleCo" and job_title == "Firmware Engineer" else None),
    )

    jobs = OfficialJobSourceService.search_company(
        "ExampleCo",
        target_roles=["Firmware Engineer"],
        location="Remote",
    )

    assert len(jobs) == 1
    assert jobs[0]["company"] == "ExampleCo"
    assert jobs[0]["title"] == "Firmware Engineer"
    assert jobs[0]["resolved_url"] == career_url
    assert jobs[0]["source_type"] == "company_site"
    assert jobs[0]["resolution_status"] == "resolved"


def test_official_job_source_service_parses_custom_big_company_career_pages(monkeypatch):
    class FakeResponse:
        def __init__(self, text="", payload=None, status_code=200):
            self.text = text
            self._payload = payload
            self.status_code = status_code
            self.ok = 200 <= status_code < 300

        def json(self):
            return self._payload

    def fake_get(url, timeout, headers):
        assert headers["User-Agent"]
        if "jobs.apple.com" in url:
            return FakeResponse(
                '\n                <div class="job-list-item">\n                  <h3><a href="/en-us/details/2001/firmware-engineer">Firmware Engineer</a></h3>\n                  <span class="team-name">Hardware</span>\n                  <span class="job-posted-date">Jun 26, 2026</span>\n                  <span id="search-store-name-container-1">Cupertino</span>\n                </div>\n                '
            )
        if "google.com/about/careers" in url:
            return FakeResponse(
                '\n                <div>\n                  <a href="/about/careers/applications/jobs/results/123-firmware-engineer">\n                    <h3>Firmware Engineer III</h3>\n                  </a>\n                  <span>Google</span><span>Sunnyvale, CA, USA</span>\n                </div>\n                '
            )
        return FakeResponse(status_code=404)

    def fake_post(url, json, timeout, headers):
        assert "nvidia.wd5.myworkdayjobs.com" in url
        return FakeResponse(
            payload={
                "jobPostings": [
                    {
                        "title": "Senior Firmware Engineer, NIC Firmware",
                        "externalPath": "/job/US-WA-Seattle/Senior-Firmware-Engineer_JR1",
                        "locationsText": "4 Locations",
                        "postedOn": "Posted 3 Days Ago",
                    }
                ]
            }
        )

    monkeypatch.setattr("app.services.official_job_sources.requests.get", fake_get)
    monkeypatch.setattr("app.services.official_job_sources.requests.post", fake_post)

    apple_jobs = OfficialJobSourceService.search_company("Apple", target_roles=["Firmware Engineer"], location="USA")
    google_jobs = OfficialJobSourceService.search_company("Google", target_roles=["Firmware Engineer"], location="USA")
    nvidia_jobs = OfficialJobSourceService.search_company("Nvidia", target_roles=["Firmware Engineer"], location="USA")

    assert apple_jobs[0]["company"] == "Apple"
    assert apple_jobs[0]["title"] == "Firmware Engineer"
    assert apple_jobs[0]["resolved_url"] == "https://jobs.apple.com/en-us/details/2001/firmware-engineer"
    assert apple_jobs[0]["source_type"] == "company_site"

    assert google_jobs[0]["company"] == "Google"
    assert google_jobs[0]["title"] == "Firmware Engineer III"
    assert google_jobs[0]["resolved_url"].startswith("https://www.google.com/about/careers/applications/jobs/results/123")
    assert google_jobs[0]["source_type"] == "company_site"

    assert nvidia_jobs[0]["company"] == "NVIDIA"
    assert nvidia_jobs[0]["ats_type"] == "workday"
    assert nvidia_jobs[0]["source_type"] == "ats"
    assert "United States" in nvidia_jobs[0]["location"]


def test_official_job_source_service_parses_configured_company_source_adapters(monkeypatch):
    class FakeResponse:
        def __init__(self, payload=None, status_code=200):
            self._payload = payload
            self.status_code = status_code
            self.ok = 200 <= status_code < 300
            self.text = ""

        def json(self):
            return self._payload

    def fake_get(url, params=None, timeout=8, headers=None):
        if "api/pcsx/search" in url:
            return FakeResponse(
                {
                    "data": {
                        "positions": [
                            {
                                "id": 1,
                                "displayJobId": "MS1",
                                "name": "Firmware Systems Engineer",
                                "standardizedLocations": ["Redmond, WA, US"],
                                "department": "Devices",
                                "positionUrl": "/careers/job/1",
                            }
                        ]
                    }
                }
            )
        if "recruitingCEJobRequisitions" in url:
            return FakeResponse(
                {
                    "items": [
                        {
                            "requisitionList": [
                                {
                                    "Id": "25010924",
                                    "Title": "Digital IC Design & Firmware Engineer",
                                    "PrimaryLocation": "Tucson, AZ, United States",
                                    "ShortDescriptionStr": "Firmware development for embedded systems.",
                                    "PostedDate": "2026-07-01",
                                }
                            ]
                        }
                    ]
                }
            )
        if "careers.rivian.com/api/jobs" in url:
            return FakeResponse(
                {
                    "jobs": [
                        {
                            "data": {
                                "title": "Embedded Firmware Engineer",
                                "apply_url": "https://us-careers-rivian.icims.com/jobs/29644/login",
                                "full_location": "Irvine, CA",
                                "description": "Firmware controls for embedded vehicle systems.",
                            }
                        }
                    ]
                }
            )
        if "boards-api.greenhouse.io/v1/boards/spacex/jobs" in url:
            return FakeResponse(
                {
                    "name": "SpaceX",
                    "jobs": [
                        {
                            "id": "spacex-1",
                            "title": "Firmware Engineer",
                            "absolute_url": "https://job-boards.greenhouse.io/spacex/jobs/1",
                            "location": {"name": "Hawthorne, CA"},
                            "content": "Firmware engineering for flight systems.",
                        }
                    ],
                }
            )
        return FakeResponse(status_code=404)

    def fake_post(url, json, timeout=8, headers=None):
        assert "medtronic.wd1.myworkdayjobs.com" in url
        return FakeResponse(
            {
                "jobPostings": [
                    {
                        "title": "Principal Firmware Engineer",
                        "externalPath": "/job/US-MN-Minneapolis/Principal-Firmware-Engineer_R1",
                        "locationsText": "Minneapolis, MN",
                        "postedOn": "Posted Today",
                    }
                ]
            }
        )

    monkeypatch.setattr("app.services.official_job_sources.requests.get", fake_get)
    monkeypatch.setattr("app.services.official_job_sources.requests.post", fake_post)

    microsoft_jobs = OfficialJobSourceService.search_company("Microsoft", target_roles=["Firmware Engineer"], location="USA")
    ti_jobs = OfficialJobSourceService.search_company("Texas Instruments", target_roles=["Firmware Engineer"], location="USA")
    rivian_jobs = OfficialJobSourceService.search_company("Rivian", target_roles=["Firmware Engineer"], location="USA")
    medtronic_jobs = OfficialJobSourceService.search_company("Medtronic", target_roles=["Firmware Engineer"], location="USA")
    spacex_jobs = OfficialJobSourceService.search_company("SpaceX", target_roles=["Firmware Engineer"], location="USA")

    assert microsoft_jobs[0]["company"] == "Microsoft"
    assert microsoft_jobs[0]["resolved_url"] == "https://apply.careers.microsoft.com/careers/job/1"
    assert ti_jobs[0]["company"] == "Texas Instruments"
    assert ti_jobs[0]["resolved_url"] == "https://careers.ti.com/en/sites/CX/job/25010924"
    assert rivian_jobs[0]["company"] == "Rivian"
    assert rivian_jobs[0]["resolved_url"] == "https://us-careers-rivian.icims.com/jobs/29644/login"
    assert medtronic_jobs[0]["company"] == "Medtronic"
    assert "medtronic.wd1.myworkdayjobs.com" in medtronic_jobs[0]["resolved_url"]
    assert spacex_jobs[0]["company"] == "SpaceX"
    assert spacex_jobs[0]["ats_type"] == "greenhouse"


def test_official_job_source_service_treats_us_state_locations_as_usa():
    assert OfficialJobSourceService._location_maybe_matches("Redmond, WA, US", "USA")
    assert OfficialJobSourceService._location_maybe_matches("Plano, Texas", "USA")
    assert OfficialJobSourceService._location_maybe_matches("Tucson, AZ", "United States")
    assert not OfficialJobSourceService._location_maybe_matches("Toronto, ON, Canada", "USA")


def test_official_job_source_service_can_attempt_every_explicit_company(monkeypatch):
    calls = []

    def fake_search_company(company, target_roles=None, location="", _fetch_cache=None):
        calls.append(company)
        if company == "Apple":
            return [
                {
                    "title": "Firmware Engineer",
                    "company": "Apple",
                    "location": "USA",
                    "description": "Official Apple role.",
                    "url": "https://jobs.apple.com/firmware",
                    "resolved_url": "https://jobs.apple.com/firmware",
                    "source_type": "company_site",
                    "ats_type": None,
                    "resolution_status": "resolved",
                    "fit_score": 0.0,
                }
            ]
        return []

    monkeypatch.setattr(OfficialJobSourceService, "search_company", staticmethod(fake_search_company))

    jobs = OfficialJobSourceService.search_companies(
        ["Apple", "TI", "ST Micro", "John Deere"],
        target_roles=["Firmware Engineer"],
        location="USA",
        target_count=1,
        stop_at_target_count=False,
        prioritise_known_sources=False,
    )

    assert calls == ["Apple", "Texas Instruments", "STMicroelectronics", "Deere"]
    assert [job["company"] for job in jobs] == ["Apple"]


def test_job_search_attempts_all_user_target_companies_before_expansion(monkeypatch):
    calls = []
    target_companies = [
        "Apple",
        "google",
        "microsoft",
        "nvidia",
        "tesla",
        "Qualcomm",
        "TI",
        "Medtronic",
        "John Deere",
        "Garmin",
        "SpaceX",
        "Rivian",
        "Siemens Energy",
        "Toyota",
        "Micron",
        "ST Micro",
    ]

    def fake_search_companies(
        companies,
        target_roles=None,
        location="",
        max_companies=16,
        target_count=None,
        stop_at_target_count=True,
        prioritise_known_sources=True,
    ):
        company_list = list(companies)
        calls.append(
            {
                "companies": company_list,
                "max_companies": max_companies,
                "target_count": target_count,
                "stop_at_target_count": stop_at_target_count,
                "prioritise_known_sources": prioritise_known_sources,
            }
        )
        return [
            {
                "title": "Firmware Engineer",
                "company": "Apple",
                "location": "USA",
                "description": "Official Apple role.",
                "url": "https://jobs.apple.com/firmware",
                "resolved_url": "https://jobs.apple.com/firmware",
                "source_type": "company_site",
                "ats_type": None,
                "resolution_status": "resolved",
                "fit_score": 0.0,
            }
        ]

    monkeypatch.setenv("FORTUNE_MIN_CANDIDATE_JOBS", "1")
    monkeypatch.setattr(job_search_module.OfficialJobSourceService, "search_companies", staticmethod(fake_search_companies))
    monkeypatch.setattr(job_search_module, "scrape_jobs", lambda **_kwargs: pytest.fail("job boards should be skipped"))

    results = job_search_module.JobSearchService.search_jobs(
        "Firmware Engineer",
        "USA",
        target_companies=target_companies,
        target_roles=["Firmware Engineer"],
    )

    assert calls[0] == {
        "companies": target_companies,
        "max_companies": 16,
        "target_count": None,
        "stop_at_target_count": False,
        "prioritise_known_sources": False,
    }
    assert len(calls) == 1
    assert [job["company"] for job in results] == ["Apple"]


def test_job_search_explores_role_relevant_companies_without_board_results(monkeypatch):
    calls = []

    def fake_search_companies(companies, target_roles=None, location="", max_companies=16, target_count=None, stop_at_target_count=True, prioritise_known_sources=True):
        company_list = list(companies)
        calls.append(company_list)
        if "Datadog" in company_list:
            return [
                {
                    "title": "Software Engineer",
                    "company": "Datadog",
                    "location": "Remote",
                    "description": "Official Datadog role.",
                    "url": "https://careers.datadoghq.com/software-engineer",
                    "resolved_url": "https://careers.datadoghq.com/software-engineer",
                    "source_type": "company_site",
                    "ats_type": None,
                    "resolution_status": "resolved",
                    "fit_score": 0.0,
                }
            ]
        return []

    monkeypatch.setattr(job_search_module.OfficialJobSourceService, "search_companies", staticmethod(fake_search_companies))
    monkeypatch.setattr(job_search_module, "scrape_jobs", lambda **_kwargs: job_search_module.pd.DataFrame([]))

    results = job_search_module.JobSearchService.search_jobs(
        "Senior Software Engineer Full-time",
        "Remote",
        target_companies=["Afero"],
        target_roles=["Software Engineer"],
    )

    assert calls[0] == ["Afero"]
    assert any("Datadog" in company_list for company_list in calls[1:])
    assert [job["company"] for job in results] == ["Datadog"]


def test_company_ranking_service_prioritizes_role_relevant_fortune_cohorts():
    fortune_500 = CompanyRankingService.fortune_500_names(
        target_roles=["Firmware Engineer"],
        query="Firmware Engineer",
        limit=4,
    )
    fortune_tail = CompanyRankingService.fortune_1000_tail_names(
        target_roles=["Firmware Engineer"],
        query="Firmware Engineer",
        limit=3,
    )

    assert fortune_500 == ["Apple", "General Motors", "Ford Motor", "Tesla"]
    assert fortune_tail == ["Garmin", "Zebra Technologies", "Teledyne Technologies"]
    assert not set(fortune_500) & set(fortune_tail)


def test_job_search_uses_fortune_500_then_tail_and_skips_boards_when_enough(monkeypatch):
    calls = []

    def make_job(company: str):
        slug = company.lower().replace(" ", "-")
        return {
            "title": "Firmware Engineer",
            "company": company,
            "location": "Remote",
            "description": f"Official {company} firmware role.",
            "url": f"https://careers.example.test/{slug}/firmware",
            "resolved_url": f"https://careers.example.test/{slug}/firmware",
            "source_type": "company_site",
            "ats_type": None,
            "resolution_status": "resolved",
            "fit_score": 0.0,
        }

    def fake_search_companies(companies, target_roles=None, location="", max_companies=16, target_count=None, stop_at_target_count=True, prioritise_known_sources=True):
        company_list = list(companies)
        if company_list:
            calls.append(company_list)
        if company_list == ["Garmin", "Zebra Technologies"]:
            return [make_job("Garmin"), make_job("Zebra Technologies")]
        return []

    def fake_fortune_500_names(**kwargs):
        assert list(kwargs.get("exclude") or []) == ["AllowedCo"]
        return ["Apple", "Tesla"]

    def fake_fortune_tail_names(**kwargs):
        assert set(kwargs.get("exclude") or []) >= {"AllowedCo", "Apple", "Tesla"}
        return ["Garmin", "Zebra Technologies"]

    monkeypatch.setenv("FORTUNE_MIN_CANDIDATE_JOBS", "2")
    monkeypatch.setenv("FORTUNE_COMPANIES_PER_PHASE", "2")
    monkeypatch.setattr(job_search_module.CompanyRankingService, "fortune_500_names", staticmethod(fake_fortune_500_names))
    monkeypatch.setattr(job_search_module.CompanyRankingService, "fortune_1000_tail_names", staticmethod(fake_fortune_tail_names))
    monkeypatch.setattr(job_search_module.OfficialJobSourceService, "search_companies", staticmethod(fake_search_companies))
    monkeypatch.setattr(job_search_module, "scrape_jobs", lambda **_kwargs: pytest.fail("job boards should be skipped"))

    results = job_search_module.JobSearchService.search_jobs(
        "Firmware Engineer",
        "Remote",
        target_companies=["AllowedCo"],
        target_roles=["Firmware Engineer"],
    )

    assert calls[:3] == [["AllowedCo"], ["Apple", "Tesla"], ["Garmin", "Zebra Technologies"]]
    assert [job["company"] for job in results] == ["Garmin", "Zebra Technologies"]


def test_job_search_skips_fortune_tail_when_fortune_500_has_enough_candidates(monkeypatch):
    calls = []

    def make_job(company: str):
        return {
            "title": "Firmware Engineer",
            "company": company,
            "location": "Remote",
            "description": f"Official {company} firmware role.",
            "url": f"https://careers.example.test/{company.lower()}/firmware",
            "resolved_url": f"https://careers.example.test/{company.lower()}/firmware",
            "source_type": "company_site",
            "ats_type": None,
            "resolution_status": "resolved",
            "fit_score": 0.0,
        }

    def fake_search_companies(companies, target_roles=None, location="", max_companies=16, target_count=None, stop_at_target_count=True, prioritise_known_sources=True):
        company_list = list(companies)
        if company_list:
            calls.append(company_list)
        if company_list == ["Apple"]:
            return [make_job("Apple")]
        return []

    monkeypatch.setenv("FORTUNE_MIN_CANDIDATE_JOBS", "1")
    monkeypatch.setenv("FORTUNE_COMPANIES_PER_PHASE", "1")
    monkeypatch.setattr(
        job_search_module.CompanyRankingService,
        "fortune_500_names",
        staticmethod(lambda **_kwargs: ["Apple"]),
    )
    monkeypatch.setattr(
        job_search_module.CompanyRankingService,
        "fortune_1000_tail_names",
        staticmethod(lambda **_kwargs: pytest.fail("Fortune 1000 tail should be skipped")),
    )
    monkeypatch.setattr(job_search_module.OfficialJobSourceService, "search_companies", staticmethod(fake_search_companies))
    monkeypatch.setattr(job_search_module, "scrape_jobs", lambda **_kwargs: pytest.fail("job boards should be skipped"))

    results = job_search_module.JobSearchService.search_jobs(
        "Firmware Engineer",
        "Remote",
        target_roles=["Firmware Engineer"],
    )

    assert calls == [["Apple"]]
    assert [job["company"] for job in results] == ["Apple"]


def test_official_job_source_service_fetches_company_application_links(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self.ok = 200 <= status_code < 300
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, timeout, headers):
        assert headers["User-Agent"] == "JobMatchKit official source crawler"
        if url == "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=false":
            return FakeResponse(
                200,
                {
                    "name": "Acme Robotics",
                    "jobs": [
                        {
                            "id": 123,
                            "title": "Firmware Engineer",
                            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/123",
                            "location": {"name": "Remote"},
                        }
                    ],
                },
            )
        if url == "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true":
            return FakeResponse(
                200,
                {
                    "name": "Acme Robotics",
                    "jobs": [
                        {
                            "id": 123,
                            "title": "Firmware Engineer",
                            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/123",
                            "location": {"name": "Remote"},
                            "content": "<p>Build embedded firmware for connected devices.</p>",
                        },
                        {
                            "id": 456,
                            "title": "Revenue Accountant",
                            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/456",
                            "location": {"name": "Remote"},
                            "content": "<p>Own revenue accounting.</p>",
                        },
                    ],
                },
            )
        return FakeResponse(404, {})

    monkeypatch.setattr("app.services.official_job_sources.requests.get", fake_get)

    jobs = OfficialJobSourceService.search_company(
        "Acme",
        target_roles=["Firmware Engineer"],
        location="Remote",
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Firmware Engineer"
    assert job["company"] == "Acme Robotics"
    assert job["resolved_url"] == "https://job-boards.greenhouse.io/acme/jobs/123"
    assert job["resolution_status"] == "resolved"
    assert job["ats_type"] == "greenhouse"
    assert job["source_type"] == "ats"
    assert "Build embedded firmware" in job["description"]


def test_official_job_source_service_prefers_apply_urls_and_caches_provider_fetches(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self.ok = 200 <= status_code < 300
            self._payload = payload

        def json(self):
            return self._payload

    requested_urls = []

    def fake_get(url, timeout, headers):
        requested_urls.append(url)
        if url == "https://api.lever.co/v0/postings/acme?mode=json":
            return FakeResponse(
                200,
                [
                    {
                        "id": "lever-1",
                        "text": "Firmware Engineer",
                        "applyUrl": "https://jobs.lever.co/acme/lever-1/apply",
                        "hostedUrl": "https://jobs.lever.co/acme/lever-1",
                        "categories": {"location": "Remote"},
                    }
                ],
            )
        if url == "https://api.smartrecruiters.com/v1/companies/acme/postings?limit=100":
            return FakeResponse(
                200,
                {
                    "content": [
                        {
                            "id": "sr-1",
                            "name": "Firmware Engineer",
                            "postingUrl": "https://jobs.smartrecruiters.com/Acme/sr-1",
                            "ref": "https://api.smartrecruiters.com/v1/companies/acme/postings/sr-1",
                            "location": {"fullLocation": "Remote"},
                        }
                    ]
                },
            )
        return FakeResponse(404, {})

    monkeypatch.setattr("app.services.official_job_sources.requests.get", fake_get)

    fetch_cache = {}
    lever_first = OfficialJobSourceService._fetch_provider_postings(
        "lever",
        "acme",
        include_description=True,
        _fetch_cache=fetch_cache,
    )
    lever_second = OfficialJobSourceService._fetch_provider_postings(
        "lever",
        "acme",
        include_description=True,
        _fetch_cache=fetch_cache,
    )
    smartrecruiters = OfficialJobSourceService._fetch_provider_postings(
        "smartrecruiters",
        "acme",
        include_description=True,
        _fetch_cache=fetch_cache,
    )
    greenhouse_miss = OfficialJobSourceService._fetch_provider_postings(
        "greenhouse",
        "acme",
        include_description=False,
        _fetch_cache=fetch_cache,
    )
    greenhouse_miss_again = OfficialJobSourceService._fetch_provider_postings(
        "greenhouse",
        "acme",
        include_description=False,
        _fetch_cache=fetch_cache,
    )

    assert lever_first == lever_second
    assert lever_first[0]["url"] == "https://jobs.lever.co/acme/lever-1/apply"
    assert smartrecruiters[0]["url"] == "https://jobs.smartrecruiters.com/Acme/sr-1"
    assert greenhouse_miss == greenhouse_miss_again == []
    assert requested_urls.count("https://api.lever.co/v0/postings/acme?mode=json") == 1
    assert requested_urls.count("https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=false") == 1


def test_job_search_prefers_official_sources_and_uses_boards_as_discovery(monkeypatch):
    calls = []

    def fake_search_companies(companies, target_roles=None, location="", max_companies=16, target_count=None, stop_at_target_count=True, prioritise_known_sources=True):
        company_list = list(companies)
        calls.append(company_list)
        if company_list == ["Acme"]:
            return [
                {
                    "title": "Firmware Engineer",
                    "company": "Acme",
                    "location": "Remote",
                    "description": "Official Acme role.",
                    "url": "https://job-boards.greenhouse.io/acme/jobs/123",
                    "resolved_url": "https://job-boards.greenhouse.io/acme/jobs/123",
                    "source_type": "ats",
                    "ats_type": "greenhouse",
                    "resolution_status": "resolved",
                    "fit_score": 0.0,
                }
            ]
        if "BoardCo" in company_list:
            return [
                {
                    "title": "Firmware Engineer",
                    "company": "BoardCo",
                    "location": "Remote",
                    "description": "Official BoardCo role.",
                    "url": "https://jobs.lever.co/boardco/abc",
                    "resolved_url": "https://jobs.lever.co/boardco/abc",
                    "source_type": "ats",
                    "ats_type": "lever",
                    "resolution_status": "resolved",
                    "fit_score": 0.0,
                }
            ]
        return []

    def fake_scrape_jobs(**_kwargs):
        return job_search_module.pd.DataFrame(
            [
                {
                    "id": "board-1",
                    "title": "Firmware Engineer",
                    "company": "BoardCo",
                    "location": "Remote",
                    "description": "LinkedIn-discovered role.",
                    "job_url": "https://www.linkedin.com/jobs/view/board-1",
                },
                {
                    "id": "board-2",
                    "title": "Firmware Engineer",
                    "company": "Acme",
                    "location": "Remote",
                    "description": "Duplicate board hint.",
                    "job_url": "https://www.linkedin.com/jobs/view/board-2",
                },
            ]
        )

    def fail_if_duplicate_board_hint_is_resolved(url, company=None, job_title=None):
        raise AssertionError(f"Official duplicate board hint should not be resolved: {url}")

    monkeypatch.setattr(job_search_module.OfficialJobSourceService, "search_companies", staticmethod(fake_search_companies))
    monkeypatch.setattr(job_search_module, "scrape_jobs", fake_scrape_jobs)
    monkeypatch.setattr(
        job_search_module.ApplicationLinkResolver,
        "resolve_url_from_context",
        staticmethod(fail_if_duplicate_board_hint_is_resolved),
    )

    results = job_search_module.JobSearchService.search_jobs(
        "Firmware Engineer",
        "Remote",
        target_companies=["Acme"],
        target_roles=["Firmware Engineer"],
    )

    assert calls[0] == ["Acme"]
    assert any("BoardCo" in company_list for company_list in calls[1:])
    assert [job["url"] for job in results] == [
        "https://job-boards.greenhouse.io/acme/jobs/123",
        "https://jobs.lever.co/boardco/abc",
    ]
    assert results[0]["resolution_status"] == "resolved"
    assert results[1]["resolution_status"] == "resolved"


def test_job_search_board_resolution_timeout_does_not_block(monkeypatch):
    def slow_prepare(_job):
        time.sleep(0.2)
        return {"title": "Slow Role", "company": "SlowCo", "url": "https://example.test/slow"}

    monkeypatch.setenv("BOARD_LINK_RESOLUTION_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setattr(
        job_search_module.JobSearchService,
        "_to_application_ready_board_job",
        staticmethod(slow_prepare),
    )

    started = time.monotonic()
    results = job_search_module.JobSearchService._resolve_application_ready_board_results([
        {
            "title": "Slow Role",
            "company": "SlowCo",
            "url": "https://www.linkedin.com/jobs/view/slow",
        }
    ])

    assert results == []
    assert time.monotonic() - started < 0.18


def test_jobspy_search_timeout_does_not_block_matching(monkeypatch):
    def slow_scrape_jobs(**kwargs):
        time.sleep(0.25)
        return job_search_module.pd.DataFrame([{"title": "Too Slow"}])

    monkeypatch.setenv("JOBSPY_SEARCH_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setattr(job_search_module, "scrape_jobs", slow_scrape_jobs)

    started = time.monotonic()
    results = job_search_module.JobSearchService._scrape_jobspy_with_timeout(
        site_names=["linkedin"],
        search_term="Firmware Engineer",
        location="Remote",
        results_wanted=5,
        hours_old=24,
        country_indeed="USA",
    )

    assert results.empty
    assert time.monotonic() - started < 0.18


def test_job_mirrors_are_not_classified_as_company_sites():
    teal_result = ApplicationLinkResolver.classify_url("https://www.tealhq.com/job/haptics-firmware-engineer_abc")
    campusbuilding_result = ApplicationLinkResolver.classify_url(
        "https://campusbuilding.com/company/microsoft/jobs/firmware-engineer/43323/"
    )

    assert teal_result.source_type == "teal"
    assert teal_result.resolution_status == "needs_resolution"
    assert teal_result.resolved_url is None
    assert ApplicationLinkResolver._is_blocked_search_host("www.tealhq.com")

    assert campusbuilding_result.source_type == "campusbuilding"
    assert campusbuilding_result.resolution_status == "needs_resolution"
    assert campusbuilding_result.resolved_url is None
    assert ApplicationLinkResolver._is_blocked_search_host("campusbuilding.com")


def test_relevant_official_company_search_respects_configured_cap(monkeypatch):
    captured = {}

    def fake_discover_company_names(**kwargs):
        captured["max_companies"] = kwargs["max_companies"]
        return []

    monkeypatch.setenv("RELEVANT_OFFICIAL_COMPANIES_MAX", "3")
    monkeypatch.setattr(
        job_search_module.CompanyDiscoveryService,
        "discover_company_names",
        staticmethod(fake_discover_company_names),
    )

    results = job_search_module.JobSearchService._search_relevant_official_jobs(
        query="Firmware Engineer",
        target_roles=["Firmware Engineer"],
        location="Remote",
        seed_companies=["Afero"],
        board_results=[{"company": "BoardCo", "title": "Firmware Engineer"}],
        max_companies=20,
    )

    assert results == []
    assert captured["max_companies"] == 3


def test_job_search_default_board_fallback_covers_four_role_terms(monkeypatch):
    scraped_terms = []

    def fake_search_companies(companies, target_roles=None, location="", max_companies=16, target_count=None, stop_at_target_count=True, prioritise_known_sources=True):
        return []

    def fake_scrape_jobs(**kwargs):
        search_term = kwargs["search_term"]
        scraped_terms.append(search_term)
        role_slug = search_term.lower().replace(" ", "-")
        return job_search_module.pd.DataFrame(
            [
                {
                    "id": role_slug,
                    "title": search_term,
                    "company": "Acme",
                    "location": "Remote",
                    "description": f"Board-discovered role for {search_term}.",
                    "job_url": f"https://www.linkedin.com/jobs/view/{role_slug}",
                }
            ]
        )

    def fake_resolve_url_from_context(url, company=None, job_title=None):
        role_slug = url.rsplit("/", 1)[-1]
        return LinkResolutionResult(
            original_url=url,
            resolved_url=f"https://jobs.lever.co/acme/{role_slug}/apply",
            source_type="linkedin",
            ats_type="lever",
            resolution_status="resolved",
            notes="Resolved from public company and role metadata.",
        )

    monkeypatch.delenv("MAX_TARGET_ROLE_SEARCH_TERMS", raising=False)
    monkeypatch.setattr(job_search_module.OfficialJobSourceService, "search_companies", staticmethod(fake_search_companies))
    monkeypatch.setattr(job_search_module, "scrape_jobs", fake_scrape_jobs)
    monkeypatch.setattr(
        job_search_module.ApplicationLinkResolver,
        "resolve_url_from_context",
        staticmethod(fake_resolve_url_from_context),
    )

    search_terms = [
        "Senior Software Engineer Full-time",
        "Senior Firmware Engineer Full-time",
        "Senior Data Scientist Full-time",
        "Senior Embedded Engineer Full-time",
    ]
    results = job_search_module.JobSearchService.search_jobs(
        "Senior Software Engineer Full-time",
        "Remote",
        target_roles=["Software Engineer", "Firmware Engineer", "Data Scientist", "Embedded Engineer"],
        search_terms=search_terms,
        use_ranked_companies=False,
    )

    assert scraped_terms == search_terms
    assert {job["title"] for job in results} == set(search_terms)
    assert len(results) == len(search_terms)


def test_job_search_runs_capped_board_fallback_for_multiple_role_terms(monkeypatch):
    scraped_terms = []

    def fake_search_companies(companies, target_roles=None, location="", max_companies=16, target_count=None, stop_at_target_count=True, prioritise_known_sources=True):
        return []

    def fake_scrape_jobs(**kwargs):
        search_term = kwargs["search_term"]
        scraped_terms.append(search_term)
        role_slug = search_term.lower().replace(" ", "-")
        return job_search_module.pd.DataFrame(
            [
                {
                    "id": role_slug,
                    "title": search_term,
                    "company": "Acme",
                    "location": "Remote",
                    "description": f"Board-discovered role for {search_term}.",
                    "job_url": f"https://www.linkedin.com/jobs/view/{role_slug}",
                }
            ]
        )

    def fake_resolve_url_from_context(url, company=None, job_title=None):
        role_slug = url.rsplit("/", 1)[-1]
        return LinkResolutionResult(
            original_url=url,
            resolved_url=f"https://jobs.lever.co/acme/{role_slug}/apply",
            source_type="linkedin",
            ats_type="lever",
            resolution_status="resolved",
            notes="Resolved from public company and role metadata.",
        )

    monkeypatch.setenv("MAX_TARGET_ROLE_SEARCH_TERMS", "2")
    monkeypatch.setattr(job_search_module.OfficialJobSourceService, "search_companies", staticmethod(fake_search_companies))
    monkeypatch.setattr(job_search_module, "scrape_jobs", fake_scrape_jobs)
    monkeypatch.setattr(
        job_search_module.ApplicationLinkResolver,
        "resolve_url_from_context",
        staticmethod(fake_resolve_url_from_context),
    )

    results = job_search_module.JobSearchService.search_jobs(
        "Senior Software Engineer Full-time",
        "Remote",
        target_roles=["Software Engineer", "Firmware Engineer", "Data Scientist"],
        search_terms=[
            "Senior Software Engineer Full-time",
            "Senior Firmware Engineer Full-time",
            "Senior Data Scientist Full-time",
        ],
        use_ranked_companies=False,
    )

    assert scraped_terms == [
        "Senior Software Engineer Full-time",
        "Senior Firmware Engineer Full-time",
    ]
    assert [job["title"] for job in results] == scraped_terms
    assert all(job["source_type"] == "ats" for job in results)
    assert all(job["resolution_status"] == "resolved" for job in results)


def test_job_search_filters_unresolved_board_urls_from_match_results(monkeypatch):
    def fake_search_companies(companies, target_roles=None, location="", max_companies=16, target_count=None, stop_at_target_count=True, prioritise_known_sources=True):
        return []

    def fake_scrape_jobs(**_kwargs):
        return job_search_module.pd.DataFrame(
            [
                {
                    "id": "linkedin-1",
                    "title": "Firmware Engineer",
                    "company": "Afero",
                    "location": "Remote",
                    "description": "LinkedIn-only role.",
                    "job_url": "https://www.linkedin.com/jobs/view/4422710126",
                }
            ]
        )

    monkeypatch.setattr(job_search_module.OfficialJobSourceService, "search_companies", staticmethod(fake_search_companies))
    monkeypatch.setattr(job_search_module, "scrape_jobs", fake_scrape_jobs)
    monkeypatch.setattr(
        job_search_module.ApplicationLinkResolver,
        "resolve_url_from_context",
        staticmethod(lambda url, company=None, job_title=None: ApplicationLinkResolver.classify_url(url)),
    )

    results = job_search_module.JobSearchService.search_jobs(
        "Firmware Engineer",
        "Remote",
        target_companies=["Afero"],
        target_roles=["Firmware Engineer"],
    )

    assert results == []


def test_job_search_rewrites_resolved_board_hint_to_employer_url(monkeypatch):
    linkedin_url = "https://www.linkedin.com/jobs/view/4422710126"
    employer_url = "https://jobs.lever.co/afero/6ab761e7/apply?lever-source=LinkedIn"

    def fake_search_companies(companies, target_roles=None, location="", max_companies=16, target_count=None, stop_at_target_count=True, prioritise_known_sources=True):
        return []

    def fake_scrape_jobs(**_kwargs):
        return job_search_module.pd.DataFrame(
            [
                {
                    "id": "linkedin-1",
                    "title": "Firmware Engineer",
                    "company": "Afero",
                    "location": "Remote",
                    "description": "LinkedIn-discovered role.",
                    "job_url": linkedin_url,
                }
            ]
        )

    def fake_resolve_url_from_context(url, company=None, job_title=None):
        assert url == linkedin_url
        assert company == "Afero"
        assert job_title == "Firmware Engineer"
        return LinkResolutionResult(
            original_url=linkedin_url,
            resolved_url=employer_url,
            source_type="linkedin",
            ats_type="lever",
            resolution_status="resolved",
            notes="Resolved from public company and role metadata.",
        )

    monkeypatch.setattr(job_search_module.OfficialJobSourceService, "search_companies", staticmethod(fake_search_companies))
    monkeypatch.setattr(job_search_module, "scrape_jobs", fake_scrape_jobs)
    monkeypatch.setattr(
        job_search_module.ApplicationLinkResolver,
        "resolve_url_from_context",
        staticmethod(fake_resolve_url_from_context),
    )

    results = job_search_module.JobSearchService.search_jobs(
        "Firmware Engineer",
        "Remote",
        target_companies=["Afero"],
        target_roles=["Firmware Engineer"],
    )

    assert len(results) == 1
    assert results[0]["url"] == employer_url
    assert results[0]["resolved_url"] == employer_url
    assert results[0]["source_url"] == linkedin_url
    assert results[0]["source_type"] == "ats"
    assert results[0]["ats_type"] == "lever"
    assert results[0]["resolution_status"] == "resolved"


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


def test_billing_status_checkout_portal_and_webhook(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_jobmatchkit")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", "price_jobmatchkit_pro")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_jobmatchkit")
    monkeypatch.setenv("PRO_PLAN_PRICE_LABEL", "$10/mo")
    monkeypatch.setenv("FRONTEND_URL", "https://app.jobmatchkit.test")

    calls = {}

    def fake_customer_create(**kwargs):
        calls["customer"] = kwargs
        return {"id": "cus_jobmatchkit"}

    def fake_checkout_create(**kwargs):
        calls["checkout"] = kwargs
        return {"url": "https://checkout.stripe.test/session"}

    def fake_portal_create(**kwargs):
        calls["portal"] = kwargs
        return {"url": "https://billing.stripe.test/session"}

    monkeypatch.setattr(endpoints.stripe.Customer, "create", fake_customer_create)
    monkeypatch.setattr(endpoints.stripe.checkout.Session, "create", fake_checkout_create)
    monkeypatch.setattr(endpoints.stripe.billing_portal.Session, "create", fake_portal_create)

    with TestClient(app) as client:
        auth, headers = register_user(client, "billing")
        user_id = auth["user"]["id"]

        status = client.get("/billing/status", headers=headers)
        assert status.status_code == 200, status.text
        assert status.json()["billing_enabled"] is True
        assert status.json()["can_upgrade"] is True
        assert status.json()["pro_price_label"] == "$10/mo"

        checkout = client.post("/billing/checkout-session", headers=headers)
        assert checkout.status_code == 200, checkout.text
        assert checkout.json()["url"] == "https://checkout.stripe.test/session"
        assert calls["customer"]["email"] == auth["user"]["email"]
        assert calls["customer"]["metadata"]["user_id"] == str(user_id)
        assert calls["checkout"]["mode"] == "subscription"
        assert calls["checkout"]["line_items"] == [{"price": "price_jobmatchkit_pro", "quantity": 1}]
        assert calls["checkout"]["success_url"] == "https://app.jobmatchkit.test/settings?billing=success"

        with Session(engine) as session:
            user = session.get(User, user_id)
            assert user.stripe_customer_id == "cus_jobmatchkit"
            assert user.subscription_tier == "free"

        portal = client.post("/billing/customer-portal", headers=headers)
        assert portal.status_code == 200, portal.text
        assert portal.json()["url"] == "https://billing.stripe.test/session"
        assert calls["portal"] == {
            "customer": "cus_jobmatchkit",
            "return_url": "https://app.jobmatchkit.test/settings?billing=portal_return",
        }

        events = [
            {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "client_reference_id": str(user_id),
                        "customer": "cus_jobmatchkit",
                        "subscription": "sub_jobmatchkit",
                        "payment_status": "paid",
                        "status": "complete",
                        "metadata": {"user_id": str(user_id)},
                    }
                },
            },
            {
                "type": "customer.subscription.updated",
                "data": {
                    "object": {
                        "id": "sub_jobmatchkit",
                        "customer": "cus_jobmatchkit",
                        "status": "active",
                        "current_period_end": 1893456000,
                        "cancel_at_period_end": True,
                        "metadata": {"user_id": str(user_id)},
                        "items": {"data": [{"price": {"id": "price_jobmatchkit_pro"}}]},
                    }
                },
            },
            {
                "type": "customer.subscription.deleted",
                "data": {
                    "object": {
                        "id": "sub_jobmatchkit",
                        "customer": "cus_jobmatchkit",
                        "status": "canceled",
                    }
                },
            },
        ]

        def fake_construct_event(_payload, _signature):
            return events.pop(0)

        monkeypatch.setattr(endpoints, "construct_stripe_event", fake_construct_event)

        webhook = client.post("/billing/webhook", data=b"{}", headers={"Stripe-Signature": "sig_test"})
        assert webhook.status_code == 200, webhook.text
        status_after_checkout = client.get("/user/status", headers=headers).json()
        assert status_after_checkout["user"]["subscription_tier"] == "pro"
        assert status_after_checkout["user"]["subscription_status"] == "active"

        webhook = client.post("/billing/webhook", data=b"{}", headers={"Stripe-Signature": "sig_test"})
        assert webhook.status_code == 200, webhook.text
        status_after_update = client.get("/billing/status", headers=headers).json()
        assert status_after_update["plan"] == "pro"
        assert status_after_update["subscription_cancel_at_period_end"] is True
        assert status_after_update["can_manage_billing"] is True

        webhook = client.post("/billing/webhook", data=b"{}", headers={"Stripe-Signature": "sig_test"})
        assert webhook.status_code == 200, webhook.text
        status_after_delete = client.get("/billing/status", headers=headers).json()
        assert status_after_delete["plan"] == "free"
        assert status_after_delete["can_upgrade"] is True


def test_billing_checkout_completed_without_paid_status_does_not_upgrade(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_jobmatchkit")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", "price_jobmatchkit_pro")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_jobmatchkit")

    with TestClient(app) as client:
        auth, headers = register_user(client, "billing-unpaid")
        user_id = auth["user"]["id"]
        with Session(engine) as session:
            user = session.get(User, user_id)
            user.stripe_customer_id = "cus_unpaid"
            session.add(user)
            session.commit()

        def fake_construct_event(_payload, _signature):
            return {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "client_reference_id": str(user_id),
                        "customer": "cus_unpaid",
                        "subscription": "sub_unpaid",
                        "payment_status": "unpaid",
                        "status": "complete",
                        "metadata": {"user_id": str(user_id)},
                    }
                },
            }

        monkeypatch.setattr(endpoints, "construct_stripe_event", fake_construct_event)

        webhook = client.post("/billing/webhook", data=b"{}", headers={"Stripe-Signature": "sig_test"})
        assert webhook.status_code == 200, webhook.text
        status = client.get("/billing/status", headers=headers).json()
        assert status["plan"] == "free"
        assert status["subscription_status"] == "incomplete"


def test_billing_checkout_requires_configuration(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_PRO_PRICE_ID", raising=False)

    with TestClient(app) as client:
        _, headers = register_user(client, "billing-disabled")
        status = client.get("/billing/status", headers=headers)
        assert status.status_code == 200, status.text
        assert status.json()["billing_enabled"] is False

        checkout = client.post("/billing/checkout-session", headers=headers)
        assert checkout.status_code == 503, checkout.text
        assert checkout.json()["detail"] == "Billing is not configured for this environment."


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

        all_apps = client.get("/applications?match_bucket=all", headers=headers)
        assert all_apps.status_code == 200, all_apps.text
        assert {item["job_title"] for item in all_apps.json()} == {
            "Strong Role",
            "Low Role",
        }

        screened = client.get("/applications?match_bucket=screened_out", headers=headers)
        assert screened.status_code == 400

        invalid = client.get("/applications?match_bucket=unknown", headers=headers)
        assert invalid.status_code == 400

        with Session(engine) as session:
            session.add(
                AgentRun(
                    user_id=user_id,
                    status="completed",
                    found_jobs_count=2,
                    applications_count=1,
                    logs=["AI scored 2 roles: 1 met your 75% minimum score and 1 stayed below threshold."],
                )
            )
            session.commit()

        summary = client.get("/applications/summary", headers=headers)
        assert summary.status_code == 200, summary.text
        summary_body = summary.json()
        assert summary_body["strong_count"] == 1
        assert summary_body["below_threshold_count"] == 1
        assert summary_body["visible_count"] == 2
        assert summary_body["min_match_score"] == 75
        assert summary_body["latest_run"]["found_jobs_count"] == 2
        assert summary_body["latest_run"]["applications_count"] == 1


def test_clear_applications_removes_related_history_and_preserves_other_users():
    with TestClient(app) as client:
        auth, headers = register_user(client, "clear-applications")
        other_auth, _ = register_user(client, "clear-applications-other")
        user_id = auth["user"]["id"]
        other_user_id = other_auth["user"]["id"]

        with Session(engine) as session:
            agent_run = AgentRun(user_id=user_id, status="completed")
            app_record = Application(
                user_id=user_id,
                job_title="Clearable Role",
                company="Acme",
                job_url="https://example.test/clearable",
                resolved_url="https://boards.greenhouse.io/acme/jobs/123",
                source_type="ats",
                ats_type="greenhouse",
                resolution_status="resolved",
                status="Needs Review",
                fit_score=0.91,
            )
            other_app = Application(
                user_id=other_user_id,
                job_title="Other User Role",
                company="OtherCo",
                job_url="https://example.test/other-user",
                status="Analyzed",
                fit_score=0.82,
            )
            session.add(agent_run)
            session.add(app_record)
            session.add(other_app)
            session.commit()
            session.refresh(agent_run)
            session.refresh(app_record)
            session.refresh(other_app)

            review = ApplicationFillReview(
                user_id=user_id,
                application_id=app_record.id,
                ats_type="greenhouse",
                application_url=app_record.resolved_url,
                status="ready_for_review",
                message="Prepared in clear test.",
                fields_filled=["First name", "Email"],
                fields_missing=[],
                blockers=[],
            )
            session.add(review)
            session.commit()
            session.refresh(review)

            legacy_review = ApplicationFillReview(
                user_id=other_user_id,
                application_id=app_record.id,
                ats_type="greenhouse",
                application_url=app_record.resolved_url,
                status="ready_for_review",
                message="Legacy mismatched owner record.",
                fields_filled=[],
                fields_missing=[],
                blockers=[],
            )
            session.add(legacy_review)
            session.commit()
            session.refresh(legacy_review)

            screenshot_path = FillReviewArtifactStore.save_base64(
                user_id=user_id,
                application_id=app_record.id,
                review_id=review.id,
                kind="screenshot",
                payload_base64=base64.b64encode(b"clear-png").decode("ascii"),
                extension="png",
            )
            trace_path = FillReviewArtifactStore.save_base64(
                user_id=user_id,
                application_id=app_record.id,
                review_id=review.id,
                kind="trace",
                payload_base64=base64.b64encode(b"clear-zip").decode("ascii"),
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
                    action="submit_confirmation",
                    status="ready",
                    message="Prepared for confirmation.",
                )
            )
            session.add(
                ApplicationAnswerAudit(
                    user_id=user_id,
                    application_id=app_record.id,
                    action="automation_read",
                    access_reason="submit_readiness",
                    source="submit_readiness",
                    fields=["work_authorized_us"],
                )
            )
            session.commit()
            app_id = app_record.id
            other_app_id = other_app.id
            attempt_id = attempt.id
            legacy_review_id = legacy_review.id

        response = client.delete("/applications", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["message"] == "Cleared 1 saved application across all matching profiles."

        with Session(engine) as session:
            assert session.get(Application, app_id) is None
            assert session.get(Application, other_app_id) is not None
            assert session.exec(
                select(ApplicationFillReview).where(ApplicationFillReview.user_id == user_id)
            ).all() == []
            assert session.get(ApplicationFillReview, legacy_review_id) is None
            assert session.exec(
                select(AutoApplyAttempt).where(AutoApplyAttempt.user_id == user_id)
            ).all() == []
            assert session.exec(
                select(AutoApplyAudit).where(AutoApplyAudit.auto_apply_attempt_id == attempt_id)
            ).all() == []
            answer_audit = session.exec(
                select(ApplicationAnswerAudit).where(ApplicationAnswerAudit.user_id == user_id)
            ).one()
            assert answer_audit.application_id is None

        assert screenshot_path is not None
        assert trace_path is not None
        assert not Path(screenshot_path).exists()
        assert not Path(trace_path).exists()


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
                    "resume_improvements": [
                        "Add a targeted Backend Engineer summary that highlights FastAPI, SQL, and automation outcomes.",
                        "Rewrite the most relevant backend bullets with measurable platform impact.",
                    ],
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
        assert body["resume_improvements"][0].startswith("Add a targeted Backend Engineer summary")
        assert body["talking_points"] == ["FastAPI", "SQL", "Automation", "Ownership"]
        assert body["qa_answers"][0]["answer"] == "Strong platform fit."
        assert body["interview_questions"][0]["question"] == "Tell me about yourself"
        assert body["company_brief"]["overview"] == "Acme builds platform tools."

        with Session(engine) as session:
            saved_app = session.get(Application, app_id)
        assert saved_app.cover_letter == body["cover_letter"]

        zip_response = client.post(
            f"/applications/{app_id}/package.zip",
            json=body,
            headers=headers,
        )

        assert zip_response.status_code == 200, zip_response.text
        assert zip_response.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(zip_response.content)) as package_zip:
            assert package_zip.namelist() == [
                "01-cover-letter.pdf",
                "02-resume-improvements.pdf",
                "03-application-notes.pdf",
                "copy-paste-fields.txt",
            ]
            assert package_zip.read("01-cover-letter.pdf").startswith(b"%PDF")
            assert package_zip.read("02-resume-improvements.pdf").startswith(b"%PDF")
            assert package_zip.read("03-application-notes.pdf").startswith(b"%PDF")
            copy_fields = package_zip.read("copy-paste-fields.txt").decode("utf-8")
            assert "Dear Hiring Manager" in copy_fields
            assert "Resume improvements" in copy_fields
            assert "measurable platform impact" in copy_fields
            assert "Why Acme?" in copy_fields
            assert "How is success measured?" in copy_fields


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
            screened_app = Application(
                user_id=user_id,
                job_title="Screened Export Role",
                company="SkipCo",
                job_url="https://example.test/screened-export-role",
                status="Screened Out",
                fit_score=0.0,
                pre_screen_status="reject",
                pre_screen_reasons=["Obvious non-fit."],
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
            session.add(screened_app)
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
        assert body["applications"][0]["pre_screen_reasons"] == []
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
        assert "Screened Export Role" not in body_text
        assert "user_id" not in body_text

        assert client.get("/account/export").status_code == 401


def test_applications_normalize_legacy_null_pre_screen_reasons():
    with TestClient(app) as client:
        auth, headers = register_user(client, "legacy-prescreen")
        user_id = auth["user"]["id"]
        with Session(engine) as session:
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Legacy Null Reason Role",
                    company="Acme",
                    job_url="https://example.test/legacy-null-reason",
                    status="Analyzed",
                    fit_score=0.92,
                    pre_screen_status="not_screened",
                )
            )
            session.commit()

        response = client.get("/applications?match_bucket=all", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body[0]["job_title"] == "Legacy Null Reason Role"
        assert body[0]["pre_screen_reasons"] == []


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

    external_apply = ApplicationLinkResolver._normalize_external_candidate(
        "https://www.linkedin.com/jobs/view/externalApply/123?url=https%3A%2F%2Fboards.greenhouse.io%2Facme%2Fjobs%2F123",
        "https://www.linkedin.com/jobs/view/123",
        "linkedin",
    )
    assert external_apply == "https://boards.greenhouse.io/acme/jobs/123"
    assert ApplicationLinkResolver._is_external_apply_candidate("Apply on company website") is True
    assert ApplicationLinkResolver._is_external_apply_candidate("Easy Apply") is False

    company_site = ApplicationLinkResolver.classify_url("https://careers.example.com/jobs/123")
    assert company_site.source_type == "company_site"
    assert company_site.resolution_status == "resolved"


def test_application_link_resolver_resolves_linkedin_via_lever_context(monkeypatch):
    class FakeResponse:
        status_code = 200
        ok = True

        def json(self):
            return [
                {
                    "text": "Accounting and Payroll Generalist",
                    "applyUrl": "https://jobs.lever.co/afero/fd0bc3ee/apply",
                },
                {
                    "text": "Firmware Engineer",
                    "applyUrl": "https://jobs.lever.co/afero/6ab761e7-84f8-4034-ab29-edbca4d14ad3/apply",
                },
            ]

    requested_urls = []

    def fake_get(url, timeout, headers):
        requested_urls.append(url)
        return FakeResponse()

    monkeypatch.setattr("app.services.application_link_resolver.requests.get", fake_get)
    monkeypatch.setattr(ApplicationLinkResolver, "_search_career_candidates", staticmethod(lambda company, job_title: []))

    result = asyncio.run(
        ApplicationLinkResolver.resolve_url(
            "https://www.linkedin.com/jobs/view/4422710126",
            company="Afero",
            job_title="Firmware Engineer",
        )
    )

    assert requested_urls == ["https://api.lever.co/v0/postings/afero?mode=json"]
    assert result.resolution_status == "resolved"
    assert result.source_type == "linkedin"
    assert result.ats_type == "lever"
    assert result.resolved_url == "https://jobs.lever.co/afero/6ab761e7-84f8-4034-ab29-edbca4d14ad3/apply?lever-source=LinkedIn"


@pytest.mark.parametrize(
    "source_url,expected_source,expected_ats,payload,expected_url",
    [
        (
            "https://www.indeed.com/viewjob?jk=abc123",
            "indeed",
            "greenhouse",
            {"jobs": [{"title": "Backend Engineer", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/123"}]},
            "https://job-boards.greenhouse.io/acme/jobs/123",
        ),
        (
            "https://www.google.com/search?q=backend+engineer+jobs",
            "google_jobs",
            "ashby",
            {"jobs": [{"title": "Backend Engineer", "jobUrl": "https://jobs.ashbyhq.com/acme/123"}]},
            "https://jobs.ashbyhq.com/acme/123",
        ),
        (
            "https://www.ziprecruiter.com/jobs/acme-backend-engineer-abc123",
            "ziprecruiter",
            "smartrecruiters",
            {"content": [{"name": "Backend Engineer", "ref": "https://jobs.smartrecruiters.com/Acme/123"}]},
            "https://jobs.smartrecruiters.com/Acme/123",
        ),
        (
            "https://www.glassdoor.com/job-listing/backend-engineer-acme-JV.htm",
            "glassdoor",
            "lever",
            [{"text": "Backend Engineer", "applyUrl": "https://jobs.lever.co/acme/123/apply"}],
            "https://jobs.lever.co/acme/123/apply?lever-source=Glassdoor",
        ),
    ],
)
def test_application_link_resolver_resolves_common_job_boards_via_public_ats_context(
    monkeypatch,
    source_url,
    expected_source,
    expected_ats,
    payload,
    expected_url,
):
    class FakeResponse:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self.ok = 200 <= status_code < 300
            self._body = body

        def json(self):
            return self._body

    ats_url_fragments = {
        "lever": "api.lever.co/v0/postings/acme",
        "greenhouse": "boards-api.greenhouse.io/v1/boards/acme/jobs",
        "ashby": "api.ashbyhq.com/posting-api/job-board/acme",
        "smartrecruiters": "api.smartrecruiters.com/v1/companies/acme/postings",
    }
    requested_urls = []

    def fake_get(url, timeout, headers):
        requested_urls.append(url)
        if ats_url_fragments[expected_ats] in url:
            return FakeResponse(200, payload)
        return FakeResponse(404, {})

    monkeypatch.setattr("app.services.application_link_resolver.requests.get", fake_get)
    monkeypatch.setattr(ApplicationLinkResolver, "_search_career_candidates", staticmethod(lambda company, job_title: []))

    result = asyncio.run(
        ApplicationLinkResolver.resolve_url(
            source_url,
            company="Acme",
            job_title="Backend Engineer",
            allow_browser=False,
        )
    )

    assert any(ats_url_fragments[expected_ats] in url for url in requested_urls)
    assert result.source_type == expected_source
    assert result.resolution_status == "resolved"
    assert result.ats_type == expected_ats
    assert result.resolved_url == expected_url


def test_application_link_resolver_can_upgrade_company_page_to_public_ats_context(monkeypatch):
    class FakeResponse:
        ok = True

        def json(self):
            return {"jobs": [{"title": "Backend Engineer", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/123"}]}

    def fake_get(url, timeout, headers):
        if "boards-api.greenhouse.io/v1/boards/acme/jobs" in url:
            return FakeResponse()
        return type("MissingResponse", (), {"ok": False, "status_code": 404, "json": lambda self: {}})()

    monkeypatch.setattr("app.services.application_link_resolver.requests.get", fake_get)

    result = asyncio.run(
        ApplicationLinkResolver.resolve_url(
            "https://careers.acme.com/jobs/backend-engineer",
            company="Acme",
            job_title="Backend Engineer",
            allow_browser=False,
        )
    )

    assert result.source_type == "company_site"
    assert result.resolution_status == "resolved"
    assert result.ats_type == "greenhouse"
    assert result.resolved_url == "https://job-boards.greenhouse.io/acme/jobs/123"


def test_application_link_resolver_accepts_validated_official_career_search_hit(monkeypatch):
    tesla_url = "https://www.tesla.com/careers/search/job/firmware-engineer-silicon-tesla-ai-263752"

    class FakeResponse:
        def __init__(self, status_code=404, body=""):
            self.status_code = status_code
            self.ok = 200 <= status_code < 300
            self.text = body

        def json(self):
            return {}

    def fake_get(url, timeout, headers, allow_redirects=True):
        if url == tesla_url:
            return FakeResponse(403, "Access denied")
        return FakeResponse(404)

    monkeypatch.setattr("app.services.application_link_resolver.requests.get", fake_get)
    monkeypatch.setattr(
        ApplicationLinkResolver,
        "_search_career_candidates",
        staticmethod(
            lambda company, job_title: [
                CareerSearchCandidate(
                    title="Firmware Engineer, Silicon, Tesla AI | Tesla Careers",
                    url=tesla_url,
                )
            ]
        ),
    )

    result = asyncio.run(
        ApplicationLinkResolver.resolve_url(
            "https://www.linkedin.com/jobs/view/4420217676",
            company="Tesla",
            job_title="Firmware Engineer, Silicon, Tesla AI",
            allow_browser=False,
        )
    )

    assert result.source_type == "linkedin"
    assert result.resolution_status == "resolved"
    assert result.ats_type is None
    assert result.resolved_url == tesla_url


def test_application_link_resolver_marks_linkedin_onsite_apply_as_unsupported(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code=404, body=""):
            self.status_code = status_code
            self.ok = 200 <= status_code < 300
            self.text = body

        def json(self):
            return {}

    def fake_get(url, timeout, headers, allow_redirects=True):
        if "jobs-guest/jobs/api/jobPosting/4417963129" in url:
            return FakeResponse(200, '<button data-tracking-control-name="public_jobs_apply-link-onsite">Apply</button>')
        return FakeResponse(404)

    monkeypatch.setattr("app.services.application_link_resolver.requests.get", fake_get)
    monkeypatch.setattr(ApplicationLinkResolver, "_search_career_candidates", staticmethod(lambda company, job_title: []))

    result = asyncio.run(
        ApplicationLinkResolver.resolve_url(
            "https://www.linkedin.com/jobs/view/4417963129",
            company="Yotta Energy",
            job_title="Senior Firmware Engineer",
            allow_browser=False,
        )
    )

    assert result.source_type == "linkedin"
    assert result.resolution_status == "unsupported"
    assert result.resolved_url == "https://www.linkedin.com/jobs/view/4417963129"
    assert "onsite" in result.notes.lower()


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

        with Session(engine) as session:
            saved = session.exec(
                select(Application).where(
                    Application.user_id == user_id,
                    Application.job_url == "https://www.linkedin.com/jobs/view/999",
                )
            ).first()
            assert saved is not None
            assert saved.source_url == "https://www.linkedin.com/jobs/view/999"
            assert saved.resolved_url is None
            assert saved.source_type == "linkedin"
            assert saved.ats_type is None
            assert saved.resolution_status == "needs_resolution"

        response = client.get("/applications", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == []


def test_applications_hide_unresolved_aggregator_source_pages():
    with TestClient(app) as client:
        auth, headers = register_user(client, "hide-source-pages")
        user_id = auth["user"]["id"]

        with Session(engine) as session:
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Raw LinkedIn Role",
                    company="Afero",
                    job_url="https://www.linkedin.com/jobs/view/123",
                    source_type="linkedin",
                    resolution_status="needs_resolution",
                    status="Identified",
                    fit_score=0.88,
                )
            )
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Resolved Board Role",
                    company="Afero",
                    job_url="https://jobs.lever.co/afero/123/apply",
                    source_url="https://www.linkedin.com/jobs/view/456",
                    resolved_url="https://jobs.lever.co/afero/123/apply",
                    source_type="linkedin",
                    ats_type="lever",
                    resolution_status="resolved",
                    status="Analyzed",
                    fit_score=0.91,
                )
            )
            session.add(
                Application(
                    user_id=user_id,
                    job_title="Direct Employer Role",
                    company="Acme",
                    job_url="https://boards.greenhouse.io/acme/jobs/123",
                    resolved_url="https://boards.greenhouse.io/acme/jobs/123",
                    source_type="ats",
                    ats_type="greenhouse",
                    resolution_status="resolved",
                    status="Analyzed",
                    fit_score=0.93,
                )
            )
            session.commit()

        response = client.get("/applications", headers=headers)
        assert response.status_code == 200, response.text
        titles = {item["job_title"] for item in response.json()}
        assert "Raw LinkedIn Role" not in titles
        assert "Resolved Board Role" in titles
        assert "Direct Employer Role" in titles


def test_persistence_preserves_existing_resolved_link_metadata():
    with TestClient(app) as client:
        auth, headers = register_user(client, "link-resolution-preserve")
        user_id = auth["user"]["id"]

        base_job = {
            "title": "Firmware Engineer",
            "company": "Afero",
            "url": "https://www.linkedin.com/jobs/view/4422710126",
            "fit_score": 0.91,
        }
        resolved_job = {
            **base_job,
            "source_url": base_job["url"],
            "resolved_url": "https://jobs.lever.co/afero/6ab761e7-84f8-4034-ab29-edbca4d14ad3/apply?lever-source=LinkedIn",
            "source_type": "linkedin",
            "ats_type": "lever",
            "resolution_status": "resolved",
            "resolution_notes": "Resolved in test.",
        }

        PersistenceService.save_job(user_id, resolved_job, "Needs Review")
        PersistenceService.save_job(user_id, base_job, "Analyzed")

        response = client.get("/applications", headers=headers)
        assert response.status_code == 200, response.text
        app_body = response.json()[0]
        assert app_body["resolution_status"] == "resolved"
        assert app_body["ats_type"] == "lever"
        assert app_body["resolved_url"] == resolved_job["resolved_url"]


def test_persistence_does_not_degrade_existing_analysis_with_discovery_or_failed_status():
    with TestClient(app) as client:
        auth, headers = register_user(client, "persistence-no-degrade")
        user_id = auth["user"]["id"]

        analyzed_job = {
            "title": "Firmware Engineer",
            "company": "Afero",
            "url": "https://jobs.lever.co/afero/role-123",
            "resolved_url": "https://jobs.lever.co/afero/role-123",
            "source_type": "ats",
            "ats_type": "lever",
            "resolution_status": "resolved",
            "fit_score": 0.91,
            "explanation": "Strong embedded firmware fit.",
            "cover_letter": "A strong generated cover letter.",
        }
        rediscovered_job = {
            "title": "Firmware Engineer",
            "company": "Afero",
            "url": "https://www.linkedin.com/jobs/view/4422710126",
            "fit_score": 0.0,
            "cover_letter": "Analysis failed due to LLM error.",
        }

        PersistenceService.save_job(user_id, analyzed_job, "Analyzed")
        PersistenceService.save_job(user_id, rediscovered_job, "Identified")
        PersistenceService.save_job(user_id, rediscovered_job, "Analysis Failed")

        response = client.get("/applications", headers=headers)
        assert response.status_code == 200, response.text
        apps = response.json()
        assert len(apps) == 1
        app_body = apps[0]
        assert app_body["status"] == "Analyzed"
        assert app_body["fit_score"] == 0.91
        assert app_body["explanation"] == "Strong embedded firmware fit."
        assert app_body["cover_letter"] == "A strong generated cover letter."
        assert app_body["resolved_url"] == analyzed_job["resolved_url"]


def test_analyze_fit_auto_resolves_analyzed_matches_without_browser(monkeypatch):
    class FakeAnalysisChain:
        def __or__(self, _other):
            return self

        async def ainvoke(self, payload):
            if payload["company"] == "Afero":
                return {
                    "score": 0.91,
                    "explanation": "Strong firmware match.",
                    "cover_letter": "Dear Afero,",
                }
            return {
                "score": 0.55,
                "explanation": "Below threshold.",
                "cover_letter": "Dear Acme,",
            }

    saved_jobs = []
    resolver_calls = []
    lever_url = "https://jobs.lever.co/afero/6ab761e7-84f8-4034-ab29-edbca4d14ad3/apply?lever-source=LinkedIn"

    async def fake_resolve_url(url, timeout_ms=30000, company=None, job_title=None, allow_browser=True):
        resolver_calls.append(
            {
                "url": url,
                "company": company,
                "job_title": job_title,
                "allow_browser": allow_browser,
            }
        )
        return LinkResolutionResult(
            original_url=url,
            resolved_url=lever_url,
            source_type="linkedin",
            ats_type="lever",
            resolution_status="resolved",
            notes="Resolved in test.",
        )

    monkeypatch.setattr(nodes, "get_llm", lambda: object())
    monkeypatch.setattr(nodes.ChatPromptTemplate, "from_messages", staticmethod(lambda _messages: FakeAnalysisChain()))
    monkeypatch.setattr(nodes.ApplicationLinkResolver, "resolve_url", staticmethod(fake_resolve_url))
    monkeypatch.setattr(
        PersistenceService,
        "save_job",
        staticmethod(lambda user_id, job, status, **_kwargs: saved_jobs.append((user_id, job.copy(), status))),
    )

    state = {
        "resume_summary": "Firmware engineer with embedded systems experience.",
        "preferences": FakePrefs(),
        "found_jobs": [
            {
                "title": "Firmware Engineer",
                "company": "Afero",
                "description": "Embedded firmware role.",
                "url": "https://www.linkedin.com/jobs/view/4422710126",
            },
            {
                "title": "Support Engineer",
                "company": "Acme",
                "description": "Support-heavy role.",
                "url": "https://www.linkedin.com/jobs/view/123",
            },
        ],
        "logs": [],
        "user_id": 42,
        "agent_run_id": 99,
    }

    result = asyncio.run(nodes.analyze_fit(state))

    assert result["application_status"] == "analyzing"
    assert resolver_calls == [
        {
            "url": "https://www.linkedin.com/jobs/view/4422710126",
            "company": "Afero",
            "job_title": "Firmware Engineer",
            "allow_browser": False,
        },
        {
            "url": "https://www.linkedin.com/jobs/view/123",
            "company": "Acme",
            "job_title": "Support Engineer",
            "allow_browser": False,
        },
    ]
    assert saved_jobs[0][1]["resolved_url"] == lever_url
    assert saved_jobs[0][1]["ats_type"] == "lever"
    assert saved_jobs[0][2] == "Analyzed"
    assert saved_jobs[1][1]["resolved_url"] == lever_url
    assert saved_jobs[1][1]["ats_type"] == "lever"
    assert saved_jobs[1][2] == "Analyzed"


def test_analyze_fit_times_out_slow_individual_jobs(monkeypatch):
    class SlowAnalysisChain:
        def __or__(self, _other):
            return self

        async def ainvoke(self, _payload):
            await asyncio.sleep(0.2)
            return {
                "score": 0.91,
                "explanation": "This response should arrive too late.",
                "cover_letter": "Dear team,",
            }

    saved_jobs = []
    resolver_calls = []

    async def fake_resolve_url(*args, **kwargs):
        resolver_calls.append((args, kwargs))
        return LinkResolutionResult(
            original_url=kwargs.get("url") or args[0],
            resolved_url="https://jobs.lever.co/acme/123",
            source_type="linkedin",
            ats_type="lever",
            resolution_status="resolved",
            notes="Resolved in test.",
        )

    monkeypatch.setattr(nodes, "get_llm", lambda: object())
    monkeypatch.setattr(nodes, "llm_analysis_timeout_seconds", lambda: 0.05)
    monkeypatch.setattr(nodes, "llm_analysis_concurrency", lambda: 1)
    monkeypatch.setattr(nodes.ChatPromptTemplate, "from_messages", staticmethod(lambda _messages: SlowAnalysisChain()))
    monkeypatch.setattr(nodes.ApplicationLinkResolver, "resolve_url", staticmethod(fake_resolve_url))
    monkeypatch.setattr(
        PersistenceService,
        "save_job",
        staticmethod(lambda user_id, job, status, **_kwargs: saved_jobs.append((user_id, job.copy(), status))),
    )

    state = {
        "resume_summary": "Firmware engineer with embedded systems experience.",
        "preferences": FakePrefs(),
        "found_jobs": [
            {
                "title": "Firmware Engineer",
                "company": "Acme",
                "description": "Embedded firmware role.",
                "url": "https://www.linkedin.com/jobs/view/slow",
            },
        ],
        "logs": [],
        "user_id": 42,
        "agent_run_id": 99,
    }

    started = time.monotonic()
    result = asyncio.run(nodes.analyze_fit(state))

    assert time.monotonic() - started < 0.18
    assert result["application_status"] == "analyzing"
    assert resolver_calls == []
    assert saved_jobs[0][2] == "Analysis Failed"
    assert saved_jobs[0][1]["fit_score"] == 0.0
    assert "Timed out after 0.05s" in saved_jobs[0][1]["explanation"]
    assert "1 failed or timed out" in result["logs"][-1]


def test_resolve_application_link_endpoint_updates_owned_application(monkeypatch):
    async def fake_resolve_url(
        url: str,
        timeout_ms: int = 30000,
        company: str | None = None,
        job_title: str | None = None,
        allow_browser: bool = True,
    ):
        assert url == "https://www.linkedin.com/jobs/view/999"
        assert company == "Acme"
        assert job_title == "Resolved Role"
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

        with Session(engine) as session:
            app_record = session.exec(
                select(Application).where(
                    Application.user_id == user_id,
                    Application.job_url == "https://www.linkedin.com/jobs/view/999",
                )
            ).first()
            assert app_record is not None
            app_id = app_record.id

        response = client.post(f"/applications/{app_id}/resolve-link", headers=headers)

        assert response.status_code == 200, response.text
        resolved = response.json()
        assert resolved["source_url"] == "https://www.linkedin.com/jobs/view/999"
        assert resolved["resolved_url"] == "https://boards.greenhouse.io/acme/jobs/999"
        assert resolved["source_type"] == "linkedin"
        assert resolved["ats_type"] == "greenhouse"
        assert resolved["resolution_status"] == "resolved"
        assert resolved["resolution_notes"] == "Resolved in test."

        _, other_headers = register_user(client, "resolve-other")
        denied = client.post(f"/applications/{app_id}/resolve-link", headers=other_headers)
        assert denied.status_code == 404


def test_browser_automation_application_routes_are_retired():
    with TestClient(app) as client:
        auth, headers = register_user(client, "automation-retired")
        user_id = auth["user"]["id"]
        prepare_agent_setup(client, headers)

        with Session(engine) as session:
            saved_app = Application(
                user_id=user_id,
                job_title="Retired Automation Role",
                company="Acme",
                job_url="https://boards.greenhouse.io/acme/jobs/123",
                resolved_url="https://boards.greenhouse.io/acme/jobs/123",
                source_type="ats",
                ats_type="greenhouse",
                resolution_status="resolved",
                status="Analyzed",
                fit_score=0.92,
            )
            session.add(saved_app)
            session.commit()
            session.refresh(saved_app)
            app_id = saved_app.id

        routes = [
            ("post", f"/applications/{app_id}/fill-review"),
            ("get", f"/applications/{app_id}/fill-reviews"),
            ("get", f"/applications/{app_id}/automation-attempts"),
            ("get", f"/applications/{app_id}/fill-reviews/1/screenshot"),
            ("get", f"/applications/{app_id}/fill-reviews/1/trace"),
            ("delete", f"/applications/{app_id}/fill-reviews"),
            ("post", f"/applications/{app_id}/submit-readiness"),
            ("post", f"/applications/{app_id}/submit-confirmation"),
        ]
        for method, route in routes:
            response = getattr(client, method)(route, headers=headers)
            assert response.status_code == 410, response.text
            assert "Apply with assistant and Application Prep have been removed" in response.json()["detail"]


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


def test_submit_application_treats_retired_auto_apply_as_manual_review(monkeypatch):
    monkeypatch.setattr(PersistenceService, "save_job", staticmethod(lambda *args, **kwargs: None))

    job_url = "https://www.linkedin.com/jobs/view/123"
    state = {
        "preferences": FakePrefs(),
        "analyzed_jobs": [
            {
                "title": "Aggregator Role",
                "company": "LinkedIn Source",
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
    assert result["application_status"] == "completed"
    assert result["auto_apply_audit"] == []
    assert result["logs"] == ["Ready to review Aggregator Role at LinkedIn Source"]


def test_apply_browser_is_retired_noop():
    result = asyncio.run(apply_browser({"auto_apply": True, "logs": ["existing"]}))
    assert result == {"application_status": "completed"}


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
    assert "Legacy browser automation never performs final submit" in result["message"]


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


def test_submission_settings_contract_keeps_submit_routes_retired(monkeypatch):
    with TestClient(app) as client:
        auth, headers = register_user(client, "submit-settings")
        user_id = auth["user"]["id"]
        prepare_agent_setup(client, headers)

        with Session(engine) as session:
            user = session.get(User, user_id)
            user.subscription_tier = "pro"
            session.add(user)
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

        default_settings = client.get("/submission-settings", headers=headers)
        assert default_settings.status_code == 200, default_settings.text
        assert default_settings.json()["true_submit_enabled"] is False

        settings_response = client.post(
            "/submission-settings",
            headers=headers,
            json={
                "true_submit_enabled": True,
                "require_human_confirmation": True,
                "min_fit_score": 85,
                "max_submits_per_day": 3,
                "allowed_companies": ["Acme, Globex", "Bank of America", " acme "],
                "denied_companies": ["Nope; Bad Corp"],
                "allowed_domains": ["greenhouse.io  lever.co"],
                "denied_domains": [],
                "allowed_job_title_keywords": ["Backend, Platform"],
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
        assert settings_body["allowed_companies"] == ["Acme", "Globex", "Bank of America"]
        assert settings_body["denied_companies"] == ["Nope", "Bad Corp"]
        assert settings_body["allowed_domains"] == ["greenhouse.io", "lever.co"]
        assert settings_body["allowed_job_title_keywords"] == ["Backend", "Platform"]

        for url in (
            f"/applications/{app_id}/submit-readiness",
            f"/applications/{app_id}/submit-confirmation",
        ):
            response = client.post(url, headers=headers)
            assert response.status_code == 410, response.text
            assert "Apply with assistant and Application Prep have been removed" in response.json()["detail"]

        reset_response = client.delete("/submission-settings", headers=headers)
        assert reset_response.status_code == 200, reset_response.text
        assert reset_response.json()["true_submit_enabled"] is False


def test_submit_confirmation_endpoint_stays_retired_for_pilot_users(monkeypatch):
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
        assert settings_response.json()["true_submit_enabled"] is True

        confirmation = client.post(f"/applications/{app_id}/submit-confirmation", headers=headers)
        assert confirmation.status_code == 410, confirmation.text
        assert "Apply with assistant and Application Prep have been removed" in confirmation.json()["detail"]

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
    assert ("0015_user_billing_fields",) in rows
    assert ("0016_matching_profiles",) in rows


def test_agent_run_reports_missing_llm_configuration(monkeypatch):
    monkeypatch.setenv("AGENT_RUNNER_MODE", "background")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(endpoints, "agent_graph", FakeAgentGraph())

    with TestClient(app) as client:
        auth, headers = register_user(client, "agent-missing-llm")
        prepare_agent_setup(client, headers)

        response = client.post("/agent/run", headers=headers)
        assert response.status_code == 503, response.text
        assert "OPENAI_API_KEY" in response.json()["detail"]

        with Session(engine) as session:
            runs = session.exec(select(AgentRun).where(AgentRun.user_id == auth["user"]["id"])).all()
        assert runs == []


def test_matching_profiles_scope_setup_runs_and_pipeline(monkeypatch):
    monkeypatch.setenv("AGENT_RUNNER_MODE", "background")
    monkeypatch.setattr(endpoints, "agent_graph", FakeAgentGraph())

    with TestClient(app) as client:
        _auth, headers = register_user(client, "matching-profiles")
        prepare_agent_setup(client, headers)

        status = client.get("/user/status", headers=headers)
        assert status.status_code == 200, status.text
        default_profile = status.json()["selected_matching_profile"]
        assert default_profile["name"] == "Default profile"
        assert default_profile["resume"]["filename"] == "resume.txt"
        assert default_profile["min_match_score"] == 75

        profile_response = client.post(
            "/matching-profiles",
            json={"name": "Firmware search", "duplicate_from_id": default_profile["id"]},
            headers=headers,
        )
        assert profile_response.status_code == 200, profile_response.text
        profile_id = profile_response.json()["id"]
        assert profile_response.json()["resume"]["filename"] == "resume.txt"

        prefs_response = client.post(
            f"/preferences?matching_profile_id={profile_id}",
            json={
                "role": ["Firmware Engineer", "Embedded Engineer"],
                "experience_level": ["Senior"],
                "location": ["United States"],
                "job_type": ["Full-time"],
                "target_companies": ["Apple", "NVIDIA"],
                "min_match_score": 80,
                "posted_within_days": 14,
            },
            headers=headers,
        )
        assert prefs_response.status_code == 200, prefs_response.text

        upload_response = client.post(
            f"/matching-profiles/{profile_id}/resume",
            files={"file": ("firmware.txt", b"C firmware embedded systems", "text/plain")},
            headers=headers,
        )
        assert upload_response.status_code == 200, upload_response.text
        updated_profile = upload_response.json()
        assert updated_profile["resume"]["filename"] == "firmware.txt"
        assert updated_profile["role"] == ["Firmware Engineer", "Embedded Engineer"]
        assert updated_profile["target_companies"] == ["Apple", "NVIDIA"]

        run_response = client.post(f"/agent/run?matching_profile_id={profile_id}", headers=headers)
        assert run_response.status_code == 200, run_response.text
        run_body = run_response.json()
        assert run_body["matching_profile_id"] == profile_id

        run_detail = client.get(f"/agent/runs/{run_body['agent_run_id']}", headers=headers)
        assert run_detail.status_code == 200, run_detail.text
        run_json = run_detail.json()
        assert run_json["matching_profile_id"] == profile_id
        assert run_json["matching_profile_name"] == "Firmware search"
        assert run_json["resume_id"] == updated_profile["resume"]["id"]

        with Session(engine) as session:
            session.add(
                Application(
                    user_id=_auth["user"]["id"],
                    job_title="Firmware Profile Role",
                    company="Apple",
                    job_url="https://jobs.example.test/apple-firmware",
                    resolved_url="https://jobs.example.test/apple-firmware",
                    source_type="company_site",
                    resolution_status="resolved",
                    status="Analyzed",
                    matching_profile_id=profile_id,
                    agent_run_id=run_body["agent_run_id"],
                    fit_score=0.92,
                )
            )
            session.add(
                Application(
                    user_id=_auth["user"]["id"],
                    job_title="Firmware Almost Role",
                    company="Apple",
                    job_url="https://jobs.example.test/apple-almost",
                    resolved_url="https://jobs.example.test/apple-almost",
                    source_type="company_site",
                    resolution_status="resolved",
                    status="Analyzed",
                    matching_profile_id=profile_id,
                    fit_score=0.79,
                )
            )
            session.add(
                Application(
                    user_id=_auth["user"]["id"],
                    job_title="Default Profile Role",
                    company="Acme",
                    job_url="https://jobs.example.test/acme-backend",
                    resolved_url="https://jobs.example.test/acme-backend",
                    source_type="company_site",
                    resolution_status="resolved",
                    status="Analyzed",
                    matching_profile_id=default_profile["id"],
                    fit_score=0.91,
                )
            )
            session.add(
                Application(
                    user_id=_auth["user"]["id"],
                    job_title="Default Barely Role",
                    company="Acme",
                    job_url="https://jobs.example.test/acme-barely",
                    resolved_url="https://jobs.example.test/acme-barely",
                    source_type="company_site",
                    resolution_status="resolved",
                    status="Analyzed",
                    matching_profile_id=default_profile["id"],
                    fit_score=0.76,
                )
            )
            session.commit()

        scoped_apps = client.get(f"/applications?matching_profile_id={profile_id}&match_bucket=strong", headers=headers)
        assert scoped_apps.status_code == 200, scoped_apps.text
        scoped_body = scoped_apps.json()
        assert [app["job_title"] for app in scoped_body] == ["Firmware Profile Role"]
        assert scoped_body[0]["matching_profile_id"] == profile_id
        assert scoped_body[0]["matching_profile_name"] == "Firmware search"
        assert scoped_body[0]["matching_profile_min_match_score"] == 80

        default_apps = client.get(
            f"/applications?matching_profile_id={default_profile['id']}&match_bucket=strong&sort=role&direction=asc",
            headers=headers,
        )
        assert default_apps.status_code == 200, default_apps.text
        assert [app["job_title"] for app in default_apps.json()] == ["Default Barely Role", "Default Profile Role"]

        all_strong = client.get("/applications?match_bucket=strong&sort=role&direction=asc", headers=headers)
        assert all_strong.status_code == 200, all_strong.text
        assert [app["job_title"] for app in all_strong.json()] == [
            "Default Barely Role",
            "Default Profile Role",
            "Firmware Profile Role",
        ]

        all_below = client.get("/applications?match_bucket=below_threshold&sort=role&direction=asc", headers=headers)
        assert all_below.status_code == 200, all_below.text
        assert [app["job_title"] for app in all_below.json()] == ["Firmware Almost Role"]

        archived = client.delete(f"/matching-profiles/{profile_id}", headers=headers)
        assert archived.status_code == 200, archived.text
        assert archived.json()["is_archived"] is True

        profiles = client.get("/matching-profiles", headers=headers)
        assert profiles.status_code == 200, profiles.text
        assert [profile["id"] for profile in profiles.json()] == [default_profile["id"]]


def test_agent_run_is_persisted_with_logs(monkeypatch):
    monkeypatch.setenv("AGENT_RUNNER_MODE", "background")
    monkeypatch.setattr(endpoints, "agent_graph", FakeAgentGraph())

    with TestClient(app) as client:
        auth, headers = register_user(client, "agent-run")
        with Session(engine) as session:
            user = session.get(User, auth["user"]["id"])
            user.subscription_tier = "pro"
            session.add(user)
            session.commit()

        prepare_agent_setup(client, headers)

        response = client.post("/agent/run", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "queued"
        assert body["agent_run_id"]
        assert body["quota_remaining"] == 49

        run_response = client.get(f"/agent/runs/{body['agent_run_id']}", headers=headers)
        assert run_response.status_code == 200, run_response.text
        run = run_response.json()
        assert run["status"] == "completed"
        assert run["auto_apply"] is False
        assert run["applications_count"] == 1
        assert run["found_jobs_count"] == 1
        assert run["logs"][-1] == "Fake search complete"
        assert run["auto_apply_audit"] == []

        runs_response = client.get("/agent/runs", headers=headers)
        assert runs_response.status_code == 200, runs_response.text
        assert runs_response.json()[0]["id"] == body["agent_run_id"]


def test_agent_run_uses_matching_profile_target_companies_as_search_seeds(monkeypatch):
    class CapturingAgentGraph:
        def __init__(self):
            self.states = []

        async def ainvoke(self, state):
            self.states.append({
                "allowed_companies": list(state.get("allowed_companies") or []),
            })
            return {
                "logs": state.get("logs", []) + ["Captured allowed companies"],
                "applications_submitted": [],
                "found_jobs": [],
                "application_status": "completed",
                "extracted_skills": [],
                "resume_summary": None,
                "auto_apply_audit": [],
            }

    graph = CapturingAgentGraph()
    monkeypatch.setenv("AGENT_RUNNER_MODE", "background")
    monkeypatch.setattr(endpoints, "agent_graph", graph)

    with TestClient(app) as client:
        _, headers = register_user(client, "agent-target-companies")
        prepare_agent_setup(client, headers)

        prefs_response = client.post(
            "/preferences",
            json={
                "role": ["Software Engineer"],
                "experience_level": ["Senior"],
                "location": ["Remote"],
                "job_type": ["Full-time"],
                "target_companies": ["Afero, Tesla", "Acme"],
                "min_match_score": 75,
                "posted_within_days": 7,
            },
            headers=headers,
        )
        assert prefs_response.status_code == 200, prefs_response.text

        response = client.post("/agent/run", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "queued"

        agent_run_id = body["agent_run_id"]
        run_response = client.get(f"/agent/runs/{agent_run_id}", headers=headers)
        assert run_response.status_code == 200, run_response.text
        assert run_response.json()["status"] == "completed"

    assert graph.states == [{"allowed_companies": ["Afero", "Tesla", "Acme"]}]


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
        assert queued_run.json()["logs"] == ["Matching workflow queued for Default profile"]

        assert asyncio.run(endpoints.run_next_queued_agent_run()) is True

        completed_run = client.get(f"/agent/runs/{body['agent_run_id']}", headers=headers)
        assert completed_run.status_code == 200, completed_run.text
        run_body = completed_run.json()
        assert run_body["status"] == "completed"
        assert run_body["applications_count"] == 1
        assert run_body["logs"][-1] == "Fake search complete"


def test_queued_agent_run_can_be_canceled_before_worker_claims_it(monkeypatch):
    monkeypatch.setattr(endpoints, "agent_graph", FakeAgentGraph())
    monkeypatch.setenv("AGENT_RUNNER_MODE", "worker")

    with TestClient(app) as client:
        _, headers = register_user(client, "agent-cancel-queued")
        prepare_agent_setup(client, headers)

        response = client.post("/agent/run", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()

        cancel_response = client.post(f"/agent/runs/{body['agent_run_id']}/cancel", headers=headers)
        assert cancel_response.status_code == 200, cancel_response.text
        canceled = cancel_response.json()
        assert canceled["status"] == "canceled"
        assert canceled["completed_at"] is not None
        assert canceled["logs"][-1] == "Matching workflow stopped by user."

        assert asyncio.run(endpoints.run_next_queued_agent_run()) is False

        run_response = client.get(f"/agent/runs/{body['agent_run_id']}", headers=headers)
        assert run_response.status_code == 200, run_response.text
        assert run_response.json()["status"] == "canceled"


def test_running_agent_run_can_request_stop():
    with TestClient(app) as client:
        auth, headers = register_user(client, "agent-cancel-running")

        with Session(engine) as session:
            run = AgentRun(
                user_id=auth["user"]["id"],
                status="running",
                auto_apply=False,
                logs=["Matching workflow started"],
                claimed_at=utc_now(),
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id

        response = client.post(f"/agent/runs/{run_id}/cancel", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "cancel_requested"
        assert body["logs"][-1] == "Stop requested. Matching will stop after the current step finishes."
        assert body["completed_at"] is None


def test_cancel_requested_agent_run_is_marked_canceled_before_execution(monkeypatch):
    monkeypatch.setattr(endpoints, "agent_graph", FakeAgentGraph())

    with TestClient(app) as client:
        auth, _headers = register_user(client, "agent-cancel-before-start")

        with Session(engine) as session:
            run = AgentRun(
                user_id=auth["user"]["id"],
                status="cancel_requested",
                auto_apply=False,
                logs=["Stop requested. Matching will stop after the current step finishes."],
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id

        asyncio.run(endpoints.execute_agent_run(run_id, auth["user"]["id"], False))

        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run is not None
            assert run.status == "canceled"
            assert run.completed_at is not None
            assert run.logs[-1] == "Matching workflow stopped by user."


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


def test_apply_assistant_routes_are_retired():
    with TestClient(app) as client:
        auth, headers = register_user(client, "assistant-retired")
        user_id = auth["user"]["id"]
        prepare_agent_setup(client, headers)

        with Session(engine) as session:
            saved_app = Application(
                user_id=user_id,
                job_title="Assistant Retired Role",
                company="Acme",
                job_url="https://boards.greenhouse.io/acme/jobs/assistant",
                resolved_url="https://boards.greenhouse.io/acme/jobs/assistant",
                source_type="ats",
                ats_type="greenhouse",
                resolution_status="resolved",
                status="Analyzed",
                fit_score=0.94,
            )
            session.add(saved_app)
            session.commit()
            session.refresh(saved_app)
            app_id = saved_app.id

        session_response = client.post(f"/applications/{app_id}/assistant-session", headers=headers)
        assert session_response.status_code == 410
        assert "Apply with assistant and Application Prep have been removed" in session_response.json()["detail"]

        payload_response = client.get("/assistant/session/not-a-token")
        assert payload_response.status_code == 410
        assert "Apply with assistant and Application Prep have been removed" in payload_response.json()["detail"]

        plan_response = client.post("/assistant/session/not-a-token/plan", json={"fields": [], "controls": []})
        assert plan_response.status_code == 410
        assert "Apply with assistant and Application Prep have been removed" in plan_response.json()["detail"]


def test_agent_run_rejects_retired_auto_apply_flag(monkeypatch):
    monkeypatch.setattr(endpoints, "agent_graph", FakeAgentGraph())

    with TestClient(app) as client:
        _, headers = register_user(client, "auto-apply-retired")
        prepare_agent_setup(client, headers)

        response = client.post("/agent/run?auto_apply=true", headers=headers)
        assert response.status_code == 410
        assert "Apply with assistant and Application Prep have been removed" in response.json()["detail"]
