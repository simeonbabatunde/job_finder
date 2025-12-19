from app.agent.state import AgentState, Job
from app.agent.llm_factory import get_llm
from langchain_core.prompts import ChatPromptTemplate
from typing import List
import json
import random

# Mock Job Data Generator
def mock_job_search(query: str, location: str) -> List[Job]:
    """Generates mock jobs for demonstration."""
    titles = ["Software Engineer", "Backend Developer", "Full Stack Engineer", "AI Engineer", "Data Scientist"]
    companies = ["TechCorp", "DataSystems", "AI Solutions", "WebWorks", "CloudNine"]
    
    jobs = []
    for _ in range(5):
        job: Job = {
            "title": random.choice(titles),
            "company": random.choice(companies),
            "location": location,
            "description": f"We are looking for a skilled {query} to join our team...",
            "url": f"https://example.com/job/{random.randint(1000, 9999)}",
            "source": "mock"
        }
        jobs.append(job)
    return jobs

def parse_resume(state: AgentState):
    """
    Extracts key skills and summary from resume.
    In a real app, this would use an LLM or parser.
    """
    # Simply passing through for now, assuming content is text
    return {"logs": ["Resume parsed (simple pass-through)"]}

def search_jobs(state: AgentState):
    """
    Searches for jobs based on preferences.
    """
    prefs = state.get("preferences")
    query = prefs.role if prefs else "Software Engineer"
    location = prefs.location if prefs else "Remote"
    weeks = prefs.posted_within_weeks if prefs else 1
    
    jobs = mock_job_search(query, location)
    return {"found_jobs": jobs, "logs": [f"Found {len(jobs)} jobs for {query} in {location} (posted within {weeks} weeks)"]}

def analyze_fit(state: AgentState):
    """
    Analyzes the fit of the found jobs using an LLM.
    We will just pick the first one to 'apply' to for the demo loop, 
    or we could iterate. For simplicity in this node, let's just 
    analyze the list and pick the best one to 'apply'.
    """
    jobs = state.get("found_jobs", [])
    if not jobs:
        return {"application_status": "completed", "logs": ["No jobs found to analyze"]}
    
    # Just picking the first one for the prototype flow
    current_job = jobs[0]
    
    # Real logic: use LLM to score.
    # llm = get_llm("openai") # Or from config
    # ...
    
    return {
        "current_job": current_job, 
        "application_status": "analyzing",
        "logs": [f"Selected {current_job['title']} at {current_job['company']} for analysis"]
    }

def submit_application(state: AgentState):
    """
    Mocks the application submission.
    """
    job = state.get("current_job")
    if not job:
        return {"application_status": "completed"}
    
    # Store in DB would happen here or via API callback
    # For the agent state, we just mark it.
    
    return {
        "applications_submitted": state.get("applications_submitted", []) + [job["url"]],
        "application_status": "completed",
        "logs": [f"Applied to {job['title']} at {job['company']}"]
    }
