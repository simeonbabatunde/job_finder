from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse


@dataclass(frozen=True)
class LinkResolutionResult:
    original_url: str
    resolved_url: Optional[str]
    source_type: str
    ats_type: Optional[str]
    resolution_status: str
    notes: str

    def model_dump(self) -> dict:
        return asdict(self)


class ApplicationLinkResolver:
    ATS_DOMAINS = {
        "greenhouse": ("greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io"),
        "lever": ("lever.co", "jobs.lever.co"),
        "ashby": ("ashbyhq.com", "jobs.ashbyhq.com"),
        "smartrecruiters": ("smartrecruiters.com", "jobs.smartrecruiters.com"),
        "workday": ("myworkdayjobs.com", "workdayjobs.com"),
        "bamboohr": ("bamboohr.com",),
        "icims": ("icims.com",),
        "recruitee": ("recruitee.com",),
        "taleo": ("taleo.net",),
    }

    AGGREGATOR_DOMAINS = {
        "linkedin": ("linkedin.com", "www.linkedin.com"),
        "indeed": ("indeed.com", "www.indeed.com"),
        "google_jobs": ("google.com", "www.google.com"),
        "ziprecruiter": ("ziprecruiter.com", "www.ziprecruiter.com"),
        "glassdoor": ("glassdoor.com", "www.glassdoor.com"),
    }

    @classmethod
    def classify_url(cls, url: str) -> LinkResolutionResult:
        normalized_url = (url or "").strip()
        if not normalized_url:
            return LinkResolutionResult(
                original_url=url,
                resolved_url=None,
                source_type="unknown",
                ats_type=None,
                resolution_status="manual_review",
                notes="No URL provided.",
            )

        parsed = urlparse(normalized_url)
        hostname = (parsed.hostname or "").lower()
        if hostname.startswith("www."):
            hostname_without_www = hostname[4:]
        else:
            hostname_without_www = hostname

        ats_type = cls.detect_ats(hostname_without_www)
        if ats_type:
            return LinkResolutionResult(
                original_url=normalized_url,
                resolved_url=normalized_url,
                source_type="ats",
                ats_type=ats_type,
                resolution_status="resolved",
                notes=f"URL is already a supported ATS destination: {ats_type}.",
            )

        source_type = cls.detect_aggregator(hostname_without_www)
        if source_type:
            return LinkResolutionResult(
                original_url=normalized_url,
                resolved_url=None,
                source_type=source_type,
                ats_type=None,
                resolution_status="needs_resolution",
                notes="Aggregator job link must be opened and resolved to the employer application URL before form filling.",
            )

        if hostname_without_www:
            return LinkResolutionResult(
                original_url=normalized_url,
                resolved_url=normalized_url,
                source_type="company_site",
                ats_type=None,
                resolution_status="resolved",
                notes="URL appears to be a direct company or job page. ATS support still needs to be detected before auto-submit.",
            )

        return LinkResolutionResult(
            original_url=normalized_url,
            resolved_url=None,
            source_type="unknown",
            ats_type=None,
            resolution_status="manual_review",
            notes="URL could not be classified.",
        )

    @classmethod
    async def resolve_url(cls, url: str, timeout_ms: int = 30000) -> LinkResolutionResult:
        classification = cls.classify_url(url)
        if classification.resolution_status != "needs_resolution":
            return classification

        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except Exception:
            return LinkResolutionResult(
                original_url=classification.original_url,
                resolved_url=None,
                source_type=classification.source_type,
                ats_type=None,
                resolution_status="manual_review",
                notes="Playwright is unavailable, so this aggregator link needs manual review.",
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
                    await page.goto(classification.original_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except PlaywrightTimeoutError:
                        pass

                    blocker_status = await cls._detect_page_blocker(page)
                    if blocker_status:
                        return LinkResolutionResult(
                            original_url=classification.original_url,
                            resolved_url=None,
                            source_type=classification.source_type,
                            ats_type=None,
                            resolution_status=blocker_status,
                            notes=f"{classification.source_type.title()} blocked automatic resolution with {blocker_status.replace('_', ' ')}.",
                        )

                    resolved_url = await cls._find_external_apply_url(page, classification.source_type)
                    if resolved_url:
                        resolved = cls.classify_url(resolved_url)
                        return LinkResolutionResult(
                            original_url=classification.original_url,
                            resolved_url=resolved_url,
                            source_type=classification.source_type,
                            ats_type=resolved.ats_type,
                            resolution_status="resolved",
                            notes=(
                                "Resolved aggregator job link to the employer application destination. "
                                f"Destination type: {resolved.ats_type or resolved.source_type}."
                            ),
                        )

                    return LinkResolutionResult(
                        original_url=classification.original_url,
                        resolved_url=None,
                        source_type=classification.source_type,
                        ats_type=None,
                        resolution_status="manual_review",
                        notes="No clear external employer application link was found on the aggregator page.",
                    )
                finally:
                    await browser.close()
        except PlaywrightTimeoutError:
            return LinkResolutionResult(
                original_url=classification.original_url,
                resolved_url=None,
                source_type=classification.source_type,
                ats_type=None,
                resolution_status="manual_review",
                notes="Timed out while trying to resolve the aggregator job link.",
            )
        except Exception as exc:
            return LinkResolutionResult(
                original_url=classification.original_url,
                resolved_url=None,
                source_type=classification.source_type,
                ats_type=None,
                resolution_status="manual_review",
                notes=f"Could not resolve the aggregator job link automatically: {exc}",
            )

    @classmethod
    def detect_ats(cls, hostname: str) -> Optional[str]:
        return cls._detect_from_domains(hostname, cls.ATS_DOMAINS)

    @classmethod
    def detect_aggregator(cls, hostname: str) -> Optional[str]:
        return cls._detect_from_domains(hostname, cls.AGGREGATOR_DOMAINS)

    @staticmethod
    def _detect_from_domains(hostname: str, domains_by_type: dict[str, tuple[str, ...]]) -> Optional[str]:
        for source_type, domains in domains_by_type.items():
            if any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
                return source_type
        return None

    @classmethod
    async def _detect_page_blocker(cls, page) -> Optional[str]:
        text = (await page.locator("body").inner_text(timeout=3000)).lower()
        if any(marker in text for marker in ("captcha", "verify you are human", "security check")):
            return "captcha"
        if any(
            marker in text
            for marker in (
                "sign in to view",
                "sign in to continue",
                "log in to view",
                "login to view",
                "join linkedin",
            )
        ):
            return "login_required"
        return None

    @classmethod
    async def _find_external_apply_url(cls, page, source_type: str) -> Optional[str]:
        candidates = await page.evaluate(
            """() => {
                const applyTerms = [
                    "apply",
                    "apply now",
                    "apply on company",
                    "company website",
                    "continue to application",
                    "external apply",
                    "start application"
                ];
                const elements = Array.from(document.querySelectorAll('a[href], button, [role="button"]'));
                return elements.map((element) => {
                    const href = element.href
                        || element.getAttribute('href')
                        || element.getAttribute('data-url')
                        || element.getAttribute('data-href')
                        || element.getAttribute('formaction')
                        || "";
                    const text = [
                        element.innerText,
                        element.getAttribute('aria-label'),
                        element.getAttribute('title'),
                        href
                    ].filter(Boolean).join(" ").toLowerCase();
                    return { href, text };
                }).filter((candidate) => (
                    candidate.href && applyTerms.some((term) => candidate.text.includes(term))
                )).slice(0, 30);
            }"""
        )

        for candidate in candidates:
            href = candidate.get("href", "")
            resolved = cls._normalize_external_candidate(href, page.url, source_type)
            if resolved:
                return resolved
        return None

    @classmethod
    def _normalize_external_candidate(cls, href: str, base_url: str, source_type: str) -> Optional[str]:
        candidate_url = urljoin(base_url, href)
        extracted_url = cls._extract_redirect_target(candidate_url, source_type)
        if extracted_url:
            candidate_url = extracted_url

        parsed = urlparse(candidate_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None

        hostname = parsed.hostname.lower()
        hostname_without_www = hostname[4:] if hostname.startswith("www.") else hostname
        if cls.detect_aggregator(hostname_without_www) == source_type:
            return None

        return candidate_url

    @classmethod
    def _extract_redirect_target(cls, url: str, source_type: str) -> Optional[str]:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        for key in ("url", "u", "target", "redirect", "redirect_url", "continue", "to"):
            for raw_value in query.get(key, []):
                value = unquote(raw_value)
                target = urlparse(value)
                if target.scheme in ("http", "https") and target.hostname:
                    hostname = target.hostname.lower()
                    hostname_without_www = hostname[4:] if hostname.startswith("www.") else hostname
                    if cls.detect_aggregator(hostname_without_www) != source_type:
                        return value
        return None
