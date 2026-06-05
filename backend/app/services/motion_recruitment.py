"""
Custom scraper for Motion Recruitment (motionrecruitment.com).
Since python-jobspy doesn't support this site, we scrape it directly.
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import re

from app.observability import log_event

BASE_URL = "https://motionrecruitment.com/tech-jobs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def scrape_motion_recruitment(query: str, location: str, results_wanted: int = 20) -> List[Dict]:
    """
    Scrapes job listings from Motion Recruitment.

    Args:
        query: Search term (e.g. 'python developer')
        location: Location filter (e.g. 'New York')
        results_wanted: Maximum number of results to return

    Returns:
        List of job dicts matching the standard format used by JobSearchService.
    """
    log_event("motion_recruitment.search_started", query=query, location=location, results_wanted=results_wanted)
    all_jobs: List[Dict] = []

    # Scrape multiple pages until we have enough results
    pages_to_scrape = max(1, (results_wanted + 19) // 20)  # 20 results per page
    pages_to_scrape = min(pages_to_scrape, 5)  # Cap at 5 pages to avoid excessive requests

    for page in range(pages_to_scrape):
        start = page * 20
        url = f"{BASE_URL}?start={start}" if start > 0 else BASE_URL

        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()
        except requests.RequestException as e:
            log_event("motion_recruitment.page_failed", level="warning", page=page + 1, error=str(e))
            break

        soup = BeautifulSoup(response.text, "html.parser")
        jobs_on_page = _parse_listing_page(soup)

        if not jobs_on_page:
            break

        all_jobs.extend(jobs_on_page)

        if len(all_jobs) >= results_wanted:
            break

    # Filter by query and location
    filtered = _filter_jobs(all_jobs, query, location)

    log_event(
        "motion_recruitment.search_completed",
        matched_jobs_count=len(filtered),
        scraped_jobs_count=len(all_jobs),
    )
    return filtered[:results_wanted]


def _parse_listing_page(soup: BeautifulSoup) -> List[Dict]:
    """Parse job listings from a Motion Recruitment listing page."""
    jobs: List[Dict] = []

    # Job listings are anchor tags linking to /tech-jobs/{city}/{type}/{slug}/{id}
    job_pattern = re.compile(r"/tech-jobs/[^/]+/(contract|direct-hire|full-time)/[^/]+/\d+$")

    seen_urls = set()
    for link in soup.find_all("a", href=job_pattern):
        href = link.get("href", "")
        full_url = f"https://motionrecruitment.com{href}" if href.startswith("/") else href

        # Deduplicate — same job appears multiple times on the page
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Extract text content from the link
        text = link.get_text(separator="\n", strip=True)
        if not text:
            continue

        job_data = _parse_job_from_link(text, full_url)
        if job_data:
            jobs.append(job_data)

    return jobs


def _parse_job_from_link(text: str, url: str) -> Dict | None:
    """
    Parse job details from a listing link's text content.

    Typical text format (newline-separated):
        Title
        Location
        Work Type (Hybrid/Remote/Onsite/100% Remote/Local Only)
        Job Type (Contract/Direct Hire/Full Time)
        Salary Range
        Description snippet...
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    if len(lines) < 3:
        return None

    title = lines[0]

    # Try to identify location, work arrangement, job type, salary, and description
    location = ""
    job_type = ""
    description = ""

    # Known work arrangements and job types
    work_types = {"hybrid", "onsite", "100% remote", "remote", "local only"}
    job_types = {"contract", "direct hire", "full time"}
    salary_pattern = re.compile(r"\$[\d,.]+")

    remaining_lines = lines[1:]
    desc_start = len(remaining_lines)

    for i, line in enumerate(remaining_lines):
        lower = line.lower()
        if lower in work_types:
            continue  # Skip work arrangement line
        elif lower in job_types:
            job_type = line
        elif salary_pattern.search(line):
            continue  # Skip salary line
        elif not location and i < 3:
            # First non-categorized line near the top is likely the location
            location = line
        else:
            # Everything else is description
            desc_start = i
            break

    description = " ".join(remaining_lines[desc_start:])

    # Extract job ID from URL for deduplication
    job_id_match = re.search(r"/(\d+)$", url)
    job_id = job_id_match.group(1) if job_id_match else ""

    return {
        "id": f"motion_{job_id}",
        "title": title,
        "company": "Motion Recruitment",
        "location": location,
        "description": description if description else "No description available.",
        "url": url,
        "fit_score": 0.0,
    }


def _filter_jobs(jobs: List[Dict], query: str, location: str) -> List[Dict]:
    """Filter jobs by matching query against title/description and location."""
    if not query and not location:
        return jobs

    query_terms = query.lower().split() if query else []
    location_lower = location.lower().strip() if location else ""

    filtered = []
    for job in jobs:
        # Check query match (any term in title or description)
        if query_terms:
            title_lower = job["title"].lower()
            desc_lower = job["description"].lower()
            combined = f"{title_lower} {desc_lower}"
            if not any(term in combined for term in query_terms):
                continue

        # Check location match (partial match)
        if location_lower:
            job_location = job["location"].lower()
            if location_lower not in job_location and job_location not in location_lower:
                # Also check for state abbreviation or city match
                location_parts = location_lower.replace(",", " ").split()
                job_location_parts = job_location.replace(",", " ").split()
                if not any(lp in job_location_parts for lp in location_parts):
                    continue

        filtered.append(job)

    return filtered
