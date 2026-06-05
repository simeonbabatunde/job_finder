"""
OAuth configuration and utilities for social login
"""
import os
from fastapi import HTTPException

from app.observability import log_event

# OAuth Configuration
# In production, these should be loaded securely from environment variables
# For local dev/docker-compose, they are passed via environment variables
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")

LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8000/auth/linkedin/callback")

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

def get_google_oauth_url() -> str:
    """Generate Google OAuth URL"""
    if not GOOGLE_CLIENT_ID:
        log_event("oauth.provider_config_missing", level="warning", provider="google", key_name="GOOGLE_CLIENT_ID")
    
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent"
    }
    
    # Simple query string construction
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query_string}"

def get_linkedin_oauth_url() -> str:
    """Generate LinkedIn OAuth URL"""
    if not LINKEDIN_CLIENT_ID:
        log_event("oauth.provider_config_missing", level="warning", provider="linkedin", key_name="LINKEDIN_CLIENT_ID")
    
    params = {
        "client_id": LINKEDIN_CLIENT_ID,
        "redirect_uri": LINKEDIN_REDIRECT_URI,
        "response_type": "code",
        # LinkedIn basic scope
        "scope": "openid profile email" 
    }
    
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    return f"https://www.linkedin.com/oauth/v2/authorization?{query_string}"
