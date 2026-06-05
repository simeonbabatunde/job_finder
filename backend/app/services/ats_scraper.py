import requests
import re
from typing import List, Dict, Any

from app.observability import log_event

class AtsScraper:
    """
    Direct ATS scraper for Greenhouse and Lever.
    """

    @staticmethod
    def _slugify(name: str) -> str:
        """Convert company name to a likely ATS slug."""
        return re.sub(r'[^a-z0-9]', '', name.lower())

    @staticmethod
    def _fetch_greenhouse(slug: str) -> List[Dict[str, Any]]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                jobs = []
                for job in data.get("jobs", []):
                    jobs.append({
                        "title": job.get("title"),
                        "company": data.get("name", slug.title()),
                        "location": job.get("location", {}).get("name", "Unknown"),
                        "url": job.get("absolute_url"),
                        "description": "Greenhouse Direct Listing", # We don't fetch full desc to save time, unless needed
                        "job_type": "Full-time" # Default assumption
                    })
                return jobs
        except Exception as e:
            log_event("ats_scraper.greenhouse_failed", level="warning", slug=slug, error=str(e))
        return []

    @staticmethod
    def _fetch_lever(slug: str) -> List[Dict[str, Any]]:
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                jobs = []
                for job in data:
                    jobs.append({
                        "title": job.get("text"),
                        "company": slug.title(), # Lever API doesn't return company name cleanly in root
                        "location": job.get("categories", {}).get("location", "Unknown"),
                        "url": job.get("hostedUrl"),
                        "description": job.get("descriptionPlain", "Lever Direct Listing")[:1000],
                        "job_type": "Full-time"
                    })
                return jobs
        except Exception as e:
            log_event("ats_scraper.lever_failed", level="warning", slug=slug, error=str(e))
        return []

    @staticmethod
    def scrape_company(company_name: str, target_roles: List[str] = []) -> List[Dict[str, Any]]:
        """
        Attempts to scrape a company's jobs from known ATS providers.
        Filters by target roles if provided.
        """
        slug = AtsScraper._slugify(company_name)
        jobs = []

        # Try Greenhouse
        gh_jobs = AtsScraper._fetch_greenhouse(slug)
        if gh_jobs:
            jobs = gh_jobs
        else:
            # Fallback to Lever
            lv_jobs = AtsScraper._fetch_lever(slug)
            if lv_jobs:
                jobs = lv_jobs

        # Filter by roles if applicable
        if target_roles and jobs:
            filtered = []
            role_keywords = [r.lower() for r in target_roles]
            for job in jobs:
                title_lower = job.get("title", "").lower()
                if any(k in title_lower for k in role_keywords):
                    filtered.append(job)
            return filtered

        return jobs
