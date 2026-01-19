from jobspy import scrape_jobs
import pandas as pd
from typing import List, Dict

class JobSearchService:
    @staticmethod
    def search_jobs(query: str, location: str, posted_within_days: int = 7) -> List[Dict]:
        """
        Searches for jobs using python-jobspy across multiple sites (Indeed, LinkedIn, Glassdoor).
        """
        print(f"JobSpy: Scraping jobs for '{query}' in '{location}' (Last {posted_within_days} days)...")
        results = []
        
        try:
            # JobSpy uses 'hours_old'
            hours = posted_within_days * 24
            
            # Scrape Indeed & LinkedIn & Glassdoor "indeed", "linkedin", "glassdoor"
            # Note: We limit results_wanted to 15 for speed in this demo
            jobs: pd.DataFrame = scrape_jobs(
                site_name=["glassdoor"], 
                search_term=query,
                location=location,
                results_wanted=5, 
                hours_old=hours, 
                country_indeed='USA',
                linkedin_fetch_description=True # Need description for analysis
            )
            
            if jobs.empty:
                print("JobSpy: No jobs found.")
                return []
            
            print(f"JobSpy: Found {len(jobs)} jobs. \n Details: {jobs}")
            
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
                results.append(job_data)
                
            return results

        except Exception as e:
            print(f"JobSpy Error: {e}")
            return []
