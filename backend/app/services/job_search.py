from jobspy import scrape_jobs
import pandas as pd
from typing import List, Dict
from sqlmodel import Session, select
from app.database import engine
from app.models import ScraperConfig
from app.services.motion_recruitment import scrape_motion_recruitment

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
            
            # Fetch config from DB
            site_names = ["linkedin", "google"]
            results_wanted = 20
            country_indeed = 'USA'
            
            try:
                with Session(engine) as session:
                    config = session.exec(select(ScraperConfig).order_by(ScraperConfig.updated_at.desc())).first()
                    if config:
                        site_names = config.site_names
                        results_wanted = config.results_wanted
                        country_indeed = config.country_indeed
            except Exception as e:
                print(f"Error fetching scraper config: {e}")

            # Separate custom scrapers from jobspy-supported sites
            CUSTOM_SCRAPERS = {'motion_recruitment'}
            custom_sites = [s for s in site_names if s in CUSTOM_SCRAPERS]
            jobspy_sites = [s for s in site_names if s not in CUSTOM_SCRAPERS]

            # Run Motion Recruitment scraper if enabled
            if 'motion_recruitment' in custom_sites:
                try:
                    motion_jobs = scrape_motion_recruitment(query, location, results_wanted)
                    results.extend(motion_jobs)
                    print(f"Motion Recruitment: Added {len(motion_jobs)} jobs to results.")
                except Exception as e:
                    print(f"Motion Recruitment scraper error: {e}")

            # Run jobspy for standard sites (if any remain)
            if not jobspy_sites:
                return results

            # Scrape Indeed & LinkedIn & Glassdoor via jobspy
            jobs: pd.DataFrame = scrape_jobs(
                site_name=jobspy_sites,
                search_term=query,
                location=location,
                results_wanted=results_wanted,
                hours_old=hours,
                country_indeed=country_indeed,
                linkedin_fetch_description=True # Need description for analysis
            )
            
            if jobs.empty:
                print("JobSpy: No jobs found.")
                return results
            
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
            return results
