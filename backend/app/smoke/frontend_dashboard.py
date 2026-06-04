from __future__ import annotations

import os
import json
import re
import time
from typing import Any

import requests
from playwright.sync_api import expect, sync_playwright


def env_url(name: str, default: str) -> str:
    return os.getenv(name, default).rstrip("/")


def api_post(api_url: str, path: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.post(f"{api_url}{path}", json=payload, headers=headers, timeout=15)
    if not response.ok:
        raise RuntimeError(f"{path} returned {response.status_code}: {response.text}")
    return response.json()


def upload_resume(api_url: str, token: str) -> None:
    resume_text = (
        "Simeon Smoke\n"
        "Software engineer focused on Python, React, automation, and data workflows.\n"
        "Built production tools for job matching, dashboards, and workflow orchestration.\n"
    )
    response = requests.post(
        f"{api_url}/upload-resume",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("smoke_resume.txt", resume_text.encode("utf-8"), "text/plain")},
        timeout=15,
    )
    if not response.ok:
        raise RuntimeError(f"/upload-resume returned {response.status_code}: {response.text}")


def seed_user(api_url: str) -> dict[str, Any]:
    stamp = int(time.time() * 1000)
    email = f"frontend-smoke+{stamp}@jobfinder.test"
    password = "Password123!"
    auth = api_post(
        api_url,
        "/auth/register",
        {
            "email": email,
            "password": password,
            "profile": {
                "first_name": "Frontend",
                "last_name": "Smoke",
                "phone": "+1 555 0100",
                "location": "Remote",
                "linkedin_url": "",
            },
        },
    )
    token = auth["access_token"]
    api_post(
        api_url,
        "/preferences",
        {
            "role": ["Software Engineer"],
            "experience_level": ["Senior"],
            "location": ["Remote"],
            "job_type": ["Full-time"],
            "target_companies": ["Stripe", "Figma"],
            "min_match_score": 75,
            "posted_within_days": 7,
        },
        token,
    )
    upload_resume(api_url, token)
    return {"email": email, "auth": auth}


def auth_storage_init_script(auth: dict[str, Any]) -> str:
    session_json = json.dumps(auth)
    return f"""(() => {{
        const session = {session_json};
        localStorage.setItem('auth_token', session.access_token);
        if (session.refresh_token) {{
            localStorage.setItem('auth_refresh_token', session.refresh_token);
        }}
        if (session.expires_in) {{
            localStorage.setItem('auth_token_expires_at', String(Date.now() + session.expires_in * 1000));
        }}
        if (session.refresh_expires_in) {{
            localStorage.setItem('auth_refresh_expires_at', String(Date.now() + session.refresh_expires_in * 1000));
        }}
        localStorage.setItem('user_email', session.user.email);
    }})();"""


def main() -> None:
    api_url = env_url("PREFLIGHT_API_URL", "http://localhost:8000")
    frontend_url = env_url("PREFLIGHT_FRONTEND_BROWSER_URL", "http://frontend:5173")
    seeded = seed_user(api_url)
    auth = seeded["auth"]
    email = seeded["email"]
    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        context.add_init_script(auth_storage_init_script(auth))
        page = context.new_page()
        page.on(
            "console",
            lambda message: console_errors.append(message.text) if message.type == "error" else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        try:
            page.goto(frontend_url, wait_until="domcontentloaded")

            expect(page.get_by_role("heading", name="Smart job search assistant")).to_be_visible(timeout=15_000)
            expect(page.get_by_text(email)).to_be_visible(timeout=15_000)
            expect(page.get_by_text("smoke_resume.txt").first).to_be_visible()
            expect(page.get_by_text("Software Engineer / Remote").first).to_be_visible()
            expect(page.get_by_role("heading", name="Workspace setup")).to_be_visible()
            expect(page.get_by_role("heading", name="Match and package jobs")).to_be_visible()
            expect(page.get_by_role("heading", name="Best-fit jobs")).to_be_visible()
            expect(page.get_by_role("button", name="Start matching")).to_be_visible()

            page.get_by_role("link", name="Applications").click()
            expect(page).to_have_url(re.compile(r".*/applications$"), timeout=10_000)
            expect(page.get_by_role("heading", name="Application pipeline").first).to_be_visible()
            expect(page.get_by_text("No strong matches yet.")).to_be_visible()
        except Exception:
            page.screenshot(path="/tmp/job_finder_frontend_smoke_failure.png", full_page=True)
            raise
        finally:
            context.close()
            browser.close()

    if page_errors:
        raise RuntimeError(f"Frontend page errors during smoke: {page_errors}")
    if console_errors:
        raise RuntimeError(f"Frontend console errors during smoke: {console_errors}")

    print(json.dumps({"email": email, "dashboard": "ok", "applications": "ok"}))


if __name__ == "__main__":
    main()
