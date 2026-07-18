from app.agent.state import AgentState, Job
from app.agent.llm_factory import get_llm
from langchain_core.prompts import ChatPromptTemplate
from typing import List
import asyncio
import json
import os
import random
from langchain_core.output_parsers import JsonOutputParser

from app.services.job_search import JobSearchService
from app.services.persistence import PersistenceService
from app.services.application_link_resolver import ApplicationLinkResolver
from app.services.job_pre_screen import JobPreScreenService
from app.observability import log_event, url_host


def attach_link_resolution(job: dict, link_resolution) -> None:
    job["source_url"] = link_resolution.original_url
    job["resolved_url"] = link_resolution.resolved_url
    job["source_type"] = link_resolution.source_type
    job["ats_type"] = link_resolution.ats_type
    job["resolution_status"] = link_resolution.resolution_status
    job["resolution_notes"] = link_resolution.notes


async def resolve_job_link(job: dict, *, allow_browser: bool = False):
    link_resolution = await ApplicationLinkResolver.resolve_url(
        job["url"],
        company=job.get("company"),
        job_title=job.get("title"),
        allow_browser=allow_browser,
    )
    attach_link_resolution(job, link_resolution)
    return link_resolution

async def resolve_job_link_for_analysis(job: dict):
    classification = ApplicationLinkResolver.classify_url(job["url"])
    if classification.resolution_status == "resolved":
        attach_link_resolution(job, classification)
        return classification
    return await resolve_job_link(job, allow_browser=False)

def merge_company_seed_lists(*company_lists):
    companies = []
    seen = set()
    for company_list in company_lists:
        for company in company_list or []:
            clean = " ".join(str(company or "").split())
            key = clean.lower()
            if not clean or key in seen or key in {"unknown", "unknown company"}:
                continue
            seen.add(key)
            companies.append(clean)
    return companies

def is_resolved_application_source(link_resolution) -> bool:
    return link_resolution.resolution_status == "resolved" and bool(link_resolution.resolved_url)

def clean_preference_values(values, fallback):
    selected = []
    seen = set()
    for value in values or []:
        clean = " ".join(str(value or "").split())
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        selected.append(clean)
    return selected or list(fallback)


def role_search_terms(roles, experience_level: str, job_type: str):
    return [
        " ".join(part for part in [experience_level, role, job_type] if part).strip()
        for role in roles
    ]


def role_summary(roles):
    roles = list(roles or [])
    if len(roles) <= 3:
        return ", ".join(roles)
    return f"{', '.join(roles[:3])} +{len(roles) - 3} more"


def _bounded_float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError:
        log_event("agent_node.invalid_float_env", level="warning", variable=name, value=raw_value, default=default)
        return default
    return min(max(value, minimum), maximum)


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError:
        log_event("agent_node.invalid_int_env", level="warning", variable=name, value=raw_value, default=default)
        return default
    return min(max(value, minimum), maximum)


def llm_step_timeout_seconds() -> float:
    return _bounded_float_env("LLM_STEP_TIMEOUT_SECONDS", 90.0, 10.0, 600.0)


def llm_analysis_timeout_seconds() -> float:
    return _bounded_float_env("LLM_ANALYSIS_TIMEOUT_SECONDS", 120.0, 10.0, 600.0)


def llm_analysis_concurrency() -> int:
    return _bounded_int_env("LLM_ANALYSIS_CONCURRENCY", 3, 1, 8)


def format_analysis_error(error: Exception, timeout_seconds: float) -> str:
    if isinstance(error, asyncio.TimeoutError):
        timeout_label = f"{timeout_seconds:.2f}".rstrip("0").rstrip(".")
        return f"Timed out after {timeout_label}s"
    return str(error) or error.__class__.__name__


def application_source_summary(jobs):
    if not jobs:
        return "0 application-ready sources"

    counts = {"company": 0, "ats": 0, "resolved_board": 0, "other": 0}
    board_sources = {"linkedin", "indeed", "google_jobs", "ziprecruiter", "glassdoor"}
    for job in jobs:
        source_type = str(job.get("source_type") or "").lower()
        source_url_type = ""
        if job.get("source_url"):
            source_url_type = ApplicationLinkResolver.classify_url(str(job.get("source_url"))).source_type

        if source_type in board_sources or source_url_type in board_sources:
            counts["resolved_board"] += 1
        elif job.get("ats_type") or source_type == "ats":
            counts["ats"] += 1
        elif source_type == "company_site":
            counts["company"] += 1
        else:
            counts["other"] += 1

    labels = []
    if counts["company"]:
        labels.append(f"{counts['company']} company page")
    if counts["ats"]:
        labels.append(f"{counts['ats']} ATS feed")
    if counts["resolved_board"]:
        labels.append(f"{counts['resolved_board']} resolved board link")
    if counts["other"]:
        labels.append(f"{counts['other']} other")
    return ", ".join(labels)


async def parse_resume(state: AgentState):
    """
    Extracts key skills and summary from resume using LLM.
    """
    resume_content = state.get("resume", "")
    prefs = state.get("preferences")
    target_role = prefs.role[0] if prefs and prefs.role else "General"
    
    if not resume_content or resume_content == "None":
        return {
            "resume_summary": "No resume content provided.", 
            "extracted_skills": [],
            "logs": state.get("logs", []) + ["No resume found to parse."]
        }

    try:
        llm = get_llm()
        parser = JsonOutputParser()
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an expert career coach. Extract a professional summary and a list of key skills from the resume. Return a JSON object with two keys: 'summary' (a string) and 'skills' (a list of strings)."),
            ("user", "Resume Content:\n{resume_text}\n\nExtract Summary and Skills:")
        ])
        
        chain = prompt | llm | parser
        
        response = await asyncio.wait_for(
            chain.ainvoke({
                "resume_text": resume_content[:5000]
            }),
            timeout=llm_step_timeout_seconds(),
        )
        
        summary = response.get("summary", "")
        skills = response.get("skills", [])
        
        log_event(
            "agent_node.resume_parsed",
            agent_run_id=state.get("agent_run_id"),
            user_id=state.get("user_id"),
            skills_count=len(skills),
            summary_present=bool(summary),
        )
        
        # We don't have session here easily to update the DB, 
        # but we can return it in the state and let the next node or endpoint handle it.
        # Actually, let's just keep it in state for now.
        
        log_msg = f"Resume parsed: {len(skills)} skills found."
        
    except Exception as e:
        log_event(
            "agent_node.resume_parse_failed",
            level="error",
            agent_run_id=state.get("agent_run_id"),
            user_id=state.get("user_id"),
            error=str(e),
        )
        summary = "Error parsing resume."
        skills = []
        log_msg = f"Error parsing resume: {e}"

    return {
        "resume_summary": summary, 
        "extracted_skills": skills,
        "logs": state.get("logs", []) + [log_msg]
    }

async def search_jobs(state: AgentState):
    """
    Searches for jobs based on preferences.
    """
    prefs = state.get("preferences")
    query_roles = clean_preference_values(getattr(prefs, "role", []) if prefs else [], ["Software Engineer"])
    location = clean_preference_values(getattr(prefs, "location", []) if prefs else [], ["Remote"])
    days = prefs.posted_within_days if prefs else 7
    exp_levels = clean_preference_values(getattr(prefs, "experience_level", []) if prefs else [], ["Intermediate"])
    job_types = clean_preference_values(getattr(prefs, "job_type", []) if prefs else [], ["Full-time"])
    
    # Construct a more specific search term
    # Example: "Senior Software Engineer Full-time"
    base_role = query_roles[0] if query_roles else "Software Engineer"
    exp = exp_levels[0] if exp_levels else ""
    jtype = job_types[0] if job_types else ""
    
    search_query = f"{exp} {base_role} {jtype}".strip()
    search_terms = role_search_terms(query_roles, exp, jtype)
    search_loc = location[0] if location else "Remote"
    
    allowed_companies = state.get("allowed_companies", [])
    target_companies = merge_company_seed_lists(
        allowed_companies,
        getattr(prefs, "target_companies", []),
    )

    log_event(
        "agent_node.search_started",
        agent_run_id=state.get("agent_run_id"),
        user_id=state.get("user_id"),
        search_role=base_role,
        search_location=search_loc,
        posted_within_days=days,
        search_roles_count=len(query_roles),
        search_terms_count=len(search_terms),
        allowed_companies_count=len(allowed_companies or []),
        target_companies_count=len(target_companies),
    )
    
    jobs = await asyncio.to_thread(
        JobSearchService.search_jobs,
        search_query,
        search_loc,
        posted_within_days=days,
        target_companies=target_companies,
        target_roles=query_roles,
        search_terms=search_terms,
    )
    
    # Persist only jobs worth reviewing; reject results are counted but not saved.
    user_id = state.get("user_id")
    jobs_for_analysis = []
    pre_screen_counts = {"pass": 0, "maybe": 0, "reject": 0}
    unresolved_source_pages_count = 0
    for job in jobs:
        pre_screen = JobPreScreenService.screen(job, prefs)
        job["pre_screen_status"] = pre_screen.status
        job["pre_screen_reasons"] = pre_screen.reasons
        pre_screen_counts[pre_screen.status] = pre_screen_counts.get(pre_screen.status, 0) + 1

        if pre_screen.should_analyze:
            link_resolution = await resolve_job_link_for_analysis(job)
            if not is_resolved_application_source(link_resolution):
                unresolved_source_pages_count += 1
                log_event(
                    "agent_node.unresolved_source_page_skipped",
                    agent_run_id=state.get("agent_run_id"),
                    user_id=user_id,
                    source_type=link_resolution.source_type,
                    resolution_status=link_resolution.resolution_status,
                    company=job.get("company"),
                )
                continue

            PersistenceService.save_job(user_id, job, "Identified", matching_profile_id=state.get("matching_profile_id"), agent_run_id=state.get("agent_run_id"))
            jobs_for_analysis.append(job)

    screened_summary = (
        f"Pre-screen kept {len(jobs_for_analysis)} for AI analysis "
        f"({pre_screen_counts['pass']} pass, {pre_screen_counts['maybe']} maybe) "
        f"and skipped {pre_screen_counts['reject']} obvious non-fits."
    )
    run_logs = [
        f"Found {len(jobs)} application-ready jobs for {role_summary(query_roles)} in '{search_loc}' using official sources first and job boards as fallback discovery.",
        f"Source mix: {application_source_summary(jobs)}.",
        screened_summary,
    ]
    if unresolved_source_pages_count:
        run_logs.append(
            f"Skipped {unresolved_source_pages_count} source-page jobs that could not be resolved to employer application links before analysis."
        )
    log_event(
        "agent_node.search_completed",
        agent_run_id=state.get("agent_run_id"),
        user_id=user_id,
        found_jobs_count=len(jobs),
        jobs_for_analysis_count=len(jobs_for_analysis),
        pre_screen_pass_count=pre_screen_counts["pass"],
        pre_screen_maybe_count=pre_screen_counts["maybe"],
        pre_screen_reject_count=pre_screen_counts["reject"],
        unresolved_source_pages_count=unresolved_source_pages_count,
    )
    
    return {
        "found_jobs": jobs_for_analysis,
        "total_found_jobs": len(jobs),
        "screened_out_jobs_count": pre_screen_counts["reject"],
        "logs": state.get("logs", []) + run_logs
    }

async def analyze_fit(state: AgentState):
    """
    Analyzes the fit of pass/maybe found jobs using an LLM in batch.
    """
    jobs = state.get("found_jobs", [])
    if not jobs:
        return {"application_status": "completed", "logs": state.get("logs", []) + ["No jobs passed pre-screen for AI analysis"]}
    
    resume_summary = state.get("resume_summary", "")
    prefs = state.get("preferences")
    
    # Extract criteria string for the LLM
    criteria = {
        "Desired Experience Level": ", ".join(prefs.experience_level) if prefs else "Not specified",
        "Desired Job Type": ", ".join(prefs.job_type) if prefs else "Not specified",
        "Desired Roles": ", ".join(prefs.role) if prefs else "Not specified"
    }
    criteria_str = json.dumps(criteria, indent=2)

    # Prepare batch inputs
    inputs = []
    for job in jobs:
        inputs.append({
            "job_title": job.get("title", ""),
            "company": job.get("company", ""),
            "description": job.get("description", ""),
            "resume_summary": resume_summary,
            "user_preferences": criteria_str
        })
    
    new_logs = []
    
    try:
        llm = get_llm()
        parser = JsonOutputParser()
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a world class career assistant. Analyze the fit between the candidate's resume, their specific job preferences, and the job description. \n\nUser Preferences:\n{user_preferences}\n\nStrictly penalize matches where the job seniority (e.g. Senior vs Junior) or job type (e.g. Contract vs Full-time) does not align with the user preferences. Return a JSON object with three keys: 'score' (between 0 and 1), 'explanation' (one paragraph string justifying the score based on skills AND preferences), and 'cover_letter' (a professional, customized cover letter text)."),
            ("user", "Job: {job_title} at {company}\nDescription: {description}\n\nResume Summary: {resume_summary}\n\nAnalyze fit and return a structured output in JSON format:")
        ])
        
        chain = prompt | llm | parser
        
        timeout_seconds = llm_analysis_timeout_seconds()
        concurrency = llm_analysis_concurrency()
        semaphore = asyncio.Semaphore(concurrency)

        async def analyze_one(payload):
            async with semaphore:
                return await asyncio.wait_for(chain.ainvoke(payload), timeout=timeout_seconds)

        log_event(
            "agent_node.analysis_started",
            agent_run_id=state.get("agent_run_id"),
            user_id=state.get("user_id"),
            jobs_count=len(inputs),
            timeout_seconds=timeout_seconds,
            concurrency=concurrency,
        )
        results = await asyncio.gather(
            *(analyze_one(payload) for payload in inputs),
            return_exceptions=True,
        )
        
        successful_count = 0
        failed_count = 0

        # Map results back to jobs
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_count += 1
                error_message = format_analysis_error(result, timeout_seconds)
                jobs[i]["fit_score"] = 0.0
                jobs[i]["explanation"] = f"Analysis failed or timed out: {error_message}"
                jobs[i]["cover_letter"] = ""
                PersistenceService.save_job(state.get("user_id"), jobs[i], "Analysis Failed", matching_profile_id=state.get("matching_profile_id"), agent_run_id=state.get("agent_run_id"))
                new_logs.append(f"Analysis failed for {jobs[i]['title']}: {error_message}")
                log_event(
                    "agent_node.job_analysis_failed",
                    level="warning",
                    agent_run_id=state.get("agent_run_id"),
                    user_id=state.get("user_id"),
                    company=jobs[i].get("company"),
                    job_title=jobs[i].get("title"),
                    error=error_message,
                )
                continue

            successful_count += 1
            score_val = result.get("score", 0.5)
            try:
                s = float(score_val)
                if s > 1.0: s = s / 100.0
                score = s
            except:
                score = 0.5
                
            explanation = result.get("explanation", "No explanation provided.")
            cover_letter = result.get("cover_letter", "")
            
            # Update the job in the list
            jobs[i]["fit_score"] = score
            jobs[i]["explanation"] = explanation
            jobs[i]["cover_letter"] = cover_letter

            link_resolution = await resolve_job_link(jobs[i], allow_browser=False)
            if link_resolution.resolution_status == "resolved" and link_resolution.resolved_url:
                new_logs.append(f"Resolved application link for {jobs[i]['title']} at {jobs[i]['company']}.")
            
            # Persist analysis results incrementally
            PersistenceService.save_job(state.get("user_id"), jobs[i], "Analyzed", matching_profile_id=state.get("matching_profile_id"), agent_run_id=state.get("agent_run_id"))
            
            new_logs.append(f"Analyzed {jobs[i]['title']}: {score:.2f}")
        min_score = prefs.min_match_score if prefs and hasattr(prefs, 'min_match_score') else 70
        strong_count = sum(1 for job in jobs if job.get("fit_score", 0.0) * 100 >= min_score)
        below_count = sum(1 for job in jobs if 0 < job.get("fit_score", 0.0) * 100 < min_score)
        new_logs.append(
            f"AI scored {successful_count} of {len(jobs)} roles: {strong_count} met your {min_score}% minimum score, {below_count} stayed below threshold, and {failed_count} failed or timed out."
        )
        log_event(
            "agent_node.analysis_completed",
            agent_run_id=state.get("agent_run_id"),
            user_id=state.get("user_id"),
            jobs_count=len(results),
            successful_count=successful_count,
            failed_count=failed_count,
            strong_count=strong_count,
            below_threshold_count=below_count,
            min_match_score=min_score,
        )

    except Exception as e:
        log_event(
            "agent_node.analysis_failed",
            level="error",
            agent_run_id=state.get("agent_run_id"),
            user_id=state.get("user_id"),
            jobs_count=len(jobs),
            error=str(e),
        )
        new_logs.append(f"Error analyzing jobs: {e}")

    return {
        "found_jobs": jobs, 
        "application_status": "analyzing",
        "logs": state.get("logs", []) + new_logs
    }

async def submit_application(state: AgentState):
    """
    Mark qualifying jobs as ready for user review. Browser form preparation is retired.
    """
    jobs = state.get("analyzed_jobs", [])
    prefs = state.get("preferences")
    min_score = prefs.min_match_score if prefs and hasattr(prefs, 'min_match_score') else 70

    current_submitted = state.get("applications_submitted", [])
    new_submitted = []
    new_logs = []

    for job in jobs:
        fit_score = job.get("fit_score", 0.0)
        pct_score = fit_score * 100

        if pct_score >= min_score and job["url"] not in current_submitted:
            new_submitted.append(job["url"])
            new_logs.append(f"Ready to review {job['title']} at {job['company']}")
            log_event(
                "agent_node.application_ready",
                agent_run_id=state.get("agent_run_id"),
                user_id=state.get("user_id"),
                source_host=url_host(job.get("url")),
                auto_apply=False,
                fit_score=fit_score,
            )

    submitted_urls = current_submitted + new_submitted

    return {
        "applications_submitted": submitted_urls,
        "application_status": "completed",
        "logs": state.get("logs", []) + new_logs,
        "auto_apply_audit": state.get("auto_apply_audit", []),
    }

async def apply_browser(state: AgentState):
    """Retired browser automation node kept as a graph compatibility no-op."""
    return {"application_status": "completed"}
