from app.agent.state import AgentState, Job
from app.agent.llm_factory import get_llm
from langchain_core.prompts import ChatPromptTemplate
from typing import List
import json
import random
from langchain_core.output_parsers import JsonOutputParser

from app.services.job_search import JobSearchService

# Mock job search removed

def parse_resume(state: AgentState):
    """
    Extracts key skills and summary from resume using LLM.
    """
    resume_content = state.get("resume", "")
    prefs = state.get("preferences")
    target_role = prefs.role[0] if prefs and prefs.role else "General"
    
    if not resume_content or resume_content == "None":
        return {
            "resume_summary": "No resume content provided.", 
            "logs": ["No resume found to parse."]
        }

    try:
        # Use OpenRouter LLM (same as analyze_fit)
        llm = get_llm(model_type="openrouter", model_name="openai/gpt-oss-20b:free")
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an expert career coach. Extract a professional summary and key skills from the resume, highlighting experience relevant to the target role ({target_role}). Return few paragraphs that capture the essence of the resume and can be used to analyze the fit between the resume and the job."),
            ("user", "Resume Content:\n{resume_text}\n\nExtract Summary:")
        ])
        
        chain = prompt | llm
        
        response = chain.invoke({
            "target_role": target_role,
            "resume_text": resume_content[:5000] # Truncate to avoid huge context usage
        })
        
        summary = response.content
        print(f"Resume Summary: {summary}")
        log_msg = f"Resume parsed for {target_role}"
        
    except Exception as e:
        print(f"Resume Parsing Error: {e}. Check OPENROUTER_API_KEY in .env.")
        summary = "Error parsing resume."
        log_msg = f"Error parsing resume: {e}"

    return {
        "resume_summary": summary, 
        "logs": [log_msg]
    }

def search_jobs(state: AgentState):
    """
    Searches for jobs based on preferences.
    """
    prefs = state.get("preferences")
    query = prefs.role if prefs else "Software Engineer"
    location = prefs.location if prefs else "Remote"
    levels = prefs.experience_level if prefs else ["Intermediate"]
    job_types = prefs.job_type if prefs else ["Full-time"]
    days = prefs.posted_within_days if prefs else 7
    
    # Prepare prompt for log
    levels_str = ", ".join(levels) if isinstance(levels, list) else str(levels)
    job_types_str = ", ".join(job_types) if isinstance(job_types, list) else str(job_types)
    role_str = ", ".join(query) if isinstance(query, list) else str(query)
    loc_str = ", ".join(location) if isinstance(location, list) else str(location)
    
    # Use first role and location for search (simplification for prototype)
    # Use first valid role and location
    # Handle [""] case which is non-empty list but empty string
    valid_queries = [q for q in query if q and q.strip()] if isinstance(query, list) else []
    search_query = valid_queries[0] if valid_queries else "Software Engineer"
    
    valid_locs = [l for l in location if l and l.strip()] if isinstance(location, list) else []
    search_loc = valid_locs[0] if valid_locs else "Remote"
    
    print(f"Searching for: {search_query} in {search_loc}")
    
    # Call Real Service
    jobs = JobSearchService.search_jobs(search_query, search_loc, posted_within_days=days)
    
    return {
        "found_jobs": jobs, 
        "logs": [f"Found {len(jobs)} jobs for {role_str} ({job_types_str}) in {loc_str} (posted within {days} days)"]
    }

def analyze_fit(state: AgentState):
    """
    Analyzes the fit of the found jobs using an LLM.
    """
    jobs = state.get("found_jobs", [])
    if not jobs:
        return {"application_status": "completed", "logs": ["No jobs found to analyze"]}
    
    # Just picking the first one for the prototype flow
    current_job = jobs[0]
    
    # Use OpenRouter LLM
    try:
        llm = get_llm(model_type="openrouter", model_name="openai/gpt-oss-20b:free")
        parser = JsonOutputParser()
        
        # Simple prompt requiring JSON output
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a world class career assistant. Analyze the fit between the candidate's resume and the job description. Return a JSON object with two keys: 'score' (between 0 and 1) and 'explanation' (one paragraph string)."),
            ("user", "Job: {job_title} at {company}\nDescription: {description}\n\nResume Summary: {resume_summary}\n\nAnalyze fit and return a structured output in JSON format:")
        ])
        
        chain = prompt | llm | parser
        
        result = chain.invoke({
            "job_title": current_job["title"],
            "company": current_job["company"],
            "description": current_job["description"],
            "resume_summary": state.get("resume_summary")
        })
        
        # Result is already a dict
        score_val = result.get("score", 0.5)
        try:
            s = float(score_val)
            if s > 1.0: s = s / 100.0
            score = s
        except:
            score = 0.5
            
        explanation = result.get("explanation", "No explanation provided.")
        log_msg = f"Fit Score: {score:.2f}. {explanation[:100]}..."

    except Exception as e:
        print(f"LLM Error: {e}. Check OPENROUTER_API_KEY in .env.")
        log_msg = f"Error analyzing job: {e}"
        score = 0.5

    current_job["fit_score"] = score

    return {
        "current_job": current_job, 
        "application_status": "analyzing",
        "logs": [log_msg]
    }

def submit_application(state: AgentState):
    """
    Mocks the application submission.
    """
    job = state.get("current_job")
    if not job:
        return {"application_status": "completed"}
    
    prefs = state.get("preferences")
    min_score = prefs.min_match_score if prefs and hasattr(prefs, 'min_match_score') else 70
    
    fit_score = job.get("fit_score", 0.0)
    
    if (fit_score * 100) < min_score:
        return {
            "application_status": "completed",
            "logs": [f"Skipped {job['title']} at {job['company']}: Fit Score {fit_score*100:.0f}% < Min {min_score}%"]
        }

    return {
        "applications_submitted": state.get("applications_submitted", []) + [job["url"]],
        "application_status": "completed",
        "logs": [f"Applied to {job['title']} at {job['company']} (Score: {fit_score:.2f})"]
    }
