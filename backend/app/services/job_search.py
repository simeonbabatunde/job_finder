from typing import List, Dict

class JobSearchService:
    @staticmethod
    def search_jobs(query: str, location: str) -> List[Dict]:
        """
        Searches for jobs using an external API.
        Currently returns mock data for demonstration purposes.
        """
        # TODO: Integrate with a real API like LinkedIn, Indeed, or others.
        
        # Mock results
        mock_jobs = [
            {
                "id": "1",
                "title": f"Senior {query} Developer",
                "company": "Tech Corp",
                "location": location,
                "description": "We are looking for an experienced developer...",
                "salary": "$120k - $150k"
            },
            {
                "id": "2",
                "title": f"Junior {query} Engineer",
                "company": "Startup Inc",
                "location": location,
                "description": "Great opportunity for growth...",
                "salary": "$80k - $100k"
            },
            {
                "id": "3",
                "title": "Product Manager",
                "company": "Business Solns",
                "location": "Remote",
                "description": "Lead our product team...",
                "salary": "$110k - $140k"
            }
        ]
        
        return mock_jobs
