from __future__ import annotations

from dataclasses import dataclass
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
import requests

from app.observability import log_event
from app.services.application_link_resolver import ApplicationLinkResolver


USER_AGENT = "JobMatchKit official source crawler"
BROWSER_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
ProviderFetchCache = dict[tuple[str, str, bool], List[Dict[str, Any]]]


@dataclass(frozen=True)
class OfficialJobSource:
    company: str
    provider: str
    slug: str
    confidence: float


class OfficialJobSourceService:
    """Fetch jobs directly from official company application sources.

    This service intentionally uses public, structured company job feeds first.
    Job-board URLs are useful hints, but official application links are the product
    primitive we want to feed into matching and package generation.
    """

    PROVIDERS = ("greenhouse", "lever", "ashby", "smartrecruiters")
    MAX_COMPANIES_PER_SEARCH = 16
    MAX_JOBS_PER_COMPANY = 80
    MAX_CAREER_SEARCH_ROLES = 4
    MAX_CUSTOM_JOBS_PER_COMPANY = 12
    WORKDAY_COMPANY_BOARDS = {
        "medtronic": ("Medtronic", "medtronic", "MedtronicCareers", "wd1"),
        "micron technology": ("Micron Technology", "micron", "External", "wd1"),
        "nvidia": ("NVIDIA", "nvidia", "NVIDIAExternalCareerSite", "wd5"),
        "nvidia corporation": ("NVIDIA", "nvidia", "NVIDIAExternalCareerSite", "wd5"),
        "toyota": ("Toyota", "toyota", "TMNA", "wd503"),
    }
    PROVIDER_COMPANY_BOARDS = {
        "spacex": OfficialJobSource("SpaceX", "greenhouse", "spacex", 0.94),
    }
    EIGHTFOLD_COMPANY_BOARDS = {
        "microsoft": ("Microsoft", "https://apply.careers.microsoft.com", "microsoft.com"),
        "qualcomm": ("Qualcomm", "https://careers.qualcomm.com", "qualcomm.com"),
    }
    ORACLE_COMPANY_BOARDS = {
        "texas instruments": (
            "Texas Instruments",
            "https://edbz.fa.us2.oraclecloud.com",
            "CX",
            "https://careers.ti.com/en/sites/CX",
        ),
    }
    JIBE_COMPANY_BOARDS = {
        "rivian": (
            "Rivian",
            "https://careers.rivian.com",
            "/api/jobs",
            {"tags2": "Rivian Automotive", "stretch": "10"},
        ),
    }
    HTML_RESULT_COMPANY_BOARDS = {
        "siemens energy": (
            "Siemens Energy",
            "https://jobs.siemens-energy.com/en_US/jobs?keywords={query}&location={location}",
            "https://jobs.siemens-energy.com",
        ),
    }
    COMPANY_NAME_ALIASES = {
        "alphabet": "Google",
        "google": "Google",
        "john deere": "Deere",
        "deere company": "Deere",
        "micron": "Micron Technology",
        "nvidia": "NVIDIA",
        "nvidia corporation": "NVIDIA",
        "st micro": "STMicroelectronics",
        "stmicro": "STMicroelectronics",
        "st microelectronics": "STMicroelectronics",
        "stmicroelectronics": "STMicroelectronics",
        "ti": "Texas Instruments",
    }
    US_STATE_NAMES = {
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
        "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana",
        "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts",
        "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
        "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
        "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
        "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
        "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
    }
    US_STATE_ABBREVIATIONS = {
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il",
        "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt",
        "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri",
        "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
    }

    @classmethod
    def search_companies(
        cls,
        companies: Iterable[str],
        *,
        target_roles: Optional[Iterable[str]] = None,
        location: str = "",
        max_companies: Optional[int] = MAX_COMPANIES_PER_SEARCH,
        target_count: Optional[int] = None,
        stop_at_target_count: bool = True,
        prioritise_known_sources: bool = True,
    ) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        fetch_cache: ProviderFetchCache = {}
        ordered_companies = cls._dedupe_companies(companies)
        if prioritise_known_sources:
            ordered_companies = cls._prioritise_companies(ordered_companies)
        if max_companies is not None:
            ordered_companies = ordered_companies[:max(max_companies, 0)]

        for company in ordered_companies:
            company_jobs = cls.search_company(
                company,
                target_roles=target_roles,
                location=location,
                _fetch_cache=fetch_cache,
            )
            jobs.extend(company_jobs)
            if stop_at_target_count and target_count and len(cls.dedupe_jobs(jobs)) >= target_count:
                log_event(
                    "official_job_sources.target_count_met",
                    jobs_count=len(cls.dedupe_jobs(jobs)),
                    target_count=target_count,
                )
                break
        return cls.dedupe_jobs(jobs)

    @classmethod
    def _prioritise_companies(cls, companies: Iterable[str]) -> List[str]:
        def priority(company: str) -> int:
            key = cls._company_key(company)
            if key in {"apple", "google", "alphabet", "alphabet google"}:
                return 0
            if key in cls.WORKDAY_COMPANY_BOARDS:
                return 1
            return 2

        return sorted(list(companies), key=lambda company: (priority(company), list(companies).index(company)))


    @classmethod
    def search_company(
        cls,
        company: str,
        *,
        target_roles: Optional[Iterable[str]] = None,
        location: str = "",
        _fetch_cache: Optional[ProviderFetchCache] = None,
    ) -> List[Dict[str, Any]]:
        normalized_company = " ".join((company or "").split())
        if not normalized_company:
            return []

        fetch_cache = _fetch_cache if _fetch_cache is not None else {}
        custom_jobs = cls._search_custom_company_careers(
            normalized_company,
            target_roles=target_roles,
            location=location,
        )
        if custom_jobs:
            log_event(
                "official_job_sources.custom_company_matched",
                company=normalized_company,
                jobs_count=len(custom_jobs),
            )
            return custom_jobs

        sources = cls.discover_sources(normalized_company, _fetch_cache=fetch_cache)
        if not sources:
            career_jobs = cls._search_validated_career_pages(
                normalized_company,
                target_roles=target_roles,
                location=location,
            )
            if career_jobs:
                return career_jobs
            log_event("official_job_sources.no_source", company=normalized_company)
            return []

        for source in sources:
            raw_jobs = cls._fetch_provider_jobs(source, _fetch_cache=fetch_cache)
            if not raw_jobs:
                continue
            jobs = [
                cls._to_job_dict(raw_job, source, fallback_location=location)
                for raw_job in raw_jobs
            ]
            filtered = cls._filter_jobs(jobs, target_roles=target_roles, location=location)
            if filtered:
                deduped = cls.dedupe_jobs(filtered)[: cls.MAX_CUSTOM_JOBS_PER_COMPANY]
                log_event(
                    "official_job_sources.company_matched",
                    company=normalized_company,
                    provider=source.provider,
                    slug=source.slug,
                    jobs_count=len(deduped),
                )
                return deduped

        career_jobs = cls._search_validated_career_pages(
            normalized_company,
            target_roles=target_roles,
            location=location,
        )
        if career_jobs:
            return career_jobs

        log_event("official_job_sources.no_matching_jobs", company=normalized_company)
        return []

    @classmethod
    def discover_sources(cls, company: str, *, _fetch_cache: Optional[ProviderFetchCache] = None) -> List[OfficialJobSource]:
        candidates: List[OfficialJobSource] = []
        fetch_cache = _fetch_cache if _fetch_cache is not None else {}
        slugs = ApplicationLinkResolver._candidate_company_slugs(company)
        for slug in slugs:
            for provider in cls.PROVIDERS:
                postings = cls._fetch_provider_postings(
                    provider,
                    slug,
                    include_description=False,
                    _fetch_cache=fetch_cache,
                )
                if postings:
                    candidates.append(
                        OfficialJobSource(
                            company=cls._company_from_postings(company, provider, slug, postings),
                            provider=provider,
                            slug=slug,
                            confidence=0.92 if slugs and slug == slugs[0] else 0.84,
                        )
                    )
                    return candidates
        return candidates

    @classmethod
    def dedupe_jobs(cls, jobs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set[str] = set()
        deduped: List[Dict[str, Any]] = []
        for job in jobs:
            key = cls._job_key(job)
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(job)
        return deduped

    @classmethod
    def _search_custom_company_careers(
        cls,
        company: str,
        *,
        target_roles: Optional[Iterable[str]],
        location: str,
    ) -> List[Dict[str, Any]]:
        company_key = cls._company_key(company)
        roles = cls._normalised_target_roles(target_roles)
        if not roles:
            return []

        if company_key == "apple":
            return cls._search_apple_jobs(roles, location=location)
        if company_key in {"google", "alphabet", "alphabet google"}:
            return cls._search_google_jobs(roles, location=location)
        if company_key in cls.WORKDAY_COMPANY_BOARDS:
            display_name, tenant, site, shard = cls.WORKDAY_COMPANY_BOARDS[company_key]
            return cls._search_workday_jobs(
                display_name,
                tenant=tenant,
                site=site,
                shard=shard,
                roles=roles,
                location=location,
            )
        if company_key in cls.PROVIDER_COMPANY_BOARDS:
            return cls._search_configured_provider_jobs(
                cls.PROVIDER_COMPANY_BOARDS[company_key],
                roles=roles,
                location=location,
            )
        if company_key in cls.EIGHTFOLD_COMPANY_BOARDS:
            display_name, base_url, domain = cls.EIGHTFOLD_COMPANY_BOARDS[company_key]
            return cls._search_eightfold_jobs(
                display_name,
                base_url=base_url,
                domain=domain,
                roles=roles,
                location=location,
            )
        if company_key in cls.ORACLE_COMPANY_BOARDS:
            display_name, api_base_url, site_number, vanity_base_url = cls.ORACLE_COMPANY_BOARDS[company_key]
            return cls._search_oracle_jobs(
                display_name,
                api_base_url=api_base_url,
                site_number=site_number,
                vanity_base_url=vanity_base_url,
                roles=roles,
                location=location,
            )
        if company_key in cls.JIBE_COMPANY_BOARDS:
            display_name, base_url, endpoint_path, extra_params = cls.JIBE_COMPANY_BOARDS[company_key]
            return cls._search_jibe_jobs(
                display_name,
                base_url=base_url,
                endpoint_path=endpoint_path,
                extra_params=extra_params,
                roles=roles,
                location=location,
            )
        if company_key in cls.HTML_RESULT_COMPANY_BOARDS:
            display_name, url_template, base_url = cls.HTML_RESULT_COMPANY_BOARDS[company_key]
            return cls._search_official_html_result_jobs(
                display_name,
                url_template=url_template,
                base_url=base_url,
                roles=roles,
                location=location,
            )
        return []

    @classmethod
    def _normalised_target_roles(cls, target_roles: Optional[Iterable[str]]) -> list[str]:
        roles: list[str] = []
        seen: set[str] = set()
        for role in target_roles or []:
            clean = " ".join(str(role or "").split())
            key = clean.lower()
            if not clean or key in seen:
                continue
            seen.add(key)
            roles.append(clean)
            if len(roles) >= cls.MAX_CAREER_SEARCH_ROLES:
                break
        return roles

    @classmethod
    def _search_configured_provider_jobs(
        cls,
        source: OfficialJobSource,
        *,
        roles: list[str],
        location: str,
    ) -> List[Dict[str, Any]]:
        raw_jobs = cls._fetch_provider_jobs(source)
        jobs = []
        for raw_job in raw_jobs:
            normalised_raw_job = dict(raw_job)
            normalised_raw_job["company"] = source.company
            jobs.append(cls._to_job_dict(normalised_raw_job, source, fallback_location=location))
        return cls.dedupe_jobs(cls._filter_jobs(jobs, target_roles=roles, location=location))[: cls.MAX_CUSTOM_JOBS_PER_COMPANY]

    @classmethod
    def _search_eightfold_jobs(
        cls,
        company: str,
        *,
        base_url: str,
        domain: str,
        roles: list[str],
        location: str,
    ) -> List[Dict[str, Any]]:
        jobs: list[Dict[str, Any]] = []
        endpoint = urljoin(base_url.rstrip("/") + "/", "api/pcsx/search")
        for role in roles:
            for query in cls._custom_role_queries(role):
                params = {
                    "domain": domain,
                    "query": query,
                    "location": cls._career_search_location(location),
                    "start": "0",
                }
                try:
                    response = requests.get(
                        endpoint,
                        params=params,
                        timeout=8,
                        headers={
                            "User-Agent": BROWSER_USER_AGENT,
                            "Accept": "application/json",
                            "Referer": base_url,
                        },
                    )
                except requests.RequestException as exc:
                    log_event("official_job_sources.custom_fetch_failed", level="warning", company=company, provider="eightfold", error=str(exc))
                    continue
                if not response.ok:
                    continue
                try:
                    payload = response.json()
                except ValueError:
                    continue
                positions = payload.get("data", {}).get("positions") if isinstance(payload, dict) else None
                if not isinstance(positions, list):
                    continue
                for position in positions[: cls.MAX_CUSTOM_JOBS_PER_COMPANY]:
                    if not isinstance(position, dict):
                        continue
                    title = " ".join(str(position.get("name") or "").split())
                    position_path = str(position.get("positionUrl") or "").strip()
                    if not title or not position_path:
                        continue
                    locations = position.get("standardizedLocations") or position.get("locations") or []
                    if not isinstance(locations, list):
                        locations = []
                    job_location = "; ".join(str(item) for item in locations[:4] if item) or location or "Unknown"
                    details = [
                        f"Official {company} Eightfold careers listing.",
                        f"Job ID: {position.get('displayJobId') or position.get('atsJobId')}." if position.get("displayJobId") or position.get("atsJobId") else "",
                        f"Department: {position.get('department')}." if position.get("department") else "",
                        f"Search role: {query}.",
                    ]
                    jobs.append(
                        cls._custom_job_dict(
                            title=title,
                            company=company,
                            location=job_location,
                            url=urljoin(base_url.rstrip("/") + "/", position_path.lstrip("/")),
                            description=" ".join(part for part in details if part),
                            source_confidence=0.9,
                        )
                    )
        return cls.dedupe_jobs(cls._filter_jobs(jobs, target_roles=None, location=location))[: cls.MAX_CUSTOM_JOBS_PER_COMPANY]

    @classmethod
    def _search_oracle_jobs(
        cls,
        company: str,
        *,
        api_base_url: str,
        site_number: str,
        vanity_base_url: str,
        roles: list[str],
        location: str,
    ) -> List[Dict[str, Any]]:
        jobs: list[Dict[str, Any]] = []
        endpoint = f"{api_base_url.rstrip('/')}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        expand = "requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations"
        for role in roles:
            for query in cls._custom_role_queries(role):
                finder_parts = [
                    f"siteNumber={site_number}",
                    f"keyword={query}",
                    "sortBy=POSTING_DATES_DESC",
                    f"limit={cls.MAX_CUSTOM_JOBS_PER_COMPANY}",
                    "offset=0",
                ]
                search_location = cls._career_search_location(location)
                if search_location:
                    finder_parts.insert(2, f"location={search_location}")
                try:
                    response = requests.get(
                        endpoint,
                        params={
                            "onlyData": "true",
                            "expand": expand,
                            "finder": "findReqs;" + ",".join(finder_parts),
                        },
                        timeout=8,
                        headers={
                            "User-Agent": BROWSER_USER_AGENT,
                            "Accept": "application/json",
                            "Ora-Irc-Language": "en",
                        },
                    )
                except requests.RequestException as exc:
                    log_event("official_job_sources.custom_fetch_failed", level="warning", company=company, provider="oracle", error=str(exc))
                    continue
                if not response.ok:
                    continue
                try:
                    payload = response.json()
                except ValueError:
                    continue
                items = payload.get("items") if isinstance(payload, dict) else None
                requisitions = items[0].get("requisitionList") if isinstance(items, list) and items and isinstance(items[0], dict) else None
                if not isinstance(requisitions, list):
                    continue
                for requisition in requisitions:
                    if not isinstance(requisition, dict):
                        continue
                    title = " ".join(str(requisition.get("Title") or "").split())
                    requisition_id = str(requisition.get("Id") or "").strip()
                    if not title or not requisition_id:
                        continue
                    job_location = cls._oracle_location_text(requisition) or location or "Unknown"
                    description = cls._clean_html(str(requisition.get("ShortDescriptionStr") or ""))
                    if not description:
                        description = " ".join(
                            part
                            for part in [
                                f"Official {company} Oracle Recruiting listing.",
                                f"Posted: {requisition.get('PostedDate')}." if requisition.get("PostedDate") else "",
                                f"Search role: {query}.",
                            ]
                            if part
                        )
                    jobs.append(
                        cls._custom_job_dict(
                            title=title,
                            company=company,
                            location=job_location,
                            url=f"{vanity_base_url.rstrip('/')}/job/{requisition_id}",
                            description=description,
                            source_confidence=0.9,
                        )
                    )
        return cls.dedupe_jobs(cls._filter_jobs(jobs, target_roles=None, location=location))[: cls.MAX_CUSTOM_JOBS_PER_COMPANY]

    @staticmethod
    def _oracle_location_text(requisition: Dict[str, Any]) -> str:
        location = str(requisition.get("PrimaryLocation") or "").strip()
        if location:
            return location
        work_locations = requisition.get("workLocation") if isinstance(requisition.get("workLocation"), list) else []
        names = []
        for item in work_locations[:3]:
            if not isinstance(item, dict):
                continue
            city = str(item.get("TownOrCity") or "").strip()
            state = str(item.get("Region2") or "").strip()
            country = str(item.get("Country") or "").strip()
            names.append(", ".join(part for part in [city, state, country] if part))
        return "; ".join(name for name in names if name)

    @classmethod
    def _search_jibe_jobs(
        cls,
        company: str,
        *,
        base_url: str,
        endpoint_path: str,
        extra_params: Dict[str, str],
        roles: list[str],
        location: str,
    ) -> List[Dict[str, Any]]:
        jobs: list[Dict[str, Any]] = []
        endpoint = urljoin(base_url.rstrip("/") + "/", endpoint_path.lstrip("/"))
        for role in roles:
            for query in cls._custom_role_queries(role):
                params = {"keywords": query, "limit": str(cls.MAX_CUSTOM_JOBS_PER_COMPANY), "offset": "0", **extra_params}
                search_location = cls._career_search_location(location)
                if search_location:
                    params["location"] = search_location
                try:
                    response = requests.get(
                        endpoint,
                        params=params,
                        timeout=8,
                        headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "application/json", "Referer": base_url},
                    )
                except requests.RequestException as exc:
                    log_event("official_job_sources.custom_fetch_failed", level="warning", company=company, provider="jibe", error=str(exc))
                    continue
                if not response.ok:
                    continue
                try:
                    payload = response.json()
                except ValueError:
                    continue
                rows = payload.get("jobs") if isinstance(payload, dict) else None
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    data = row.get("data") if isinstance(row, dict) else None
                    if not isinstance(data, dict):
                        continue
                    title = " ".join(str(data.get("title") or "").split())
                    url = str(data.get("apply_url") or "").strip()
                    if not title or not url:
                        continue
                    job_location = str(data.get("full_location") or data.get("location_name") or data.get("short_location") or "").strip()
                    description = cls._clean_html(str(data.get("description") or data.get("qualifications") or ""))
                    jobs.append(
                        cls._custom_job_dict(
                            title=title,
                            company=company,
                            location=job_location or location or "Unknown",
                            url=url,
                            description=description or f"Official {company} Jibe careers listing. Search role: {query}.",
                            source_confidence=0.9,
                        )
                    )
        return cls.dedupe_jobs(cls._filter_jobs(jobs, target_roles=None, location=location))[: cls.MAX_CUSTOM_JOBS_PER_COMPANY]

    @classmethod
    def _search_official_html_result_jobs(
        cls,
        company: str,
        *,
        url_template: str,
        base_url: str,
        roles: list[str],
        location: str,
    ) -> List[Dict[str, Any]]:
        jobs: list[Dict[str, Any]] = []
        for role in roles:
            for query in cls._custom_role_queries(role):
                url = url_template.format(query=quote_plus(query), location=quote_plus(cls._career_search_location(location)))
                try:
                    response = requests.get(url, timeout=8, headers={"User-Agent": BROWSER_USER_AGENT})
                except requests.RequestException as exc:
                    log_event("official_job_sources.custom_fetch_failed", level="warning", company=company, provider="html", error=str(exc))
                    continue
                if not response.ok:
                    continue
                soup = BeautifulSoup(response.text, "html.parser")
                for anchor in soup.find_all("a", href=True):
                    title = " ".join(anchor.get_text(" ", strip=True).split())
                    href = str(anchor.get("href") or "").strip()
                    if not title or not href:
                        continue
                    href_lower = href.lower()
                    if not re.search(r"(folderdetail|/job/|/jobs/[a-z0-9_-]+|jobid=|job_id=)", href_lower):
                        continue
                    title_text = cls._clean_match_text(title)
                    query_tokens = cls._meaningful_role_tokens(cls._clean_match_text(query))
                    title_tokens = set(title_text.split())
                    if not cls._matches_any_role(title, [role]) and not (query_tokens and query_tokens & title_tokens):
                        continue
                    jobs.append(
                        cls._custom_job_dict(
                            title=title,
                            company=company,
                            location=location or "Unknown",
                            url=urljoin(base_url.rstrip("/") + "/", href),
                            description=f"Official {company} career search result. Search role: {query}.",
                            source_confidence=0.78,
                        )
                    )
        return cls.dedupe_jobs(cls._filter_jobs(jobs, target_roles=roles, location=location))[: cls.MAX_CUSTOM_JOBS_PER_COMPANY]

    @staticmethod
    def _custom_role_queries(role: str) -> list[str]:
        role_text = " ".join(str(role or "").split())
        role_lower = role_text.lower()
        queries: list[str] = []
        if "firmware" in role_lower:
            queries.append("firmware")
        if "embedded" in role_lower:
            queries.append("embedded firmware")
        if "edge" in role_lower and "ai" in role_lower:
            queries.extend(["edge ai", "machine learning"])
        if "iot" in role_lower:
            queries.extend(["iot", "embedded"])
        queries.append(role_text)

        deduped: list[str] = []
        seen: set[str] = set()
        for query in queries:
            clean = " ".join(query.split())
            key = clean.lower()
            if clean and key not in seen:
                seen.add(key)
                deduped.append(clean)
        return deduped[:3]


    @classmethod
    def _search_apple_jobs(cls, roles: list[str], *, location: str) -> List[Dict[str, Any]]:
        jobs: list[Dict[str, Any]] = []
        for role in roles:
            for query in cls._custom_role_queries(role):
                url = f"https://jobs.apple.com/en-us/search?search={quote_plus(query)}&location=united-states-USA"
                try:
                    response = requests.get(url, timeout=8, headers={"User-Agent": BROWSER_USER_AGENT})
                except requests.RequestException as exc:
                    log_event("official_job_sources.custom_fetch_failed", level="warning", company="Apple", provider="apple", error=str(exc))
                    continue
                if not response.ok:
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                for anchor in soup.select('div.job-list-item h3 a[href^="/en-us/details/"]'):
                    title = " ".join(anchor.get_text(" ", strip=True).split())
                    href = anchor.get("href")
                    if not title or not href or title.lower().startswith("see full"):
                        continue
                    row = anchor.find_parent(class_="job-list-item")
                    team = ""
                    posted = ""
                    job_location = "United States" if location else "USA"
                    if row is not None:
                        team_el = row.select_one(".team-name")
                        posted_el = row.select_one(".job-posted-date")
                        location_el = row.select_one('[id*="store-name-container"]')
                        team = team_el.get_text(" ", strip=True) if team_el else ""
                        posted = posted_el.get_text(" ", strip=True) if posted_el else ""
                        if location_el:
                            city = location_el.get_text(" ", strip=True)
                            job_location = f"United States; {city}" if city else job_location

                    jobs.append(
                        cls._custom_job_dict(
                            title=title,
                            company="Apple",
                            location=job_location,
                            url=urljoin("https://jobs.apple.com", href),
                            description=" ".join(
                                part
                                for part in [
                                    "Official Apple careers listing.",
                                    f"Team: {team}." if team else "",
                                    f"Posted: {posted}." if posted else "",
                                    f"Search role: {query}.",
                                ]
                                if part
                            ),
                            source_confidence=0.9,
                        )
                    )
        return cls.dedupe_jobs(cls._filter_jobs(jobs, target_roles=roles, location=location))[: cls.MAX_CUSTOM_JOBS_PER_COMPANY]

    @classmethod
    def _search_google_jobs(cls, roles: list[str], *, location: str) -> List[Dict[str, Any]]:
        jobs: list[Dict[str, Any]] = []
        location_query = "United States" if cls._location_maybe_matches("United States", location or "USA") else location
        for role in roles:
            for query in cls._custom_role_queries(role):
                url = (
                    "https://www.google.com/about/careers/applications/jobs/results/"
                    f"?q={quote_plus(query)}&location={quote_plus(location_query or 'United States')}"
                )
                try:
                    response = requests.get(url, timeout=8, headers={"User-Agent": BROWSER_USER_AGENT})
                except requests.RequestException as exc:
                    log_event("official_job_sources.custom_fetch_failed", level="warning", company="Google", provider="google", error=str(exc))
                    continue
                if not response.ok:
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                for heading in soup.find_all("h3"):
                    title = " ".join(heading.get_text(" ", strip=True).split())
                    if not title:
                        continue
                    card = heading
                    detail_url = ""
                    card_text = title
                    for _ in range(8):
                        card = card.find_parent("div") if card else None
                        if card is None:
                            break
                        card_text = card.get_text(" ", strip=True)
                        link = card.find("a", href=True)
                        href = link.get("href", "") if link else ""
                        if "jobs/results/" in href:
                            detail_url = urljoin("https://www.google.com/about/careers/applications/", href)
                            break
                    if not detail_url:
                        continue
                    job_location = cls._extract_google_location(card_text) or "United States" if location else "United States"
                    jobs.append(
                        cls._custom_job_dict(
                            title=title,
                            company="Google",
                            location=job_location,
                            url=detail_url,
                            description=f"Official Google careers listing. {card_text[:1200]}",
                            source_confidence=0.9,
                        )
                    )
        return cls.dedupe_jobs(cls._filter_jobs(jobs, target_roles=roles, location=location))[: cls.MAX_CUSTOM_JOBS_PER_COMPANY]

    @classmethod
    def _search_workday_jobs(
        cls,
        company: str,
        *,
        tenant: str,
        site: str,
        shard: str,
        roles: list[str],
        location: str,
    ) -> List[Dict[str, Any]]:
        jobs: list[Dict[str, Any]] = []
        endpoint = f"https://{tenant}.{shard}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
        for role in roles:
            try:
                response = requests.post(
                    endpoint,
                    json={"appliedFacets": {}, "limit": cls.MAX_CUSTOM_JOBS_PER_COMPANY, "offset": 0, "searchText": role},
                    timeout=8,
                    headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
                )
            except requests.RequestException as exc:
                log_event("official_job_sources.custom_fetch_failed", level="warning", company=company, provider="workday", error=str(exc))
                continue
            if not response.ok:
                continue
            try:
                payload = response.json()
            except ValueError:
                continue
            postings = payload.get("jobPostings") if isinstance(payload, dict) else None
            if not isinstance(postings, list):
                continue
            for posting in postings:
                if not isinstance(posting, dict):
                    continue
                title = " ".join(str(posting.get("title") or "").split())
                external_path = str(posting.get("externalPath") or "").strip()
                if not title or not external_path:
                    continue
                locations_text = str(posting.get("locationsText") or "").strip()
                if external_path.startswith("/job/US-") and "United States" not in locations_text:
                    locations_text = "United States" if not locations_text else f"United States; {locations_text}"
                url = f"https://{tenant}.{shard}.myworkdayjobs.com/en-US/{site}{external_path}"
                jobs.append(
                    cls._custom_job_dict(
                        title=title,
                        company=company,
                        location=locations_text or location or "Unknown",
                        url=url,
                        description=" ".join(
                            part
                            for part in [
                                f"Official {company} Workday listing.",
                                str(posting.get("postedOn") or ""),
                                f"Search role: {role}.",
                            ]
                            if part
                        ),
                        source_type="ats",
                        ats_type="workday",
                        source_confidence=0.92,
                    )
                )
        return cls.dedupe_jobs(cls._filter_jobs(jobs, target_roles=None, location=location))[: cls.MAX_CUSTOM_JOBS_PER_COMPANY]

    @staticmethod
    def _extract_google_location(card_text: str) -> str:
        locations = []
        for location in re.findall(r"[A-Z][A-Za-z .'-]+, [A-Z]{2}, USA", card_text or ""):
            clean = re.sub(r"^(Google\s+)?place\s+", "", location).strip()
            if clean:
                locations.append(clean)
        return "; ".join(dict.fromkeys(locations[:3]))

    @staticmethod
    def _custom_job_dict(
        *,
        title: str,
        company: str,
        location: str,
        url: str,
        description: str,
        source_type: str = "company_site",
        ats_type: str | None = None,
        source_confidence: float = 0.86,
    ) -> Dict[str, Any]:
        classification = ApplicationLinkResolver.classify_url(url)
        return {
            "id": url,
            "title": title,
            "company": company,
            "location": location or "Unknown",
            "description": description[:5000] or "Official company career listing.",
            "url": url,
            "source_url": url,
            "resolved_url": url,
            "source_type": source_type if source_type != "company_site" else classification.source_type if classification.source_type == "ats" else "company_site",
            "ats_type": ats_type or classification.ats_type,
            "resolution_status": "resolved",
            "resolution_notes": "Official employer career listing parsed directly from the company career site.",
            "source_confidence": source_confidence,
            "fit_score": 0.0,
        }


    @classmethod
    def _search_validated_career_pages(
        cls,
        company: str,
        *,
        target_roles: Optional[Iterable[str]],
        location: str,
    ) -> List[Dict[str, Any]]:
        roles = [str(role).strip() for role in target_roles or [] if str(role).strip()]
        if not roles:
            return []

        jobs: List[Dict[str, Any]] = []
        deadline = time.monotonic() + cls._career_fallback_company_timeout_seconds()
        for role in roles[: cls.MAX_CAREER_SEARCH_ROLES]:
            if time.monotonic() >= deadline:
                log_event(
                    "official_job_sources.career_page_search_budget_exhausted",
                    level="warning",
                    company=company,
                    timeout_seconds=cls._career_fallback_company_timeout_seconds(),
                )
                break
            career_url = ApplicationLinkResolver._resolve_company_career_from_search(company, role)
            if not career_url:
                continue
            classification = ApplicationLinkResolver.classify_url(career_url)
            source_type = classification.source_type if classification.source_type != "unknown" else "company_site"
            jobs.append(
                {
                    "id": career_url,
                    "title": role,
                    "company": company,
                    "location": location or "Unknown",
                    "url": career_url,
                    "source_url": career_url,
                    "resolved_url": career_url,
                    "source_type": source_type,
                    "ats_type": classification.ats_type,
                    "resolution_status": "resolved",
                    "resolution_notes": "Validated official career page found using company and role search metadata.",
                    "description": "Validated official career page discovered from the employer career site.",
                    "source_confidence": 0.74,
                    "fit_score": 0.0,
                }
            )

        if jobs:
            log_event(
                "official_job_sources.career_page_matched",
                company=company,
                jobs_count=len(jobs),
            )
        return cls.dedupe_jobs(jobs)

    @staticmethod
    def _career_fallback_company_timeout_seconds() -> float:
        raw_value = os.getenv("CAREER_SEARCH_COMPANY_TIMEOUT_SECONDS", "12").strip()
        try:
            value = float(raw_value)
        except ValueError:
            return 12.0
        return min(max(value, 2.0), 60.0)


    @classmethod
    def _fetch_provider_jobs(
        cls,
        source: OfficialJobSource,
        *,
        _fetch_cache: Optional[ProviderFetchCache] = None,
    ) -> List[Dict[str, Any]]:
        return cls._fetch_provider_postings(
            source.provider,
            source.slug,
            include_description=True,
            _fetch_cache=_fetch_cache,
        )

    @classmethod
    def _fetch_provider_postings(
        cls,
        provider: str,
        slug: str,
        *,
        include_description: bool,
        _fetch_cache: Optional[ProviderFetchCache] = None,
    ) -> List[Dict[str, Any]]:
        cache_key = (provider, slug, include_description)
        if _fetch_cache is not None and cache_key in _fetch_cache:
            return list(_fetch_cache[cache_key])

        normalised: List[Dict[str, Any]] = []
        try:
            if provider == "greenhouse":
                content = "true" if include_description else "false"
                response = requests.get(
                    f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content={content}",
                    timeout=8,
                    headers={"User-Agent": USER_AGENT},
                )
                if not response.ok:
                    return cls._cache_fetch_result(_fetch_cache, cache_key, [])
                payload = response.json()
                jobs = payload.get("jobs") if isinstance(payload, dict) else None
                if not isinstance(jobs, list):
                    return cls._cache_fetch_result(_fetch_cache, cache_key, [])
                company = str(payload.get("name") or slug.title()) if isinstance(payload, dict) else slug.title()
                normalised = [cls._normalise_greenhouse_job(job, company) for job in jobs if isinstance(job, dict)]

            elif provider == "lever":
                response = requests.get(
                    f"https://api.lever.co/v0/postings/{slug}?mode=json",
                    timeout=8,
                    headers={"User-Agent": USER_AGENT},
                )
                if not response.ok:
                    return cls._cache_fetch_result(_fetch_cache, cache_key, [])
                payload = response.json()
                if not isinstance(payload, list):
                    return cls._cache_fetch_result(_fetch_cache, cache_key, [])
                normalised = [cls._normalise_lever_job(job, slug.title()) for job in payload if isinstance(job, dict)]

            elif provider == "ashby":
                response = requests.get(
                    f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                    timeout=8,
                    headers={"User-Agent": USER_AGENT},
                )
                if not response.ok:
                    return cls._cache_fetch_result(_fetch_cache, cache_key, [])
                payload = response.json()
                jobs = payload.get("jobs") if isinstance(payload, dict) else None
                if not isinstance(jobs, list):
                    return cls._cache_fetch_result(_fetch_cache, cache_key, [])
                company = str(payload.get("name") or slug.title()) if isinstance(payload, dict) else slug.title()
                normalised = [cls._normalise_ashby_job(job, company) for job in jobs if isinstance(job, dict)]

            elif provider == "smartrecruiters":
                response = requests.get(
                    f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100",
                    timeout=8,
                    headers={"User-Agent": USER_AGENT},
                )
                if not response.ok:
                    return cls._cache_fetch_result(_fetch_cache, cache_key, [])
                payload = response.json()
                jobs = payload.get("content") if isinstance(payload, dict) else None
                if not isinstance(jobs, list):
                    return cls._cache_fetch_result(_fetch_cache, cache_key, [])
                normalised = [cls._normalise_smartrecruiters_job(job, slug.title()) for job in jobs if isinstance(job, dict)]
        except (requests.RequestException, ValueError) as exc:
            log_event("official_job_sources.fetch_failed", level="warning", provider=provider, slug=slug, error=str(exc))

        return cls._cache_fetch_result(_fetch_cache, cache_key, normalised)

    @staticmethod
    def _cache_fetch_result(
        fetch_cache: Optional[ProviderFetchCache],
        cache_key: tuple[str, str, bool],
        postings: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if fetch_cache is not None:
            fetch_cache[cache_key] = list(postings)
        return postings

    @staticmethod
    def _normalise_greenhouse_job(job: Dict[str, Any], company: str) -> Dict[str, Any]:
        return {
            "title": str(job.get("title") or ""),
            "company": company,
            "location": ((job.get("location") or {}).get("name") or ""),
            "url": str(job.get("absolute_url") or job.get("url") or ""),
            "description": OfficialJobSourceService._clean_html(str(job.get("content") or "")),
            "external_id": str(job.get("id") or ""),
        }

    @staticmethod
    def _normalise_lever_job(job: Dict[str, Any], company: str) -> Dict[str, Any]:
        categories = job.get("categories") if isinstance(job.get("categories"), dict) else {}
        return {
            "title": str(job.get("text") or ""),
            "company": company,
            "location": str(categories.get("location") or ""),
            "url": str(job.get("applyUrl") or job.get("hostedUrl") or ""),
            "description": str(job.get("descriptionPlain") or job.get("description") or ""),
            "external_id": str(job.get("id") or ""),
        }

    @staticmethod
    def _normalise_ashby_job(job: Dict[str, Any], company: str) -> Dict[str, Any]:
        location = job.get("location")
        if isinstance(location, dict):
            location_text = str(location.get("name") or "")
        else:
            location_text = str(location or "")
        return {
            "title": str(job.get("title") or ""),
            "company": company,
            "location": location_text,
            "url": str(job.get("jobUrl") or job.get("applyUrl") or job.get("externalLink") or job.get("url") or ""),
            "description": OfficialJobSourceService._clean_html(str(job.get("descriptionHtml") or job.get("description") or "")),
            "external_id": str(job.get("id") or ""),
        }

    @staticmethod
    def _normalise_smartrecruiters_job(job: Dict[str, Any], company: str) -> Dict[str, Any]:
        location = job.get("location") if isinstance(job.get("location"), dict) else {}
        return {
            "title": str(job.get("name") or job.get("title") or ""),
            "company": company,
            "location": str(location.get("fullLocation") or location.get("city") or ""),
            "url": str(job.get("postingUrl") or job.get("ref") or job.get("url") or ""),
            "description": OfficialJobSourceService._clean_html(str(job.get("jobAd") or job.get("description") or "")),
            "external_id": str(job.get("id") or ""),
        }

    @classmethod
    def _to_job_dict(cls, raw_job: Dict[str, Any], source: OfficialJobSource, *, fallback_location: str) -> Dict[str, Any]:
        title = str(raw_job.get("title") or "").strip()
        url = str(raw_job.get("url") or "").strip()
        company = str(raw_job.get("company") or source.company).strip() or source.company
        description = str(raw_job.get("description") or "").strip() or "Official application source listing."
        location = str(raw_job.get("location") or fallback_location or "Unknown").strip()
        return {
            "id": str(raw_job.get("external_id") or url),
            "title": title,
            "company": company,
            "location": location,
            "description": description[:5000],
            "url": url,
            "source_url": url,
            "resolved_url": url,
            "source_type": "ats",
            "ats_type": source.provider,
            "resolution_status": "resolved",
            "resolution_notes": "Official apply link found directly from the company application source.",
            "source_confidence": source.confidence,
            "fit_score": 0.0,
        }

    @classmethod
    def _filter_jobs(
        cls,
        jobs: Iterable[Dict[str, Any]],
        *,
        target_roles: Optional[Iterable[str]],
        location: str,
    ) -> List[Dict[str, Any]]:
        filtered = []
        for job in jobs:
            if not job.get("title") or not job.get("url"):
                continue
            role_match_text = " ".join(
                str(part or "")
                for part in [job.get("title"), job.get("description")]
                if part
            )
            role_match_text = re.sub(r"\bSearch role:\s*[^.]+\.?", " ", role_match_text, flags=re.I)
            if target_roles and not cls._matches_any_role(role_match_text, target_roles):
                continue
            if location and not cls._location_maybe_matches(str(job.get("location") or ""), location):
                continue
            filtered.append(job)
        return filtered

    @classmethod
    def _matches_any_role(cls, title: str, target_roles: Iterable[str]) -> bool:
        target_roles = [role for role in target_roles if str(role).strip()]
        if not target_roles:
            return True
        title_text = cls._clean_match_text(title)
        title_tokens = set(title_text.split())
        for role in target_roles:
            role_text = cls._clean_match_text(str(role))
            if not role_text:
                continue
            if role_text in title_text or title_text in role_text:
                return True
            role_tokens = cls._meaningful_role_tokens(role_text)
            if role_tokens and len(role_tokens & title_tokens) / len(role_tokens) >= 0.67:
                return True
        return False

    @classmethod
    def _career_search_location(cls, location: str) -> str:
        clean = " ".join(str(location or "").split())
        if clean and cls._location_maybe_matches("United States", clean):
            return "United States"
        return clean

    @classmethod
    def _location_maybe_matches(cls, job_location: str, desired_location: str) -> bool:
        desired = cls._clean_match_text(desired_location)
        job = cls._clean_match_text(job_location)
        if not desired or "remote" in desired or "anywhere" in desired:
            return True
        desired_tokens_all = set(desired.split())
        desired_is_us = desired in {"usa", "us", "u s", "united states", "united states usa"} or {"united", "states"}.issubset(desired_tokens_all)
        if desired_is_us and cls._is_us_location(job):
            return True
        if not job:
            return True
        if "remote" in job:
            return True
        desired_tokens = {token for token in desired.split() if len(token) >= 3}
        return not desired_tokens or any(token in job for token in desired_tokens)

    @classmethod
    def _is_us_location(cls, cleaned_location: str) -> bool:
        tokens = set(cleaned_location.split())
        if "usa" in cleaned_location or "united states" in cleaned_location or "u s" in cleaned_location or "us" in tokens:
            return True
        if any(state in cleaned_location for state in cls.US_STATE_NAMES):
            return True
        return bool(tokens & cls.US_STATE_ABBREVIATIONS)

    @staticmethod
    def _meaningful_role_tokens(role_text: str) -> set[str]:
        stopwords = {
            "senior",
            "sr",
            "junior",
            "jr",
            "lead",
            "staff",
            "principal",
            "engineer",
            "developer",
            "manager",
            "specialist",
            "full",
            "time",
        }
        short_signal_tokens = {"ai", "ml", "qa"}
        return {
            token
            for token in role_text.split()
            if (len(token) >= 3 or token in short_signal_tokens) and token not in stopwords
        }

    @staticmethod
    def _clean_match_text(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9+#.]+", (value or "").lower()))

    @staticmethod
    def _clean_html(value: str) -> str:
        without_scripts = re.sub(r"<script.*?</script>|<style.*?</style>", " ", value or "", flags=re.I | re.S)
        without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
        return " ".join(without_tags.split())

    @classmethod
    def _company_from_postings(cls, fallback: str, provider: str, slug: str, postings: List[Dict[str, Any]]) -> str:
        for posting in postings:
            company = str(posting.get("company") or "").strip()
            if company:
                return company
        if provider == "lever":
            return " ".join(part.capitalize() for part in slug.split("-")) or fallback
        return fallback

    @classmethod
    def _dedupe_companies(cls, companies: Iterable[str]) -> List[str]:
        seen: set[str] = set()
        deduped: List[str] = []
        for company in companies:
            clean = cls._canonical_company_name(company)
            key = cls._company_key(clean)
            if not clean or key in seen or key in {"unknown", "unknowncompany"}:
                continue
            seen.add(key)
            deduped.append(clean)
        return deduped

    @classmethod
    def _canonical_company_name(cls, value: str) -> str:
        clean = " ".join(str(value or "").split())
        if clean.lower() in {"unknown", "unknown company"}:
            return ""
        return cls.COMPANY_NAME_ALIASES.get(cls._company_key(clean), clean)

    @staticmethod
    def _company_key(value: str) -> str:
        cleaned = re.sub(r"\([^)]*\)", " ", str(value or "").lower())
        cleaned = re.sub(
            r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|group)\b\.?,?",
            " ",
            cleaned,
        )
        return " ".join(re.findall(r"[a-z0-9]+", cleaned))


    @classmethod
    def _job_key(cls, job: Dict[str, Any]) -> str:
        url = str(job.get("resolved_url") or job.get("url") or "").strip().lower().rstrip("/")
        if url:
            return url
        title = cls._clean_match_text(str(job.get("title") or ""))
        company = cls._clean_match_text(str(job.get("company") or ""))
        return f"{company}:{title}" if title and company else ""
