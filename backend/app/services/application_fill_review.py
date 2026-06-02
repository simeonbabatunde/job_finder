import os
import tempfile
from dataclasses import asdict, dataclass, field
from typing import Optional

from app.models import ApplicationAnswerProfile, Profile


@dataclass
class FillReviewResult:
    status: str
    ats_type: str
    application_url: str
    fields_filled: list[str] = field(default_factory=list)
    fields_missing: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    message: str = ""
    application_status: str = "Needs Review"

    def model_dump(self) -> dict:
        return asdict(self)


class ApplicationFillReviewService:
    @classmethod
    async def fill_application_for_review(
        cls,
        application_url: str,
        ats_type: str,
        profile: Profile,
        resume_bytes: bytes,
        resume_filename: str,
        answer_profile: Optional[ApplicationAnswerProfile] = None,
        cover_letter: Optional[str] = None,
        timeout_ms: int = 60000,
    ) -> FillReviewResult:
        if ats_type != "greenhouse":
            return FillReviewResult(
                status="unsupported",
                ats_type=ats_type,
                application_url=application_url,
                blockers=[f"{ats_type} fill-for-review is not implemented yet."],
                message="This ATS is not supported for fill-for-review yet.",
            )

        if not profile:
            return FillReviewResult(
                status="blocked",
                ats_type=ats_type,
                application_url=application_url,
                blockers=["Candidate profile is required."],
                message="Add candidate profile details before fill-for-review.",
            )

        if not resume_bytes:
            return FillReviewResult(
                status="blocked",
                ats_type=ats_type,
                application_url=application_url,
                blockers=["Resume file is required."],
                message="Upload a resume before fill-for-review.",
            )

        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except Exception:
            return FillReviewResult(
                status="blocked",
                ats_type=ats_type,
                application_url=application_url,
                blockers=["Playwright is unavailable."],
                message="Browser automation is unavailable in this environment.",
            )

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/119.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()

                try:
                    await page.goto(application_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except PlaywrightTimeoutError:
                        pass

                    return await cls._fill_greenhouse_page(
                        page=page,
                        application_url=application_url,
                        profile=profile,
                        resume_bytes=resume_bytes,
                        resume_filename=resume_filename,
                        answer_profile=answer_profile,
                        cover_letter=cover_letter,
                    )
                finally:
                    await browser.close()
        except Exception as exc:
            return FillReviewResult(
                status="failed",
                ats_type=ats_type,
                application_url=application_url,
                blockers=[str(exc)],
                message="Fill-for-review could not complete.",
            )

    @classmethod
    async def _fill_greenhouse_page(
        cls,
        page,
        application_url: str,
        profile: Profile,
        resume_bytes: bytes,
        resume_filename: str,
        answer_profile: Optional[ApplicationAnswerProfile],
        cover_letter: Optional[str],
    ) -> FillReviewResult:
        fields_filled: list[str] = []
        fields_missing: list[str] = []
        blockers: list[str] = []

        contact_fields = [
            ("First name", ["#first_name", "input[name='job_application[first_name]']", "input[name='first_name']"], profile.first_name),
            ("Last name", ["#last_name", "input[name='job_application[last_name]']", "input[name='last_name']"], profile.last_name),
            ("Email", ["#email", "input[name='job_application[email]']", "input[type='email']"], profile.email),
            ("Phone", ["#phone", "input[name='job_application[phone]']", "input[type='tel']"], profile.phone),
            ("LinkedIn", ["#job_application_answers_attributes_0_text_value", "input[name*='linkedin' i]"], profile.linkedin_url),
            ("Website", ["input[name*='portfolio' i]", "input[name*='website' i]", "input[name*='github' i]"], profile.portfolio_url or profile.github_url),
        ]

        for label, selectors, value in contact_fields:
            if not value:
                fields_missing.append(label)
                continue
            if await cls._fill_first_available(page, selectors, value):
                fields_filled.append(label)
            elif label in ("First name", "Last name", "Email"):
                fields_missing.append(label)

        if cover_letter:
            if await cls._fill_first_available(
                page,
                ["#cover_letter", "textarea[name*='cover_letter' i]", "textarea[name*='cover' i]"],
                cover_letter,
            ):
                fields_filled.append("Cover letter")

        if await cls._upload_resume(page, resume_bytes, resume_filename):
            fields_filled.append("Resume")
        else:
            fields_missing.append("Resume upload")

        if answer_profile:
            await cls._fill_answer_profile_fields(page, answer_profile, fields_filled, fields_missing)
        else:
            blockers.append("Application answer consent is off or no answer profile is saved; work authorization answers were not filled.")

        required_missing = await cls._detect_required_missing_fields(page)
        for item in required_missing:
            if item not in fields_missing:
                fields_missing.append(item)

        status = "ready_for_review" if not blockers else "needs_review"
        return FillReviewResult(
            status=status,
            ats_type="greenhouse",
            application_url=application_url,
            fields_filled=fields_filled,
            fields_missing=fields_missing,
            blockers=blockers,
            message="Greenhouse form prepared for human review. Nothing was submitted.",
        )

    @staticmethod
    async def _fill_first_available(page, selectors: list[str], value: str) -> bool:
        for selector in selectors:
            try:
                locator = page.locator(selector).first()
                if await locator.count() == 0:
                    continue
                await locator.fill(value, timeout=1500)
                return True
            except Exception:
                continue
        return False

    @staticmethod
    async def _upload_resume(page, resume_bytes: bytes, resume_filename: str) -> bool:
        suffix = os.path.splitext(resume_filename or "resume.pdf")[1] or ".pdf"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(resume_bytes)
            tmp_path = tmp.name

        try:
            for selector in (
                "input[type='file'][name*='resume' i]",
                "input[type='file'][id*='resume' i]",
                "input[type='file']",
            ):
                try:
                    locator = page.locator(selector).first()
                    if await locator.count() == 0:
                        continue
                    await locator.set_input_files(tmp_path, timeout=2000)
                    return True
                except Exception:
                    continue
            return False
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @classmethod
    async def _fill_answer_profile_fields(
        cls,
        page,
        answer_profile: ApplicationAnswerProfile,
        fields_filled: list[str],
        fields_missing: list[str],
    ) -> None:
        text_answers = [
            ("Desired compensation", ["salary", "compensation"], answer_profile.desired_salary),
            ("Notice period", ["notice"], answer_profile.notice_period),
            ("Earliest start date", ["start", "available"], answer_profile.earliest_start_date),
        ]
        for label, keywords, value in text_answers:
            if value and await cls._fill_by_label_keywords(page, keywords, value):
                fields_filled.append(label)

        yes_no_answers = [
            ("Work authorization", ["authorized", "work"], answer_profile.work_authorized_us),
            ("Sponsorship now", ["sponsor"], answer_profile.requires_sponsorship_now),
            ("Sponsorship future", ["sponsor", "future"], answer_profile.requires_sponsorship_future),
            ("Relocation", ["relocat"], answer_profile.willing_to_relocate),
        ]
        for label, keywords, value in yes_no_answers:
            if value not in ("yes", "no", "prefer_not_to_answer"):
                fields_missing.append(label)
                continue
            if await cls._choose_option_by_group_text(page, keywords, value):
                fields_filled.append(label)
            else:
                fields_missing.append(label)

    @staticmethod
    async def _fill_by_label_keywords(page, keywords: list[str], value: str) -> bool:
        return await page.evaluate(
            """({ keywords, value }) => {
                const controls = Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="file"]), textarea'));
                for (const control of controls) {
                    const id = control.id;
                    const label = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null;
                    const wrapperText = [
                        label?.innerText,
                        control.getAttribute('aria-label'),
                        control.getAttribute('placeholder'),
                        control.closest('div, fieldset, li')?.innerText
                    ].filter(Boolean).join(' ').toLowerCase();
                    if (keywords.every((keyword) => wrapperText.includes(keyword))) {
                        control.value = value;
                        control.dispatchEvent(new Event('input', { bubbles: true }));
                        control.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                }
                return false;
            }""",
            {"keywords": keywords, "value": value},
        )

    @staticmethod
    async def _choose_option_by_group_text(page, keywords: list[str], value: str) -> bool:
        target_words = {
            "yes": ["yes"],
            "no": ["no"],
            "prefer_not_to_answer": ["prefer not", "decline", "do not wish"],
        }[value]
        return await page.evaluate(
            """({ keywords, targetWords }) => {
                const groups = Array.from(document.querySelectorAll('fieldset, .field, .application-question, .custom-question, li'));
                for (const group of groups) {
                    const groupText = (group.innerText || '').toLowerCase();
                    if (!keywords.every((keyword) => groupText.includes(keyword))) continue;
                    const labels = Array.from(group.querySelectorAll('label'));
                    for (const label of labels) {
                        const labelText = (label.innerText || '').trim().toLowerCase();
                        if (!targetWords.some((word) => labelText.includes(word))) continue;
                        const input = label.htmlFor
                            ? document.getElementById(label.htmlFor)
                            : label.querySelector('input, option');
                        if (input && input.tagName === 'INPUT') {
                            input.click();
                            input.dispatchEvent(new Event('change', { bubbles: true }));
                            return true;
                        }
                    }
                }
                return false;
            }""",
            {"keywords": keywords, "targetWords": target_words},
        )

    @staticmethod
    async def _detect_required_missing_fields(page) -> list[str]:
        return await page.evaluate(
            """() => {
                const controls = Array.from(document.querySelectorAll('input, textarea, select'));
                return controls
                    .filter((control) => {
                        const type = (control.getAttribute('type') || '').toLowerCase();
                        if (['hidden', 'submit', 'button'].includes(type)) return false;
                        const required = control.required || control.getAttribute('aria-required') === 'true';
                        if (!required) return false;
                        if (type === 'file') return !control.files || control.files.length === 0;
                        return !String(control.value || '').trim();
                    })
                    .map((control) => {
                        const id = control.id;
                        const label = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null;
                        return (label?.innerText || control.getAttribute('aria-label') || control.name || 'Required field').trim();
                    })
                    .filter(Boolean)
                    .slice(0, 20);
            }"""
        )
