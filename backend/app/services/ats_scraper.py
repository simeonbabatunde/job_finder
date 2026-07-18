import re
from typing import List, Dict, Any

from app.services.official_job_sources import OfficialJobSourceService

class AtsScraper:
    """
    Backward-compatible wrapper for official company application sources.

    New code should use OfficialJobSourceService directly. This class remains so
    older agent/search code and tests can keep their import path while the source
    model moves away from job-board link repair.
    """

    @staticmethod
    def _slugify(name: str) -> str:
        """Convert company name to a likely ATS slug."""
        return re.sub(r'[^a-z0-9]', '', name.lower())

    @staticmethod
    def _fetch_greenhouse(slug: str) -> List[Dict[str, Any]]:
        source = OfficialJobSourceService.discover_sources(slug)
        for candidate in source:
            if candidate.provider == "greenhouse":
                return OfficialJobSourceService.search_company(candidate.company)
        return []

    @staticmethod
    def _fetch_lever(slug: str) -> List[Dict[str, Any]]:
        source = OfficialJobSourceService.discover_sources(slug)
        for candidate in source:
            if candidate.provider == "lever":
                return OfficialJobSourceService.search_company(candidate.company)
        return []

    @staticmethod
    def scrape_company(company_name: str, target_roles: List[str] = []) -> List[Dict[str, Any]]:
        """Fetch a company's jobs from official application sources."""
        return OfficialJobSourceService.search_company(company_name, target_roles=target_roles)
