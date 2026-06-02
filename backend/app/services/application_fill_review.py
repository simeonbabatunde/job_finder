import base64
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from typing import Optional

from bs4 import BeautifulSoup

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
    screenshot_base64: Optional[str] = None
    trace_base64: Optional[str] = None

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class SubmitControlDetection:
    status: str
    detected: bool = False
    confidence: float = 0.0
    label: Optional[str] = None
    selector: Optional[str] = None
    button_type: Optional[str] = None
    current_url: Optional[str] = None
    evidence: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def model_dump(self) -> dict:
        return asdict(self)


class ApplicationFillReviewService:
    SUPPORTED_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters"}
    SUBMIT_LABEL_PATTERNS = (
        ("submit application", 0.55),
        ("submit your application", 0.55),
        ("send application", 0.5),
        ("send your application", 0.5),
        ("complete application", 0.45),
        ("complete your application", 0.45),
        ("finish application", 0.4),
        ("apply now", 0.3),
        ("submit", 0.38),
        ("apply", 0.18),
    )
    NON_FINAL_LABEL_PATTERNS = (
        "save",
        "draft",
        "next",
        "continue",
        "back",
        "cancel",
        "close",
        "upload",
        "browse",
        "sign in",
        "log in",
    )
    PAGE_BLOCKER_PATTERNS = (
        "captcha",
        "recaptcha",
        "security check",
        "verify you are human",
        "bot check",
        "sign in required",
        "login required",
    )

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
        if ats_type not in cls.SUPPORTED_ATS:
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
                trace_started = False
                try:
                    await context.tracing.start(screenshots=True, snapshots=True, sources=False)
                    trace_started = True
                except Exception:
                    pass

                page = await context.new_page()
                fill_result: Optional[FillReviewResult] = None

                try:
                    await page.goto(application_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except PlaywrightTimeoutError:
                        pass

                    if ats_type == "greenhouse":
                        fill_result = await cls._fill_greenhouse_page(
                            page=page,
                            application_url=application_url,
                            profile=profile,
                            resume_bytes=resume_bytes,
                            resume_filename=resume_filename,
                            answer_profile=answer_profile,
                            cover_letter=cover_letter,
                        )
                    elif ats_type == "lever":
                        fill_result = await cls._fill_lever_page(
                            page=page,
                            application_url=application_url,
                            profile=profile,
                            resume_bytes=resume_bytes,
                            resume_filename=resume_filename,
                            answer_profile=answer_profile,
                            cover_letter=cover_letter,
                        )
                    elif ats_type == "ashby":
                        fill_result = await cls._fill_ashby_page(
                            page=page,
                            application_url=application_url,
                            profile=profile,
                            resume_bytes=resume_bytes,
                            resume_filename=resume_filename,
                            answer_profile=answer_profile,
                            cover_letter=cover_letter,
                        )
                    else:
                        fill_result = await cls._fill_smartrecruiters_page(
                            page=page,
                            application_url=application_url,
                            profile=profile,
                            resume_bytes=resume_bytes,
                            resume_filename=resume_filename,
                            answer_profile=answer_profile,
                            cover_letter=cover_letter,
                        )
                except Exception as exc:
                    fill_result = FillReviewResult(
                        status="failed",
                        ats_type=ats_type,
                        application_url=application_url,
                        blockers=[str(exc)],
                        message="Fill-for-review could not complete.",
                    )
                finally:
                    if fill_result and trace_started:
                        fill_result.trace_base64 = await cls._capture_trace_base64(context)
                    await browser.close()
                return fill_result
        except Exception as exc:
            return FillReviewResult(
                status="failed",
                ats_type=ats_type,
                application_url=application_url,
                blockers=[str(exc)],
                message="Fill-for-review could not complete.",
            )

    @classmethod
    async def detect_final_submit_control(
        cls,
        application_url: str,
        ats_type: str,
        timeout_ms: int = 30000,
    ) -> SubmitControlDetection:
        if ats_type not in cls.SUPPORTED_ATS:
            return SubmitControlDetection(
                status="blocked",
                current_url=application_url,
                blockers=[f"{ats_type} final-submit detection is not implemented yet."],
            )

        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except Exception:
            return SubmitControlDetection(
                status="blocked",
                current_url=application_url,
                blockers=["Playwright is unavailable."],
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

                    if ats_type == "lever":
                        await cls._open_lever_apply_form(page)
                    elif ats_type in ("ashby", "smartrecruiters"):
                        await cls._open_generic_apply_form(page)

                    html = await page.content()
                    return cls.detect_final_submit_control_from_html(
                        html,
                        ats_type=ats_type,
                        current_url=page.url or application_url,
                    )
                finally:
                    await browser.close()
        except Exception as exc:
            return SubmitControlDetection(
                status="blocked",
                current_url=application_url,
                blockers=[str(exc)],
            )

    @classmethod
    def detect_final_submit_control_from_html(
        cls,
        html: str,
        ats_type: str = "",
        current_url: Optional[str] = None,
    ) -> SubmitControlDetection:
        soup = BeautifulSoup(html or "", "html.parser")
        page_text = cls._normalized_text(soup.get_text(" "))
        lowered_html = (html or "").lower()

        page_blockers = [
            pattern
            for pattern in cls.PAGE_BLOCKER_PATTERNS
            if pattern in page_text or pattern in lowered_html
        ]
        if page_blockers:
            return SubmitControlDetection(
                status="blocked",
                current_url=current_url,
                blockers=[f"Page appears blocked by: {', '.join(sorted(set(page_blockers)))}."],
            )

        field_count = cls._application_field_count(soup)
        has_form = any(cls._element_has_application_fields(form) for form in soup.find_all("form"))
        candidates = []
        for index, element in enumerate(soup.find_all(["button", "input", "a"]), start=1):
            candidate = cls._score_submit_control(element, index, field_count, has_form)
            if candidate:
                candidates.append(candidate)

        candidates.sort(key=lambda item: item["confidence"], reverse=True)
        eligible = [candidate for candidate in candidates if candidate["confidence"] >= 0.55]
        if not eligible:
            return SubmitControlDetection(
                status="missing",
                current_url=current_url,
                evidence=[
                    f"Detected {field_count} visible application field{'s' if field_count != 1 else ''}.",
                    "No high-confidence final submit control was found.",
                ],
                blockers=["Final submit control was not detected."],
            )

        top = eligible[0]
        if len(eligible) > 1 and eligible[1]["confidence"] >= max(0.55, top["confidence"] - 0.08):
            labels = [candidate["label"] for candidate in eligible[:3]]
            return SubmitControlDetection(
                status="ambiguous",
                confidence=round(float(top["confidence"]), 2),
                label=top["label"],
                selector=top["selector"],
                button_type=top["button_type"],
                current_url=current_url,
                evidence=[
                    f"Multiple possible final controls were found: {', '.join(labels)}.",
                    f"Detected {field_count} visible application field{'s' if field_count != 1 else ''}.",
                ],
                blockers=["Multiple possible final submit controls require human review."],
            )

        warnings = []
        if top["confidence"] < 0.85:
            warnings.append("Submit control confidence is below the automated-submit threshold.")
        if "apply" in top["label"].lower() and "submit" not in top["label"].lower():
            warnings.append("Submit control uses a generic apply label.")

        return SubmitControlDetection(
            status="detected",
            detected=True,
            confidence=round(float(top["confidence"]), 2),
            label=top["label"],
            selector=top["selector"],
            button_type=top["button_type"],
            current_url=current_url,
            evidence=[
                top["evidence"],
                f"Detected {field_count} visible application field{'s' if field_count != 1 else ''}.",
                f"ATS context: {ats_type or 'unknown'}.",
            ],
            warnings=warnings,
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
        screenshot_base64 = await cls._capture_screenshot_base64(page)
        return FillReviewResult(
            status=status,
            ats_type="greenhouse",
            application_url=application_url,
            fields_filled=fields_filled,
            fields_missing=fields_missing,
            blockers=blockers,
            message="Greenhouse form prepared for human review. Nothing was submitted.",
            screenshot_base64=screenshot_base64,
        )

    @classmethod
    async def _fill_lever_page(
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

        if not await cls._open_lever_apply_form(page):
            blockers.append("Could not find the Lever apply form on this page.")

        full_name = f"{profile.first_name} {profile.last_name}".strip()
        contact_fields = [
            ("Name", ["input[name='name']", "#name", "input[id*='name' i]"], full_name),
            ("Email", ["input[name='email']", "#email", "input[type='email']"], profile.email),
            ("Phone", ["input[name='phone']", "#phone", "input[type='tel']"], profile.phone),
            ("LinkedIn", ["input[name='urls[LinkedIn]']", "input[name*='linkedin' i]"], profile.linkedin_url),
            (
                "Website",
                ["input[name='urls[Portfolio]']", "input[name*='portfolio' i]", "input[name*='website' i]", "input[name*='github' i]"],
                profile.portfolio_url or profile.github_url,
            ),
        ]

        for label, selectors, value in contact_fields:
            if not value:
                fields_missing.append(label)
                continue
            if await cls._fill_first_available(page, selectors, value):
                fields_filled.append(label)
            elif label in ("Name", "Email"):
                fields_missing.append(label)

        if cover_letter:
            if await cls._fill_first_available(
                page,
                ["textarea[name='comments']", "textarea[name*='cover' i]", "textarea"],
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
        screenshot_base64 = await cls._capture_screenshot_base64(page)
        return FillReviewResult(
            status=status,
            ats_type="lever",
            application_url=page.url or application_url,
            fields_filled=fields_filled,
            fields_missing=fields_missing,
            blockers=blockers,
            message="Lever form prepared for human review. Nothing was submitted.",
            screenshot_base64=screenshot_base64,
        )

    @classmethod
    async def _fill_ashby_page(
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

        await cls._open_generic_apply_form(page)

        contact_fields = [
            ("First name", ["input[name='firstName']", "input[name='first_name']", "input[id*='first' i]"], profile.first_name),
            ("Last name", ["input[name='lastName']", "input[name='last_name']", "input[id*='last' i]"], profile.last_name),
            ("Email", ["input[name='email']", "input[type='email']", "input[id*='email' i]"], profile.email),
            ("Phone", ["input[name='phone']", "input[name='phoneNumber']", "input[type='tel']", "input[id*='phone' i]"], profile.phone),
            ("LinkedIn", ["input[name*='linkedin' i]", "input[id*='linkedin' i]"], profile.linkedin_url),
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
            if await cls._fill_first_available(page, ["textarea[name*='cover' i]", "textarea"], cover_letter):
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
        screenshot_base64 = await cls._capture_screenshot_base64(page)
        return FillReviewResult(
            status=status,
            ats_type="ashby",
            application_url=page.url or application_url,
            fields_filled=fields_filled,
            fields_missing=fields_missing,
            blockers=blockers,
            message="Ashby form prepared for human review. Nothing was submitted.",
            screenshot_base64=screenshot_base64,
        )

    @classmethod
    async def _fill_smartrecruiters_page(
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

        await cls._open_generic_apply_form(page)

        contact_fields = [
            ("First name", ["input[name='firstName']", "input[name='first_name']", "input[id*='first' i]"], profile.first_name),
            ("Last name", ["input[name='lastName']", "input[name='last_name']", "input[id*='last' i]"], profile.last_name),
            ("Email", ["input[name='email']", "input[type='email']", "input[id*='email' i]"], profile.email),
            ("Phone", ["input[name='phone']", "input[name='phoneNumber']", "input[type='tel']", "input[id*='phone' i]"], profile.phone),
            ("LinkedIn", ["input[name*='linkedin' i]", "input[id*='linkedin' i]"], profile.linkedin_url),
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
            if await cls._fill_first_available(page, ["textarea[name*='cover' i]", "textarea[name*='message' i]", "textarea"], cover_letter):
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
        screenshot_base64 = await cls._capture_screenshot_base64(page)
        return FillReviewResult(
            status=status,
            ats_type="smartrecruiters",
            application_url=page.url or application_url,
            fields_filled=fields_filled,
            fields_missing=fields_missing,
            blockers=blockers,
            message="SmartRecruiters form prepared for human review. Nothing was submitted.",
            screenshot_base64=screenshot_base64,
        )

    @staticmethod
    async def _open_lever_apply_form(page) -> bool:
        try:
            if "/apply" in page.url:
                return True

            apply_link = page.locator("a[href*='/apply']").first()
            if await apply_link.count() > 0:
                await apply_link.click(timeout=3000)
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                return True

            apply_button = page.get_by_role("button", name="Apply").first()
            if await apply_button.count() > 0:
                await apply_button.click(timeout=3000)
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                return True

            return await page.locator("input[name='name'], input[name='email'], input[type='file']").first().count() > 0
        except Exception:
            return False

    @staticmethod
    async def _open_generic_apply_form(page) -> bool:
        try:
            if await page.locator("input[type='file'], input[type='email']").first().count() > 0:
                return True

            for selector in (
                "a[href*='application']",
                "a[href*='apply']",
                "button:has-text('Apply')",
                "a:has-text('Apply')",
            ):
                locator = page.locator(selector).first()
                if await locator.count() == 0:
                    continue
                await locator.click(timeout=3000)
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                return True
            return False
        except Exception:
            return False

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
    def _normalized_text(value: str) -> str:
        return " ".join((value or "").lower().split())

    @classmethod
    def _application_field_count(cls, soup: BeautifulSoup) -> int:
        count = 0
        for element in soup.find_all(["input", "textarea", "select"]):
            if cls._is_hidden_or_disabled(element):
                continue
            element_type = (element.get("type") or "").lower()
            if element_type in ("submit", "button", "reset"):
                continue
            count += 1
        return count

    @classmethod
    def _element_has_application_fields(cls, element) -> bool:
        return any(
            not cls._is_hidden_or_disabled(control)
            and (control.name != "input" or (control.get("type") or "").lower() not in ("submit", "button", "reset"))
            for control in element.find_all(["input", "textarea", "select"])
        )

    @staticmethod
    def _is_hidden_or_disabled(element) -> bool:
        element_type = (element.get("type") or "").lower()
        style = (element.get("style") or "").lower().replace(" ", "")
        return (
            element_type == "hidden"
            or element.has_attr("hidden")
            or element.has_attr("disabled")
            or element.get("aria-hidden") == "true"
            or element.get("aria-disabled") == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )

    @classmethod
    def _score_submit_control(cls, element, index: int, field_count: int, has_form: bool) -> Optional[dict]:
        if cls._is_hidden_or_disabled(element):
            return None

        tag = element.name.lower()
        element_type = (element.get("type") or "").lower()
        if tag == "input" and element_type not in ("submit", "button"):
            return None
        if tag == "a" and element.get("role") != "button":
            label_hint = cls._normalized_text(cls._control_label(element))
            if not any(pattern in label_hint for pattern, _ in cls.SUBMIT_LABEL_PATTERNS):
                return None

        label = cls._control_label(element)
        display_label = cls._control_display_label(element) or label
        normalized_label = cls._normalized_text(label)
        if not normalized_label:
            return None

        if any(pattern in normalized_label for pattern in cls.NON_FINAL_LABEL_PATTERNS):
            has_positive_submit_word = any(
                pattern in normalized_label
                for pattern in ("submit", "send application", "complete application", "finish application")
            )
            if not has_positive_submit_word:
                return None

        score = 0.0
        evidence = []
        if tag == "button":
            score += 0.18
            evidence.append("candidate is a button")
        if tag == "input" and element_type == "submit":
            score += 0.26
            evidence.append("candidate is an input[type=submit]")
        if tag == "a":
            score += 0.08
            evidence.append("candidate is a link-style button")
        if element.find_parent("form"):
            score += 0.18
            evidence.append("candidate is inside a form")
        if has_form:
            score += 0.08
        if field_count >= 3:
            score += 0.12
            evidence.append("page contains application fields")
        elif field_count > 0:
            score += 0.06

        for pattern, weight in cls.SUBMIT_LABEL_PATTERNS:
            if pattern in normalized_label:
                score += weight
                evidence.append(f"label matched '{pattern}'")
                break

        if "preview" in normalized_label or "review" in normalized_label:
            score -= 0.18
        if normalized_label == "apply" and field_count < 3:
            score -= 0.18
        if element_type == "button" and "submit" not in normalized_label:
            score -= 0.08

        confidence = max(0.0, min(score, 0.99))
        if confidence < 0.45:
            return None

        return {
            "confidence": confidence,
            "label": display_label.strip()[:120],
            "selector": cls._selector_for_element(element, index),
            "button_type": element_type or tag,
            "evidence": "; ".join(evidence) or "candidate matched submit-control heuristics",
        }

    @staticmethod
    def _control_display_label(element) -> str:
        values = [
            element.get_text(" ", strip=True),
            element.get("value"),
            element.get("aria-label"),
            element.get("title"),
        ]
        return " ".join(value for value in values if value)

    @staticmethod
    def _control_label(element) -> str:
        values = [
            element.get_text(" ", strip=True),
            element.get("value"),
            element.get("aria-label"),
            element.get("title"),
            element.get("name"),
            element.get("id"),
            " ".join(element.get("class") or []),
        ]
        return " ".join(value for value in values if value)

    @staticmethod
    def _selector_for_element(element, index: int) -> str:
        tag = element.name.lower()
        element_id = element.get("id")
        if element_id:
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", element_id):
                return f"#{element_id}"
            return f'{tag}[id="{ApplicationFillReviewService._css_quote(element_id)}"]'

        for attr in ("data-testid", "data-test", "name", "aria-label"):
            value = element.get(attr)
            if value:
                return f'{tag}[{attr}="{ApplicationFillReviewService._css_quote(value)}"]'

        return f"{tag}:nth-of-type({index})"

    @staticmethod
    def _css_quote(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

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

    @staticmethod
    async def _capture_screenshot_base64(page) -> Optional[str]:
        try:
            screenshot = await page.screenshot(full_page=True, type="png", timeout=5000)
            return base64.b64encode(screenshot).decode("ascii")
        except Exception:
            return None

    @staticmethod
    async def _capture_trace_base64(context) -> Optional[str]:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            trace_path = tmp.name

        try:
            await context.tracing.stop(path=trace_path)
            with open(trace_path, "rb") as trace_file:
                return base64.b64encode(trace_file.read()).decode("ascii")
        except Exception:
            try:
                await context.tracing.stop()
            except Exception:
                pass
            return None
        finally:
            if os.path.exists(trace_path):
                os.unlink(trace_path)
