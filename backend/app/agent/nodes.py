from app.agent.state import AgentState, Job
from app.agent.llm_factory import get_llm
from langchain_core.prompts import ChatPromptTemplate
from typing import List
import json
import random
from langchain_core.output_parsers import JsonOutputParser

from app.services.job_search import JobSearchService
from app.services.browser_apply import BrowserApplyService

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
        # Use Gemini
        llm = get_llm(model_type="gemini")
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
        
        print(f"Resume Summary: {summary}")
        print(f"Extracted Skills: {skills}")
        
        # We don't have session here easily to update the DB, 
        # but we can return it in the state and let the next node or endpoint handle it.
        # Actually, let's just keep it in state for now.
        
        log_msg = f"Resume parsed: {len(skills)} skills found."
        
    except Exception as e:
        print(f"Resume Parsing Error: {e}")
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
    
    print(f"Searching for: '{search_query}' in '{search_loc}'")
    
    # Call Real Service
    jobs = JobSearchService.search_jobs(search_query, search_loc, posted_within_days=days)
    
    return {
        "found_jobs": jobs, 
        "logs": state.get("logs", []) + [f"Found {len(jobs)} jobs for '{search_query}' in '{search_loc}'"]
    }

async def analyze_fit(state: AgentState):
    """
    Analyzes the fit of ALL found jobs using an LLM in batch.
    """
    jobs = state.get("found_jobs", [])
    if not jobs:
        return {"application_status": "completed", "logs": state.get("logs", []) + ["No jobs found to analyze"]}
    
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
    
    # Use Gemini
    try:
        llm = get_llm(model_type="gemini")
        parser = JsonOutputParser()
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a world class career assistant. Analyze the fit between the candidate's resume, their specific job preferences, and the job description. \n\nUser Preferences:\n{user_preferences}\n\nStrictly penalize matches where the job seniority (e.g. Senior vs Junior) or job type (e.g. Contract vs Full-time) does not align with the user preferences. Return a JSON object with three keys: 'score' (between 0 and 1), 'explanation' (one paragraph string justifying the score based on skills AND preferences), and 'cover_letter' (a professional, customized cover letter text)."),
            ("user", "Job: {job_title} at {company}\nDescription: {description}\n\nResume Summary: {resume_summary}\n\nAnalyze fit and return a structured output in JSON format:")
        ])
        
        chain = prompt | llm | parser
        
        print(f"Analyzing {len(inputs)} jobs in batch...")
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
            jobs[i]["cover_letter"] = cover_letter
            new_logs.append(f"Analyzed {jobs[i]['title']}: {score:.2f}")

    except Exception as e:
        print(f"LLM Error: {e}. Check GOOGLE_API_KEY in .env.")
        new_logs.append(f"Error analyzing jobs: {e}")
        for job in jobs:
            if "fit_score" not in job:
                job["fit_score"] = 0.5

    return {
        "found_jobs": jobs, 
        "application_status": "analyzing",
        "logs": state.get("logs", []) + new_logs
    }

async def submit_application(state: AgentState):
    """
    Submits applications for jobs that meet the minimum score.
    """
    jobs = state.get("found_jobs", [])
    if not jobs:
        return {"application_status": "completed", "logs": state.get("logs", [])}
    
    prefs = state.get("preferences")
    min_score = prefs.min_match_score if prefs and hasattr(prefs, 'min_match_score') else 70
    
    current_submitted = state.get("applications_submitted", [])
    new_submitted = []
    new_logs = []
    
    for job in jobs:
        fit_score = job.get("fit_score", 0.0)
        pct_score = fit_score * 100
        
        if pct_score >= min_score:
            if job["url"] not in current_submitted:
                new_submitted.append(job["url"])
                new_logs.append(f"Ready to apply to {job['title']} at {job['company']}")
    
    return {
        "applications_submitted": current_submitted + new_submitted,
        "application_status": "applying" if state.get("auto_apply") else "completed",
        "logs": state.get("logs", []) + new_logs
    }

async def apply_browser(state: AgentState):
    """
    Autonomous browser application node.
    """
    if not state.get("auto_apply"):
        return {"application_status": "completed"}

    profile = state.get("profile")
    if not profile:
        return {"logs": state.get("logs", []) + ["Auto-apply skipped: No profile found."]}

    submitted_urls = state.get("applications_submitted", [])
    found_jobs = state.get("found_jobs", [])
    resume_bytes = state.get("resume_bytes")
    resume_filename = state.get("resume_filename", "resume.pdf")

    new_logs = []
    applied_successfully = []

    # Only apply to jobs in 'submitted_urls' that aren't already applied in DB?
    # (Actually, endpoints.py handles DB sync from state['applications_submitted'])
    # We should only apply to 'newly' submitted ones.
    
    for job_url in submitted_urls:
        job = next((j for j in found_jobs if j["url"] == job_url), None)
        if not job: continue
        
        print(f"Auto-Applying to {job['title']}...")
        result = await BrowserApplyService.apply_to_job(
            job_url=job["url"],
            profile=profile,
            resume_bytes=resume_bytes,
            resume_filename=resume_filename,
            cover_letter=job.get("cover_letter")
        )
        
        if result["status"] == "success":
            new_logs.append(f"Successfully auto-filled {job['title']} at {job['company']}")
            applied_successfully.append(job_url)
        else:
            new_logs.append(f"Auto-apply failed for {job['title']}: {result['message']}")

    return {
        "application_status": "completed",
        "logs": state.get("logs", []) + new_logs
    }
