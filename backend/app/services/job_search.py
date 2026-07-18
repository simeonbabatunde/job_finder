from jobspy import scrape_jobs
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
import math
import os
import pandas as pd
import re
from typing import Iterable, List, Dict
from sqlmodel import Session, select
from app.database import engine
from app.models import ScraperConfig
from app.observability import log_event
from app.services.motion_recruitment import scrape_motion_recruitment
from app.services.official_job_sources import OfficialJobSourceService
from app.services.company_discovery import CompanyDiscoveryService
from app.services.company_rankings import CompanyRankingService
from app.services.application_link_resolver import ApplicationLinkResolver

class JobSearchService:
    @staticmethod
    def search_jobs(
        query: str,
        location: str,
        posted_within_days: int = 7,
        target_companies: Iterable[str] | None = None,
        target_roles: Iterable[str] | None = None,
        search_terms: Iterable[str] | None = None,
        use_ranked_companies: bool = True,
    ) -> List[Dict]:
        """
        Search jobs with official company/application sources first.

        Job boards remain useful discovery hints, but direct company/application
        links are preferred because they are more stable and immediately usable
        for matching and package generation.
        """
        target_companies = list(target_companies or [])
        target_roles = list(target_roles or [query])
        search_terms = JobSearchService._search_terms(query, search_terms)
        log_event(
            "job_search.started",
            query=query,
            location=location,
            posted_within_days=posted_within_days,
            target_companies_count=len(target_companies),
            target_roles_count=len(target_roles),
            search_terms_count=len(search_terms),
            ranked_company_search_enabled=use_ranked_companies and JobSearchService._ranked_company_search_enabled(),
        )
        results: List[Dict] = []
        board_results: List[Dict] = []

        official_target_jobs = OfficialJobSourceService.search_companies(
            target_companies,
            target_roles=target_roles,
            location=location,
            max_companies=max(len(target_companies), OfficialJobSourceService.MAX_COMPANIES_PER_SEARCH),
            stop_at_target_count=False,
            prioritise_known_sources=False,
        )
        if official_target_jobs:
            results.extend(official_target_jobs)
            log_event(
                "job_search.official_target_results_added",
                jobs_count=len(official_target_jobs),
                companies_count=len(target_companies),
            )
        
        try:
            # JobSpy uses 'hours_old'
            hours = posted_within_days * 24
            
            # Fetch config from DB
            site_names = ["linkedin", "google"]
            results_wanted = 48
            country_indeed = 'USA'
            
            try:
                with Session(engine) as session:
                    config = session.exec(select(ScraperConfig).order_by(ScraperConfig.updated_at.desc())).first()
                    if config:
                        site_names = config.site_names
                        results_wanted = config.results_wanted
                        country_indeed = config.country_indeed
            except Exception as e:
                log_event("job_search.config_load_failed", level="warning", error=str(e))

            per_term_results_wanted = JobSearchService._results_wanted_per_search_term(
                results_wanted,
                len(search_terms),
            )

            if use_ranked_companies and JobSearchService._ranked_company_search_enabled():
                candidate_jobs_count = JobSearchService._candidate_jobs_count(results)
                target_jobs_count = JobSearchService._ranked_company_target_count()
                if target_jobs_count > 0 and candidate_jobs_count >= target_jobs_count:
                    log_event(
                        "job_search.ranked_company_search_skipped",
                        reason="candidate_target_met_after_target_sources",
                        candidate_jobs_count=candidate_jobs_count,
                        target_jobs_count=target_jobs_count,
                    )
                    return JobSearchService._application_ready_results(results, board_results)

                ranked_company_jobs = JobSearchService._search_ranked_company_jobs(
                    query=query,
                    target_roles=target_roles,
                    location=location,
                    seed_companies=target_companies,
                    existing_results=results,
                )
                if ranked_company_jobs:
                    results.extend(ranked_company_jobs)

                candidate_jobs_count = JobSearchService._candidate_jobs_count(results)
                target_jobs_count = JobSearchService._ranked_company_target_count()
                if target_jobs_count > 0 and candidate_jobs_count >= target_jobs_count:
                    log_event(
                        "job_search.board_search_skipped",
                        reason="candidate_target_met_after_ranked_sources",
                        candidate_jobs_count=candidate_jobs_count,
                        target_jobs_count=target_jobs_count,
                    )
                    return JobSearchService._application_ready_results(results, board_results)

            # Separate custom scrapers from jobspy-supported sites
            CUSTOM_SCRAPERS = {'motion_recruitment'}
            custom_sites = [s for s in site_names if s in CUSTOM_SCRAPERS]
            jobspy_sites = [s for s in site_names if s not in CUSTOM_SCRAPERS]

            # Run Motion Recruitment scraper if enabled
            if 'motion_recruitment' in custom_sites:
                for search_term in search_terms:
                    try:
                        motion_jobs = scrape_motion_recruitment(search_term, location, per_term_results_wanted)
                        board_results.extend(motion_jobs)
                        log_event(
                            "job_search.motion_results_added",
                            jobs_count=len(motion_jobs),
                            search_term=search_term,
                        )
                    except Exception as e:
                        log_event("job_search.motion_failed", level="warning", error=str(e), search_term=search_term)

            # Run jobspy for standard sites (if any remain)
            if not jobspy_sites:
                relevant_official_jobs = JobSearchService._search_relevant_official_jobs(
                    query=query,
                    target_roles=target_roles,
                    location=location,
                    seed_companies=target_companies,
                    board_results=board_results,
                    max_companies=results_wanted,
                )
                results.extend(relevant_official_jobs)
                return JobSearchService._application_ready_results(results, board_results)

            # Scrape Indeed & LinkedIn & Glassdoor via jobspy for each capped role term
            jobspy_jobs_count = 0
            for search_term in search_terms:
                jobs = JobSearchService._scrape_jobspy_with_timeout(
                    site_names=jobspy_sites,
                    search_term=search_term,
                    location=location,
                    results_wanted=per_term_results_wanted,
                    hours_old=hours,
                    country_indeed=country_indeed,
                )

                if jobs.empty:
                    log_event("job_search.jobspy_completed", jobs_count=0, search_term=search_term)
                    continue

                jobspy_jobs_count += len(jobs)
                log_event("job_search.jobspy_completed", jobs_count=len(jobs), search_term=search_term)

                # Convert to our format
                for _, row in jobs.iterrows():
                    # Handle missing description or NaN
                    description = row.get("description")
                    if pd.isna(description) or not description:
                        description = "No description available."

                    title = row.get("title")
                    if pd.isna(title): title = "Unknown Title"

                    company = row.get("company")
                    if pd.isna(company): company = "Unknown Company"

                    loc = row.get("location")
                    if pd.isna(loc): loc = location

                    url = row.get("job_url")
                    if pd.isna(url): url = ""

                    # Create job dict
                    job_data = {
                        "id": str(row.get("id")) if not pd.isna(row.get("id")) else "",
                        "title": str(title),
                        "company": str(company),
                        "location": str(loc),
                        "description": str(description),
                        "url": str(url),
                        "fit_score": 0.0 # Will be populated by Agent
                    }
                    board_results.append(job_data)

            if jobspy_jobs_count == 0:
                relevant_official_jobs = JobSearchService._search_relevant_official_jobs(
                    query=query,
                    target_roles=target_roles,
                    location=location,
                    seed_companies=target_companies,
                    board_results=board_results,
                    max_companies=results_wanted,
                )
                results.extend(relevant_official_jobs)
                return JobSearchService._application_ready_results(results, board_results)

            relevant_official_jobs = JobSearchService._search_relevant_official_jobs(
                query=query,
                target_roles=target_roles,
                location=location,
                seed_companies=target_companies,
                board_results=board_results,
                max_companies=results_wanted,
            )
            results.extend(relevant_official_jobs)

            return JobSearchService._application_ready_results(results, board_results)

        except Exception as e:
            log_event("job_search.failed", level="error", error=str(e))
            relevant_official_jobs = JobSearchService._search_relevant_official_jobs(
                query=query,
                target_roles=target_roles,
                location=location,
                seed_companies=target_companies,
                board_results=board_results,
            )
            results.extend(relevant_official_jobs)
            return JobSearchService._application_ready_results(results, board_results)



    @staticmethod
    def _search_terms(primary_query: str, search_terms: Iterable[str] | None) -> List[str]:
        terms = [primary_query, *list(search_terms or [])]
        selected: List[str] = []
        seen = set()
        for term in terms:
            clean = " ".join(str(term or "").split())
            key = clean.lower()
            if not clean or key in seen:
                continue
            seen.add(key)
            selected.append(clean)
            if len(selected) >= JobSearchService._max_search_terms():
                break
        return selected or ["Software Engineer"]

    @staticmethod
    def _results_wanted_per_search_term(results_wanted: int, search_terms_count: int) -> int:
        return max(5, math.ceil(max(results_wanted, 1) / max(search_terms_count, 1)))

    @staticmethod
    def _scrape_jobspy_with_timeout(
        *,
        site_names: List[str],
        search_term: str,
        location: str,
        results_wanted: int,
        hours_old: int,
        country_indeed: str,
    ) -> pd.DataFrame:
        timeout_seconds = JobSearchService._jobspy_search_timeout_seconds()
        fetch_description = JobSearchService._jobspy_linkedin_fetch_description_enabled()
        kwargs = {
            "site_name": site_names,
            "search_term": search_term,
            "location": location,
            "results_wanted": results_wanted,
            "hours_old": hours_old,
            "country_indeed": country_indeed,
            "linkedin_fetch_description": fetch_description,
        }

        if timeout_seconds <= 0:
            return scrape_jobs(**kwargs)

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jobspy-search")
        future = executor.submit(scrape_jobs, **kwargs)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            future.cancel()
            log_event(
                "job_search.jobspy_timeout",
                level="warning",
                search_term=search_term,
                site_names=site_names,
                timeout_seconds=timeout_seconds,
            )
            return pd.DataFrame()
        except Exception as exc:
            log_event(
                "job_search.jobspy_failed",
                level="warning",
                search_term=search_term,
                site_names=site_names,
                error=str(exc),
            )
            return pd.DataFrame()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _jobspy_search_timeout_seconds() -> float:
        raw_value = os.getenv("JOBSPY_SEARCH_TIMEOUT_SECONDS", "30").strip()
        try:
            value = float(raw_value)
        except ValueError:
            log_event("job_search.invalid_float_env", level="warning", variable="JOBSPY_SEARCH_TIMEOUT_SECONDS", value=raw_value, default=30)
            return 30.0
        return min(max(value, 0.0), 180.0)

    @staticmethod
    def _jobspy_linkedin_fetch_description_enabled() -> bool:
        value = os.getenv("JOBSPY_LINKEDIN_FETCH_DESCRIPTION", "false").strip().lower()
        return value in {"1", "true", "yes", "on"}

    @staticmethod
    def _max_search_terms() -> int:
        return max(1, JobSearchService._positive_int_env("MAX_TARGET_ROLE_SEARCH_TERMS", 4, max_value=6))

    @staticmethod
    def _search_ranked_company_jobs(
        *,
        query: str,
        target_roles: Iterable[str],
        location: str,
        seed_companies: Iterable[str],
        existing_results: Iterable[Dict],
    ) -> List[Dict]:
        target_count = JobSearchService._ranked_company_target_count()
        phase_limit = JobSearchService._ranked_company_phase_limit()
        if target_count <= 0 or phase_limit <= 0:
            log_event("job_search.ranked_company_search_skipped", reason="disabled_by_limit")
            return []

        seed_companies = list(seed_companies or [])
        existing_results = list(existing_results or [])
        ranked_results: List[Dict] = []
        fetched_companies: List[str] = []

        try:
            fortune_500_companies = CompanyRankingService.fortune_500_names(
                target_roles=target_roles,
                query=query,
                limit=phase_limit,
                exclude=seed_companies,
            )
            if fortune_500_companies:
                fortune_500_jobs = OfficialJobSourceService.search_companies(
                    fortune_500_companies,
                    target_roles=target_roles,
                    location=location,
                    max_companies=phase_limit,
                )
                ranked_results.extend(fortune_500_jobs)
                fetched_companies.extend(fortune_500_companies)
                log_event(
                    "job_search.ranked_company_phase_completed",
                    phase="fortune_500",
                    companies_count=len(fortune_500_companies),
                    jobs_count=len(fortune_500_jobs),
                    candidate_jobs_count=JobSearchService._candidate_jobs_count([*existing_results, *ranked_results]),
                )

            candidate_jobs_count = JobSearchService._candidate_jobs_count([*existing_results, *ranked_results])
            if candidate_jobs_count >= target_count:
                log_event(
                    "job_search.ranked_company_tail_skipped",
                    reason="candidate_target_met",
                    candidate_jobs_count=candidate_jobs_count,
                    target_jobs_count=target_count,
                )
                return ranked_results

            fortune_tail_companies = CompanyRankingService.fortune_1000_tail_names(
                target_roles=target_roles,
                query=query,
                limit=phase_limit,
                exclude=[*seed_companies, *fetched_companies],
            )
            if fortune_tail_companies:
                fortune_tail_jobs = OfficialJobSourceService.search_companies(
                    fortune_tail_companies,
                    target_roles=target_roles,
                    location=location,
                    max_companies=phase_limit,
                )
                ranked_results.extend(fortune_tail_jobs)
                log_event(
                    "job_search.ranked_company_phase_completed",
                    phase="fortune_1000_tail",
                    companies_count=len(fortune_tail_companies),
                    jobs_count=len(fortune_tail_jobs),
                    candidate_jobs_count=JobSearchService._candidate_jobs_count([*existing_results, *ranked_results]),
                )
        except Exception as exc:
            log_event("job_search.ranked_company_search_failed", level="warning", error=str(exc))

        return ranked_results

    @staticmethod
    def _candidate_jobs_count(jobs: Iterable[Dict]) -> int:
        return len(JobSearchService._dedupe_prefer_employer_links(jobs))

    @staticmethod
    def _ranked_company_search_enabled() -> bool:
        value = os.getenv("FORTUNE_COMPANY_SEARCH_ENABLED", "true").strip().lower()
        return value not in {"0", "false", "no", "off"}

    @staticmethod
    def _ranked_company_target_count() -> int:
        return JobSearchService._positive_int_env("FORTUNE_MIN_CANDIDATE_JOBS", 15, max_value=100)

    @staticmethod
    def _ranked_company_phase_limit() -> int:
        return JobSearchService._positive_int_env("FORTUNE_COMPANIES_PER_PHASE", 16, max_value=40)

    @staticmethod
    def _positive_int_env(name: str, default: int, *, max_value: int) -> int:
        raw_value = os.getenv(name, str(default)).strip()
        try:
            value = int(raw_value)
        except ValueError:
            log_event("job_search.invalid_integer_env", level="warning", variable=name, value=raw_value, default=default)
            return default
        if value < 0:
            return 0
        return min(value, max_value)

    @staticmethod
    def _search_relevant_official_jobs(
        *,
        query: str,
        target_roles: Iterable[str],
        location: str,
        seed_companies: Iterable[str],
        board_results: Iterable[Dict],
        max_companies: int = 20,
    ) -> List[Dict]:
        seed_companies = list(seed_companies or [])
        board_results = list(board_results or [])
        if not seed_companies and not board_results:
            log_event("job_search.relevant_company_search_skipped", reason="no_seed_or_board_companies")
            return []

        company_limit = JobSearchService._relevant_official_company_limit(max_companies)
        if company_limit <= 0:
            log_event("job_search.relevant_company_search_skipped", reason="disabled_by_limit")
            return []

        relevant_companies = CompanyDiscoveryService.discover_company_names(
            seed_companies=seed_companies,
            target_roles=target_roles,
            query=query,
            board_results=board_results,
            max_companies=company_limit,
        )
        companies_to_fetch = JobSearchService._exclude_companies(relevant_companies, seed_companies)
        if not companies_to_fetch:
            return []

        official_jobs = OfficialJobSourceService.search_companies(
            companies_to_fetch,
            target_roles=target_roles,
            location=location,
        )
        log_event(
            "job_search.relevant_company_results_added",
            companies_count=len(companies_to_fetch),
            jobs_count=len(official_jobs),
        )
        return official_jobs

    @staticmethod
    def _exclude_companies(companies: Iterable[str], excluded: Iterable[str]) -> List[str]:
        excluded_keys = {JobSearchService._normalise_company_for_match(str(company)) for company in excluded}
        selected: List[str] = []
        seen = set(excluded_keys)
        for company in companies:
            key = JobSearchService._normalise_company_for_match(str(company))
            clean = " ".join(str(company or "").split())
            if not clean or not key or key in seen:
                continue
            seen.add(key)
            selected.append(clean)
        return selected

    @staticmethod
    def _companies_from_board_results(board_results: Iterable[Dict], *, exclude: Iterable[str], limit: int) -> List[str]:
        excluded = {str(company).strip().lower() for company in exclude if str(company).strip()}
        companies: List[str] = []
        seen = set(excluded)
        for job in board_results:
            company = " ".join(str(job.get("company") or "").split())
            key = company.lower()
            if not company or key in seen or key in {"unknown", "unknown company"}:
                continue
            seen.add(key)
            companies.append(company)
            if len(companies) >= limit:
                break
        return companies

    @staticmethod
    def _application_ready_results(official_results: Iterable[Dict], board_results: Iterable[Dict]) -> List[Dict]:
        official_results = list(official_results)
        board_results = list(board_results)
        official_identities = {
            identity
            for identity in (JobSearchService._company_title_key(job) for job in official_results)
            if identity
        }
        board_results_to_prepare = [
            job
            for job in board_results
            if JobSearchService._company_title_key(job) not in official_identities
        ]
        resolved_board_results = JobSearchService._resolve_application_ready_board_results(board_results_to_prepare)
        if board_results:
            log_event(
                "job_search.board_results_filtered",
                board_jobs_count=len(board_results),
                official_duplicate_count=len(board_results) - len(board_results_to_prepare),
                application_ready_count=len(resolved_board_results),
                unresolved_count=len(board_results_to_prepare) - len(resolved_board_results),
            )
        return JobSearchService._dedupe_prefer_employer_links(official_results + resolved_board_results)


    @staticmethod
    def _resolve_application_ready_board_results(board_results: Iterable[Dict]) -> List[Dict]:
        board_results = list(board_results)[: JobSearchService._board_link_resolution_max_jobs()]
        if not board_results:
            return []

        timeout_seconds = JobSearchService._board_link_resolution_timeout_seconds()
        max_workers = min(4, len(board_results))
        resolved: List[Dict] = []
        executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="board-link-resolver")
        future_to_job = {
            executor.submit(JobSearchService._to_application_ready_board_job, job): job
            for job in board_results
        }
        try:
            for future in as_completed(future_to_job, timeout=timeout_seconds):
                job = future_to_job[future]
                try:
                    prepared = future.result()
                except Exception as exc:
                    log_event(
                        "job_search.board_result_resolution_failed",
                        level="warning",
                        company=job.get("company"),
                        title=job.get("title"),
                        error=str(exc),
                    )
                    continue
                if prepared is not None:
                    resolved.append(prepared)
        except FuturesTimeoutError:
            unfinished = sum(1 for future in future_to_job if not future.done())
            log_event(
                "job_search.board_result_resolution_timeout",
                level="warning",
                attempted_count=len(board_results),
                unfinished_count=unfinished,
                timeout_seconds=timeout_seconds,
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return resolved

    @staticmethod
    def _board_link_resolution_timeout_seconds() -> float:
        raw_value = os.getenv("BOARD_LINK_RESOLUTION_TIMEOUT_SECONDS", "20").strip()
        try:
            value = float(raw_value)
        except ValueError:
            log_event(
                "job_search.invalid_float_env",
                level="warning",
                variable="BOARD_LINK_RESOLUTION_TIMEOUT_SECONDS",
                value=raw_value,
                default=20,
            )
            return 20.0
        return min(max(value, 0.05), 90.0)

    @staticmethod
    def _board_link_resolution_max_jobs() -> int:
        return JobSearchService._positive_int_env("BOARD_LINK_RESOLUTION_MAX_JOBS", 24, max_value=50)

    @staticmethod
    def _relevant_official_company_limit(max_companies: int) -> int:
        configured = JobSearchService._positive_int_env("RELEVANT_OFFICIAL_COMPANIES_MAX", 8, max_value=OfficialJobSourceService.MAX_COMPANIES_PER_SEARCH)
        return min(max(max_companies, 0), configured, OfficialJobSourceService.MAX_COMPANIES_PER_SEARCH)

    @staticmethod
    def _to_application_ready_board_job(job: Dict) -> Dict | None:
        url = str(job.get("resolved_url") or job.get("url") or "").strip()
        if not url:
            return None

        resolution = ApplicationLinkResolver.resolve_url_from_context(
            url,
            company=str(job.get("company") or ""),
            job_title=str(job.get("title") or ""),
        )
        if resolution.resolution_status != "resolved" or not resolution.resolved_url:
            return None

        destination = ApplicationLinkResolver.classify_url(resolution.resolved_url)
        prepared = dict(job)
        prepared["source_url"] = job.get("source_url") or resolution.original_url or url
        prepared["url"] = resolution.resolved_url
        prepared["resolved_url"] = resolution.resolved_url
        prepared["source_type"] = destination.source_type
        prepared["ats_type"] = resolution.ats_type or destination.ats_type
        prepared["resolution_status"] = "resolved"
        prepared["resolution_notes"] = resolution.notes
        return prepared


    @staticmethod
    def _dedupe_prefer_employer_links(jobs: Iterable[Dict]) -> List[Dict]:
        deduped_by_url = OfficialJobSourceService.dedupe_jobs(jobs)
        ordered: List[Dict] = []
        by_identity: Dict[str, Dict] = {}

        for job in deduped_by_url:
            identity = JobSearchService._company_title_key(job)
            if not identity:
                ordered.append(job)
                continue

            existing = by_identity.get(identity)
            if not existing:
                by_identity[identity] = job
                ordered.append(job)
                continue

            if JobSearchService._employer_link_rank(job) > JobSearchService._employer_link_rank(existing):
                ordered[ordered.index(existing)] = job
                by_identity[identity] = job

        return ordered

    @staticmethod
    def _company_title_key(job: Dict) -> str:
        company = JobSearchService._normalise_company_for_match(str(job.get("company") or ""))
        title = JobSearchService._normalise_text_for_match(str(job.get("title") or ""))
        return f"{company}:{title}" if company and title else ""

    @staticmethod
    def _employer_link_rank(job: Dict) -> int:
        url = str(job.get("resolved_url") or job.get("url") or "")
        classification = ApplicationLinkResolver.classify_url(url)
        source_type = str(job.get("source_type") or classification.source_type or "")
        status = str(job.get("resolution_status") or classification.resolution_status or "")
        has_resolved_url = bool(job.get("resolved_url") or classification.resolved_url)

        if source_type == "ats" and has_resolved_url and status == "resolved":
            return 50
        if source_type == "company_site" and has_resolved_url and status == "resolved":
            return 40
        if has_resolved_url and status == "resolved":
            return 30
        if source_type in ApplicationLinkResolver.AGGREGATOR_DOMAINS:
            return 10
        return 20

    @staticmethod
    def _normalise_company_for_match(value: str) -> str:
        cleaned = re.sub(r"\([^)]*\)", " ", value.lower())
        cleaned = re.sub(
            r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company)\b\.?,?",
            " ",
            cleaned,
        )
        return JobSearchService._normalise_text_for_match(cleaned)

    @staticmethod
    def _normalise_text_for_match(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9+#.]+", value.lower()))
