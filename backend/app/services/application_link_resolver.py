from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import asyncio
import html as html_lib
import os
import re
from typing import Any, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests


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


@dataclass(frozen=True)
class PublicAtsMatch:
    ats_type: str
    apply_url: str
    title: str
    score: float


@dataclass(frozen=True)
class CareerSearchCandidate:
    title: str
    url: str
    snippet: str = ""


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
        "teal": ("tealhq.com", "www.tealhq.com"),
        "builtin": ("builtin.com", "www.builtin.com"),
        "themuse": ("themuse.com", "www.themuse.com"),
        "wellfound": ("wellfound.com", "www.wellfound.com", "angel.co", "www.angel.co"),
        "dice": ("dice.com", "www.dice.com"),
        "monster": ("monster.com", "www.monster.com"),
        "careerbuilder": ("careerbuilder.com", "www.careerbuilder.com"),
        "campusbuilding": ("campusbuilding.com", "www.campusbuilding.com"),
    }

    CONTEXT_RESOLUTION_SOURCE_TYPES = set(AGGREGATOR_DOMAINS.keys()) | {"company_site"}
    PUBLIC_ATS_TYPES = ("lever", "greenhouse", "ashby", "smartrecruiters")
    SEARCH_RESULT_BLOCKED_HOSTS = {
        "linkedin.com",
        "indeed.com",
        "glassdoor.com",
        "ziprecruiter.com",
        "google.com",
        "bing.com",
        "duckduckgo.com",
        "facebook.com",
        "x.com",
        "twitter.com",
        "instagram.com",
        "tealhq.com",
        "builtin.com",
        "themuse.com",
        "wellfound.com",
        "angel.co",
        "dice.com",
        "monster.com",
        "careerbuilder.com",
        "campusbuilding.com",
    }
    CAREER_PATH_MARKERS = (
        "career",
        "careers",
        "jobs",
        "job",
        "apply",
        "opening",
        "position",
        "requisition",
    )

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
    async def resolve_url(
        cls,
        url: str,
        timeout_ms: int = 30000,
        company: Optional[str] = None,
        job_title: Optional[str] = None,
        allow_browser: bool = True,
    ) -> LinkResolutionResult:
        classification = cls.classify_url(url)
        if classification.resolution_status != "needs_resolution":
            if classification.source_type == "company_site" and not classification.ats_type:
                context_resolution = await cls._resolve_supported_ats_from_context(
                    original_url=classification.original_url,
                    source_type=classification.source_type,
                    company=company,
                    job_title=job_title,
                )
                if context_resolution:
                    return context_resolution
            return classification

        context_resolution = await cls._resolve_supported_ats_from_context(
            original_url=classification.original_url,
            source_type=classification.source_type,
            company=company,
            job_title=job_title,
        )
        if context_resolution:
            return context_resolution

        if not allow_browser:
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
                    if not resolved_url and classification.source_type == "linkedin":
                        resolved_url = await cls._click_linkedin_external_apply_button(page, classification.source_type)

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
    def resolve_url_from_context(
        cls,
        url: str,
        company: Optional[str] = None,
        job_title: Optional[str] = None,
    ) -> LinkResolutionResult:
        classification = cls.classify_url(url)
        if classification.resolution_status != "needs_resolution":
            if classification.source_type == "company_site" and not classification.ats_type:
                context_resolution = cls._resolve_supported_ats_from_context_sync(
                    original_url=classification.original_url,
                    source_type=classification.source_type,
                    company=company,
                    job_title=job_title,
                )
                if context_resolution:
                    return context_resolution
            return classification

        context_resolution = cls._resolve_supported_ats_from_context_sync(
            original_url=classification.original_url,
            source_type=classification.source_type,
            company=company,
            job_title=job_title,
        )
        return context_resolution or classification

    @classmethod
    async def _resolve_supported_ats_from_context(
        cls,
        original_url: str,
        source_type: str,
        company: Optional[str],
        job_title: Optional[str],
    ) -> Optional[LinkResolutionResult]:
        return await asyncio.to_thread(
            cls._resolve_supported_ats_from_context_sync,
            original_url,
            source_type,
            company,
            job_title,
        )

    @classmethod
    def _resolve_supported_ats_from_context_sync(
        cls,
        original_url: str,
        source_type: str,
        company: Optional[str],
        job_title: Optional[str],
    ) -> Optional[LinkResolutionResult]:
        if source_type not in cls.CONTEXT_RESOLUTION_SOURCE_TYPES or not company or not job_title:
            return None

        match = cls._resolve_public_ats_from_context(company, job_title)
        if not match:
            career_url = cls._resolve_company_career_from_search(company, job_title)
            if career_url:
                return LinkResolutionResult(
                    original_url=original_url,
                    resolved_url=career_url,
                    source_type=source_type,
                    ats_type=cls.classify_url(career_url).ats_type,
                    resolution_status="resolved",
                    notes=(
                        f"Resolved {cls._source_type_label(source_type)} job to a validated employer career page "
                        "using exact company and role search metadata."
                    ),
                )

            onsite_result = cls._classify_linkedin_guest_apply_mode(original_url, source_type)
            if onsite_result:
                return onsite_result

            return None

        resolved_url = cls._decorate_resolved_ats_url(match.apply_url, match.ats_type, source_type)
        source_label = cls._source_type_label(source_type)
        ats_label = cls._source_type_label(match.ats_type)

        return LinkResolutionResult(
            original_url=original_url,
            resolved_url=resolved_url,
            source_type=source_type,
            ats_type=match.ats_type,
            resolution_status="resolved",
            notes=(
                f"Resolved {source_label} job to a matching {ats_label} application "
                "using the saved company and role title."
            ),
        )

    @classmethod
    def _resolve_company_career_from_search(cls, company: str, job_title: str) -> Optional[str]:
        for candidate in cls._search_career_candidates(company, job_title):
            resolved = cls._validate_career_search_candidate(candidate, company, job_title)
            if resolved:
                return resolved
        return None

    @classmethod
    def _search_career_candidates(cls, company: str, job_title: str) -> list[CareerSearchCandidate]:
        queries = [
            f'"{job_title}" "{company}" careers',
            f'"{job_title}" "{company}" apply',
        ]
        candidates: list[CareerSearchCandidate] = []
        seen_urls: set[str] = set()
        for query in queries:
            for candidate in cls._duckduckgo_search(query):
                if candidate.url not in seen_urls:
                    candidates.append(candidate)
                    seen_urls.add(candidate.url)
                if len(candidates) >= cls._career_search_candidate_limit():
                    return candidates
        return candidates

    @classmethod
    def _duckduckgo_search(cls, query: str) -> list[CareerSearchCandidate]:
        try:
            response = requests.get(
                f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
                timeout=cls._career_search_http_timeout_seconds(),
                headers={"User-Agent": "Mozilla/5.0"},
            )
        except requests.RequestException:
            return []
        if response.status_code != 200 or "anomaly-modal" in response.text or "bots use DuckDuckGo" in response.text:
            return []

        candidates = []
        for match in re.finditer(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            response.text,
            re.S,
        ):
            raw_url = html_lib.unescape(match.group(1))
            title = cls._clean_html(match.group(2))
            url = cls._extract_search_redirect_target(raw_url)
            if url:
                candidates.append(CareerSearchCandidate(title=title, url=url))
        return candidates

    @classmethod
    def _career_search_candidate_limit(cls) -> int:
        raw_value = os.getenv("CAREER_SEARCH_CANDIDATE_LIMIT", "4").strip()
        try:
            value = int(raw_value)
        except ValueError:
            return 4
        return min(max(value, 1), 12)

    @classmethod
    def _career_search_http_timeout_seconds(cls) -> float:
        raw_value = os.getenv("CAREER_SEARCH_HTTP_TIMEOUT_SECONDS", "4").strip()
        try:
            value = float(raw_value)
        except ValueError:
            return 4.0
        return min(max(value, 1.0), 10.0)

    @classmethod
    def _validate_career_search_candidate(
        cls,
        candidate: CareerSearchCandidate,
        company: str,
        job_title: str,
    ) -> Optional[str]:
        parsed = urlparse(candidate.url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None

        hostname = parsed.hostname.lower().removeprefix("www.")
        if cls._is_blocked_search_host(hostname):
            return None

        title_score = cls._title_match_score(job_title, candidate.title)
        if title_score < 0.9:
            return None

        ats_type = cls.detect_ats(hostname)
        company_signal = cls._company_domain_or_title_match(company, hostname, candidate.title)
        career_path_signal = any(marker in parsed.path.lower() for marker in cls.CAREER_PATH_MARKERS)
        if not ats_type and not company_signal:
            return None
        if not ats_type and not career_path_signal:
            return None

        page_validation = cls._validate_candidate_page(candidate.url, company, job_title)
        if page_validation == "match":
            return candidate.url
        if page_validation == "blocked" and company_signal and title_score >= 0.94:
            return candidate.url
        if page_validation == "unavailable" and company_signal and title_score >= 0.94:
            return candidate.url
        return None

    @classmethod
    def _validate_candidate_page(cls, url: str, company: str, job_title: str) -> str:
        try:
            response = requests.get(
                url,
                timeout=cls._career_search_http_timeout_seconds(),
                headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=True,
            )
        except requests.RequestException:
            return "unavailable"

        if response.status_code in (401, 403, 429):
            return "blocked"
        if not response.ok or not response.text:
            return "unavailable"

        text = cls._normalise_for_match(cls._clean_html(response.text[:250000]))
        title_score = cls._title_match_score(job_title, text[:5000])
        company_terms = cls._company_terms(company)
        company_match = any(term in text for term in company_terms)
        if title_score >= 0.9 and company_match:
            return "match"
        return "mismatch"

    @classmethod
    def _classify_linkedin_guest_apply_mode(cls, original_url: str, source_type: str) -> Optional[LinkResolutionResult]:
        if source_type != "linkedin":
            return None
        job_id_match = re.search(r"/(\d+)(?:[/?#]|$)", original_url)
        if not job_id_match:
            return None
        try:
            response = requests.get(
                f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id_match.group(1)}",
                timeout=8,
                headers={"User-Agent": "Mozilla/5.0"},
            )
        except requests.RequestException:
            return None
        if not response.ok:
            return None
        page = response.text
        if "public_jobs_apply-link-onsite" in page and "apply-button__offsite-apply-icon" not in page:
            return LinkResolutionResult(
                original_url=original_url,
                resolved_url=original_url,
                source_type=source_type,
                ats_type=None,
                resolution_status="unsupported",
                notes="LinkedIn exposes this as an onsite application and no employer application URL is available publicly.",
            )
        return None

    @classmethod
    def _resolve_public_ats_from_context(cls, company: str, job_title: str) -> Optional[PublicAtsMatch]:
        best_match: PublicAtsMatch | None = None
        second_best = 0.0

        for ats_type in cls.PUBLIC_ATS_TYPES:
            for slug in cls._candidate_company_slugs(company):
                postings = cls._fetch_public_ats_postings(ats_type, slug)
                for posting in postings:
                    title = posting.get("title") or ""
                    apply_url = posting.get("apply_url") or ""
                    if not title or not apply_url:
                        continue
                    score = cls._title_match_score(job_title, title)
                    match = PublicAtsMatch(
                        ats_type=ats_type,
                        apply_url=apply_url,
                        title=title,
                        score=score,
                    )

                    if score >= 0.98:
                        return match

                    if best_match is None or score > best_match.score:
                        if best_match is not None:
                            second_best = max(second_best, best_match.score)
                        best_match = match
                    else:
                        second_best = max(second_best, score)

        if best_match and cls._is_confident_public_ats_match(best_match.score, second_best):
            return best_match
        return None

    @classmethod
    def _fetch_public_ats_postings(cls, ats_type: str, slug: str) -> list[dict[str, str]]:
        try:
            if ats_type == "lever":
                response = requests.get(
                    f"https://api.lever.co/v0/postings/{slug}?mode=json",
                    timeout=5,
                    headers={"User-Agent": "JobMatchKit link resolver"},
                )
                if not response.ok:
                    return []
                payload = response.json()
                if not isinstance(payload, list):
                    return []
                return cls._normalise_lever_postings(payload)

            if ats_type == "greenhouse":
                response = requests.get(
                    f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false",
                    timeout=5,
                    headers={"User-Agent": "JobMatchKit link resolver"},
                )
                if not response.ok:
                    return []
                payload = response.json()
                jobs = payload.get("jobs") if isinstance(payload, dict) else None
                if not isinstance(jobs, list):
                    return []
                return cls._normalise_greenhouse_postings(jobs)

            if ats_type == "ashby":
                response = requests.get(
                    f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                    timeout=5,
                    headers={"User-Agent": "JobMatchKit link resolver"},
                )
                if not response.ok:
                    return []
                payload = response.json()
                jobs = payload.get("jobs") if isinstance(payload, dict) else None
                if not isinstance(jobs, list):
                    return []
                return cls._normalise_ashby_postings(jobs)

            if ats_type == "smartrecruiters":
                response = requests.get(
                    f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100",
                    timeout=5,
                    headers={"User-Agent": "JobMatchKit link resolver"},
                )
                if not response.ok:
                    return []
                payload = response.json()
                jobs = payload.get("content") if isinstance(payload, dict) else None
                if not isinstance(jobs, list):
                    return []
                return cls._normalise_smartrecruiters_postings(jobs)
        except (requests.RequestException, ValueError):
            return []

        return []

    @staticmethod
    def _normalise_lever_postings(postings: list[Any]) -> list[dict[str, str]]:
        normalised = []
        for posting in postings:
            if not isinstance(posting, dict):
                continue
            title = str(posting.get("text") or "")
            apply_url = posting.get("applyUrl") or posting.get("hostedUrl")
            if isinstance(apply_url, str) and title:
                normalised.append({"title": title, "apply_url": apply_url})
        return normalised

    @staticmethod
    def _normalise_greenhouse_postings(postings: list[Any]) -> list[dict[str, str]]:
        normalised = []
        for posting in postings:
            if not isinstance(posting, dict):
                continue
            title = str(posting.get("title") or "")
            apply_url = posting.get("absolute_url") or posting.get("url")
            if isinstance(apply_url, str) and title:
                normalised.append({"title": title, "apply_url": apply_url})
        return normalised

    @staticmethod
    def _normalise_ashby_postings(postings: list[Any]) -> list[dict[str, str]]:
        normalised = []
        for posting in postings:
            if not isinstance(posting, dict):
                continue
            title = str(posting.get("title") or "")
            apply_url = (
                posting.get("jobUrl")
                or posting.get("applyUrl")
                or posting.get("externalLink")
                or posting.get("url")
            )
            if isinstance(apply_url, str) and title:
                normalised.append({"title": title, "apply_url": apply_url})
        return normalised

    @staticmethod
    def _normalise_smartrecruiters_postings(postings: list[Any]) -> list[dict[str, str]]:
        normalised = []
        for posting in postings:
            if not isinstance(posting, dict):
                continue
            title = str(posting.get("name") or posting.get("title") or "")
            apply_url = posting.get("ref") or posting.get("postingUrl") or posting.get("url")
            if isinstance(apply_url, str) and title:
                normalised.append({"title": title, "apply_url": apply_url})
        return normalised

    @staticmethod
    def _is_confident_public_ats_match(score: float, second_best: float) -> bool:
        if score >= 0.95:
            return True
        return score >= 0.88 and score - second_best >= 0.08

    @staticmethod
    def _decorate_resolved_ats_url(apply_url: str, ats_type: str, source_type: str) -> str:
        if ats_type == "lever" and source_type != "company_site" and "lever-source=" not in apply_url:
            separator = "&" if "?" in apply_url else "?"
            return f"{apply_url}{separator}lever-source={quote_plus(ApplicationLinkResolver._source_type_label(source_type))}"
        return apply_url

    @staticmethod
    def _source_type_label(source_type: Optional[str]) -> str:
        labels = {
            "linkedin": "LinkedIn",
            "indeed": "Indeed",
            "google_jobs": "Google Jobs",
            "ziprecruiter": "ZipRecruiter",
            "glassdoor": "Glassdoor",
            "company_site": "company page",
            "greenhouse": "Greenhouse",
            "lever": "Lever",
            "ashby": "Ashby",
            "smartrecruiters": "SmartRecruiters",
        }
        return labels.get(source_type or "", (source_type or "source").replace("_", " ").title())

    @staticmethod
    def _clean_html(value: str) -> str:
        without_scripts = re.sub(r"<script.*?</script>|<style.*?</style>", " ", value or "", flags=re.I | re.S)
        without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
        return " ".join(html_lib.unescape(without_tags).split())

    @classmethod
    def _extract_search_redirect_target(cls, raw_url: str) -> Optional[str]:
        url = html_lib.unescape(raw_url or "")
        if url.startswith("//"):
            url = f"https:{url}"
        parsed = urlparse(url)
        if "duckduckgo.com" in (parsed.hostname or ""):
            target = parse_qs(parsed.query).get("uddg", [None])[0]
            if target:
                url = unquote(target)
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.hostname:
            return url
        return None

    @classmethod
    def _is_blocked_search_host(cls, hostname: str) -> bool:
        normalized = hostname.lower().removeprefix("www.")
        return any(normalized == blocked or normalized.endswith(f".{blocked}") for blocked in cls.SEARCH_RESULT_BLOCKED_HOSTS)

    @classmethod
    def _company_domain_or_title_match(cls, company: str, hostname: str, result_title: str) -> bool:
        host_text = cls._normalise_for_match(hostname.replace(".", " ").replace("-", " "))
        title_text = cls._normalise_for_match(result_title)
        terms = cls._company_terms(company)
        if not terms:
            return False
        joined = "".join(terms)
        compact_host = host_text.replace(" ", "")
        if joined and joined in compact_host:
            return True
        return any(term in host_text or term in title_text for term in terms if len(term) >= 4)

    @staticmethod
    def _normalise_for_match(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))

    @classmethod
    def _company_terms(cls, company: str) -> list[str]:
        cleaned = re.sub(r"\([^)]*\)", " ", company.lower())
        cleaned = re.sub(
            r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|staffing|staff)\b\.?",
            " ",
            cleaned,
        )
        return [term for term in re.findall(r"[a-z0-9]+", cleaned) if len(term) >= 3]

    @staticmethod
    def _candidate_company_slugs(company: str) -> list[str]:
        cleaned = re.sub(r"\([^)]*\)", " ", company.lower())
        cleaned = re.sub(r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company)\b\.?", " ", cleaned)
        tokens = re.findall(r"[a-z0-9]+", cleaned)
        candidates = []
        if tokens:
            candidates.extend(("".join(tokens), "-".join(tokens)))

        raw_tokens = re.findall(r"[a-z0-9]+", company.lower())
        if raw_tokens:
            candidates.extend(("".join(raw_tokens), "-".join(raw_tokens)))

        deduped = []
        for candidate in candidates:
            if candidate and candidate not in deduped:
                deduped.append(candidate)
        return deduped[:8]

    @staticmethod
    def _title_match_score(expected_title: str, posting_title: str) -> float:
        expected = " ".join(re.findall(r"[a-z0-9]+", expected_title.lower()))
        posting = " ".join(re.findall(r"[a-z0-9]+", posting_title.lower()))
        if not expected or not posting:
            return 0.0
        if expected == posting:
            return 1.0
        if expected in posting or posting in expected:
            return 0.94

        expected_terms = set(expected.split())
        posting_terms = set(posting.split())
        overlap = len(expected_terms & posting_terms) / max(len(expected_terms | posting_terms), 1)
        sequence = SequenceMatcher(None, expected, posting).ratio()
        return max(sequence, overlap)

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
    async def _click_linkedin_external_apply_button(cls, page, source_type: str) -> Optional[str]:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        except Exception:
            return None

        elements = page.locator('a[href], button, [role="button"]')
        try:
            count = min(await elements.count(), 80)
        except Exception:
            return None

        clicked = 0
        for index in range(count):
            element = elements.nth(index)
            try:
                visible = await element.is_visible(timeout=500)
                if not visible:
                    continue
                metadata = await element.evaluate(
                    """(element) => {
                        const href = element.href
                            || element.getAttribute('href')
                            || element.getAttribute('data-url')
                            || element.getAttribute('data-href')
                            || element.getAttribute('formaction')
                            || "";
                        const text = [
                            element.innerText,
                            element.textContent,
                            element.getAttribute('aria-label'),
                            element.getAttribute('title'),
                            href
                        ].filter(Boolean).join(" ").toLowerCase();
                        return { href, text };
                    }"""
                )
            except Exception:
                continue

            text = metadata.get("text", "")
            href = metadata.get("href", "")
            if not cls._is_external_apply_candidate(text):
                continue

            direct_url = cls._normalize_external_candidate(href, page.url, source_type) if href else None
            if direct_url:
                return direct_url

            clicked += 1
            if clicked > 5:
                return None

            original_url = page.url
            try:
                popup = None
                try:
                    async with page.expect_popup(timeout=2500) as popup_info:
                        await element.click(timeout=3000)
                    popup = await popup_info.value
                except PlaywrightTimeoutError:
                    popup = None

                if popup:
                    try:
                        await popup.wait_for_load_state("domcontentloaded", timeout=5000)
                    except PlaywrightTimeoutError:
                        pass
                    try:
                        await popup.wait_for_load_state("networkidle", timeout=5000)
                    except PlaywrightTimeoutError:
                        pass
                    resolved = cls._normalize_external_candidate(popup.url, original_url, source_type)
                    try:
                        await popup.close()
                    except Exception:
                        pass
                    if resolved:
                        return resolved

                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except PlaywrightTimeoutError:
                    pass
                try:
                    await page.wait_for_timeout(1000)
                except Exception:
                    pass

                resolved = cls._normalize_external_candidate(page.url, original_url, source_type)
                if resolved:
                    return resolved

                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
            except Exception:
                continue

        return None

    @staticmethod
    def _is_external_apply_candidate(text: str) -> bool:
        normalized = " ".join((text or "").lower().split())
        if not normalized:
            return False
        if any(blocked in normalized for blocked in ("easy apply", "save", "saved", "sign in", "log in")):
            return False
        return any(
            marker in normalized
            for marker in (
                "apply",
                "apply now",
                "apply on company",
                "company website",
                "continue to application",
                "external apply",
                "start application",
            )
        )

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
