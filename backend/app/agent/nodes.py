from app.agent.state import AgentState, Job
from app.agent.llm_factory import get_llm
from langchain_core.prompts import ChatPromptTemplate
from typing import List
import json
import random
from langchain_core.output_parsers import JsonOutputParser

from app.services.job_search import JobSearchService
from app.services.browser_apply import BrowserApplyService
from app.services.persistence import PersistenceService
from app.services.application_link_resolver import ApplicationLinkResolver
from app.services.job_pre_screen import JobPreScreenService
from app.observability import log_event, url_host

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
        
        response = await chain.ainvoke({
            "resume_text": resume_content[:5000]
        })
        
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
    query_roles = prefs.role if prefs else ["Software Engineer"]
    location = prefs.location if prefs else ["Remote"]
    days = prefs.posted_within_days if prefs else 7
    exp_levels = prefs.experience_level if prefs else ["Intermediate"]
    job_types = prefs.job_type if prefs else ["Full-time"]
    
    # Construct a more specific search term
    # Example: "Senior Software Engineer Full-time"
    base_role = query_roles[0] if query_roles else "Software Engineer"
    exp = exp_levels[0] if exp_levels else ""
    jtype = job_types[0] if job_types else ""
    
    search_query = f"{exp} {base_role} {jtype}".strip()
    search_loc = location[0] if location else "Remote"
    
    log_event(
        "agent_node.search_started",
        agent_run_id=state.get("agent_run_id"),
        user_id=state.get("user_id"),
        search_role=base_role,
        search_location=search_loc,
        posted_within_days=days,
    )
    
    # Call Real Service
    jobs = JobSearchService.search_jobs(search_query, search_loc, posted_within_days=days)

    # Call Direct ATS Scraper
    target_companies = getattr(prefs, "target_companies", [])
    if target_companies:
        from app.services.ats_scraper import AtsScraper
        for company in target_companies:
            log_event(
                "agent_node.target_company_scrape_started",
                agent_run_id=state.get("agent_run_id"),
                user_id=state.get("user_id"),
                company=company,
            )
            ats_jobs = AtsScraper.scrape_company(company, target_roles=query_roles)
            log_event(
                "agent_node.target_company_scrape_completed",
                agent_run_id=state.get("agent_run_id"),
                user_id=state.get("user_id"),
                company=company,
                jobs_count=len(ats_jobs),
            )
            jobs.extend(ats_jobs)
    
    # Persist only jobs worth reviewing; reject results are counted but not saved.
    user_id = state.get("user_id")
    jobs_for_analysis = []
    pre_screen_counts = {"pass": 0, "maybe": 0, "reject": 0}
    for job in jobs:
        pre_screen = JobPreScreenService.screen(job, prefs)
        job["pre_screen_status"] = pre_screen.status
        job["pre_screen_reasons"] = pre_screen.reasons
        pre_screen_counts[pre_screen.status] = pre_screen_counts.get(pre_screen.status, 0) + 1

        if pre_screen.should_analyze:
            PersistenceService.save_job(user_id, job, "Identified")
            jobs_for_analysis.append(job)

    screened_summary = (
        f"Pre-screen kept {len(jobs_for_analysis)} for AI analysis "
        f"({pre_screen_counts['pass']} pass, {pre_screen_counts['maybe']} maybe) "
        f"and skipped {pre_screen_counts['reject']} obvious non-fits."
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
    )
    
    return {
        "found_jobs": jobs_for_analysis,
        "total_found_jobs": len(jobs),
        "screened_out_jobs_count": pre_screen_counts["reject"],
        "logs": state.get("logs", []) + [
            f"Found {len(jobs)} jobs for '{search_query}' in '{search_loc}' (including {len(target_companies)} target companies)",
            screened_summary,
        ]
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
        
        log_event(
            "agent_node.analysis_started",
            agent_run_id=state.get("agent_run_id"),
            user_id=state.get("user_id"),
            jobs_count=len(inputs),
        )
        results = await chain.abatch(inputs)
        
        # Map results back to jobs
        for i, result in enumerate(results):
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
            
            # Persist analysis results incrementally
            PersistenceService.save_job(state.get("user_id"), jobs[i], "Analyzed")
            
            new_logs.append(f"Analyzed {jobs[i]['title']}: {score:.2f}")
        log_event(
            "agent_node.analysis_completed",
            agent_run_id=state.get("agent_run_id"),
            user_id=state.get("user_id"),
            jobs_count=len(results),
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
        for job in jobs:
            job["fit_score"] = 0.0
            job["cover_letter"] = "Analysis failed due to LLM error."
            PersistenceService.save_job(state.get("user_id"), job, "Analysis Failed")

    return {
        "found_jobs": jobs, 
        "application_status": "analyzing",
        "logs": state.get("logs", []) + new_logs
    }

async def submit_application(state: AgentState):
    """
    Selects matching jobs and prepares supported applications for review.
    """
    jobs = state.get("found_jobs", [])
    if not jobs:
        return {"application_status": "completed", "logs": state.get("logs", [])}
    
    prefs = state.get("preferences")
    min_score = prefs.min_match_score if prefs and hasattr(prefs, 'min_match_score') else 70
    
    current_submitted = state.get("applications_submitted", [])
    new_submitted = []
    new_logs = []
    audit_records = []
    
    for job in jobs:
        fit_score = job.get("fit_score", 0.0)
        pct_score = fit_score * 100
        
        if pct_score >= min_score:
            if job["url"] not in current_submitted:
                if state.get("auto_apply"):
                    link_resolution = ApplicationLinkResolver.classify_url(job["url"])
                    if link_resolution.resolution_status != "resolved" or not link_resolution.ats_type:
                        review_message = (
                            f"Fill-for-review held for review: {link_resolution.notes}"
                        )
                        new_logs.append(f"{job['title']} at {job['company']}: {review_message}")
                        PersistenceService.save_job(state.get("user_id"), job, "Needs Review")
                        audit_records.append({
                            "job_url": job.get("url"),
                            "job_title": job.get("title"),
                            "company": job.get("company"),
                            "action": "resolve",
                            "status": link_resolution.resolution_status,
                            "message": review_message,
                        })
                        log_event(
                            "agent_node.fill_review_held",
                            agent_run_id=state.get("agent_run_id"),
                            user_id=state.get("user_id"),
                            source_host=url_host(job.get("url")),
                            resolution_status=link_resolution.resolution_status,
                            ats_type=link_resolution.ats_type,
                        )
                        continue

                    job["application_url"] = link_resolution.resolved_url or job["url"]

                new_submitted.append(job["url"])
                new_logs.append(f"Ready to apply to {job['title']} at {job['company']}")
                log_event(
                    "agent_node.application_ready",
                    agent_run_id=state.get("agent_run_id"),
                    user_id=state.get("user_id"),
                    source_host=url_host(job.get("url")),
                    auto_apply=state.get("auto_apply"),
                    fit_score=fit_score,
                )
    
    submitted_urls = current_submitted + new_submitted

    return {
        "applications_submitted": submitted_urls,
        "application_status": "applying" if state.get("auto_apply") and submitted_urls else "completed",
        "logs": state.get("logs", []) + new_logs,
        "auto_apply_audit": state.get("auto_apply_audit", []) + audit_records,
    }

async def apply_browser(state: AgentState):
    """
    Browser fill-for-review node. This never clicks final submit.
    """
    if not state.get("auto_apply"):
        return {"application_status": "completed"}

    profile = state.get("profile")
    if not profile:
        log_event(
            "agent_node.browser_fill_skipped",
            level="warning",
            agent_run_id=state.get("agent_run_id"),
            user_id=state.get("user_id"),
            reason="missing_profile",
        )
        return {"logs": state.get("logs", []) + ["Auto-apply skipped: No profile found."]}

    submitted_urls = state.get("applications_submitted", [])
    found_jobs = state.get("found_jobs", [])
    resume_bytes = state.get("resume_bytes")
    resume_filename = state.get("resume_filename", "resume.pdf")

    new_logs = []
    applied_successfully = []
    audit_records = []
    log_event(
        "agent_node.browser_fill_started",
        agent_run_id=state.get("agent_run_id"),
        user_id=state.get("user_id"),
        submitted_urls_count=len(submitted_urls),
    )

    # Only apply to jobs in 'submitted_urls' that aren't already applied in DB?
    # (Actually, endpoints.py handles DB sync from state['applications_submitted'])
    # We should only apply to 'newly' submitted ones.
    
    for job_url in submitted_urls:
        job = next((j for j in found_jobs if j["url"] == job_url), None)
        if not job: continue
        application_url = job.get("application_url") or job["url"]
        link_resolution = ApplicationLinkResolver.classify_url(application_url)
        if link_resolution.resolution_status != "resolved" or not link_resolution.ats_type:
            message = "Fill-for-review skipped because the application URL is not a resolved supported ATS link."
            new_logs.append(f"{job['title']} at {job['company']}: {message}")
            PersistenceService.save_job(state.get("user_id"), job, "Needs Review")
            audit_records.append({
                "job_url": job.get("url", job_url),
                "job_title": job.get("title"),
                "company": job.get("company"),
                "action": "fill_review",
                "status": "needs_review",
                "message": message,
            })
            log_event(
                "agent_node.browser_fill_skipped",
                level="warning",
                agent_run_id=state.get("agent_run_id"),
                user_id=state.get("user_id"),
                source_host=url_host(application_url),
                reason="unsupported_or_unresolved_link",
                resolution_status=link_resolution.resolution_status,
                ats_type=link_resolution.ats_type,
            )
            continue
        
        log_event(
            "agent_node.browser_fill_job_started",
            agent_run_id=state.get("agent_run_id"),
            user_id=state.get("user_id"),
            source_host=url_host(application_url),
            ats_type=link_resolution.ats_type,
        )
        result = await BrowserApplyService.apply_to_job(
            job_url=application_url,
            profile=profile,
            resume_bytes=resume_bytes,
            resume_filename=resume_filename,
            cover_letter=job.get("cover_letter"),
            submit=False
        )
        
        if result["status"] == "success":
            new_logs.append(f"Prepared {job['title']} at {job['company']} for review")
            applied_successfully.append(job_url)
            
            PersistenceService.save_job(state.get("user_id"), job, "Needs Review")
        else:
            new_logs.append(f"Fill-for-review failed for {job['title']}: {result['message']}")
        log_event(
            "agent_node.browser_fill_job_completed",
            agent_run_id=state.get("agent_run_id"),
            user_id=state.get("user_id"),
            source_host=url_host(application_url),
            status=result.get("status", "failed"),
        )

        audit_records.append({
            "job_url": job.get("url", job_url),
            "job_title": job.get("title"),
            "company": job.get("company"),
            "action": "fill_review",
            "status": result.get("status", "failed"),
            "message": result.get("message"),
        })

    log_event(
        "agent_node.browser_fill_completed",
        agent_run_id=state.get("agent_run_id"),
        user_id=state.get("user_id"),
        attempted_jobs_count=len(audit_records),
        prepared_jobs_count=len(applied_successfully),
    )
    return {
        "application_status": "completed",
        "logs": state.get("logs", []) + new_logs,
        "auto_apply_audit": state.get("auto_apply_audit", []) + audit_records,
    }
