import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.endpoints import router as api_router
from app.database import create_db_and_tables

LOCAL_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
PRODUCTION_LIKE_ENVS = {"prod", "production", "staging"}


def get_app_env() -> str:
    return (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development").strip().lower()


def split_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def normalize_origin(origin: str) -> str:
    parsed = urlparse(origin.strip())
    if not parsed.scheme or not parsed.netloc:
        return origin.strip().rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}"


def is_local_origin(origin: str) -> bool:
    if origin == "*":
        return True
    parsed = urlparse(origin)
    return parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}


def is_valid_origin(origin: str) -> bool:
    parsed = urlparse(origin)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_https_origin(origin: str) -> bool:
    return urlparse(origin).scheme == "https"


def get_cors_allowed_origins() -> list[str]:
    app_env = get_app_env()
    production_like = app_env in PRODUCTION_LIKE_ENVS
    configured_origins = split_origins(os.getenv("CORS_ALLOWED_ORIGINS", ""))
    frontend_url = os.getenv("FRONTEND_URL", "").strip()

    origins = configured_origins[:]
    if frontend_url:
        origins.append(frontend_url)

    if not origins and not production_like:
        origins = list(LOCAL_CORS_ORIGINS)

    normalized_origins = []
    for origin in origins:
        normalized = normalize_origin(origin)
        if normalized and normalized not in normalized_origins:
            normalized_origins.append(normalized)

    if production_like:
        if not normalized_origins:
            raise RuntimeError("Set CORS_ALLOWED_ORIGINS or FRONTEND_URL before running in production.")
        if any(not is_valid_origin(origin) for origin in normalized_origins):
            raise RuntimeError("Production CORS origins must be valid URL origins such as https://app.example.com.")
        if any(not is_https_origin(origin) for origin in normalized_origins):
            raise RuntimeError("Production CORS origins must use HTTPS.")
        if any(is_local_origin(origin) for origin in normalized_origins):
            raise RuntimeError("Production CORS origins must not include localhost, 127.0.0.1, 0.0.0.0, or '*'.")

    return normalized_origins

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="Job Hunter API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

@app.get("/")
def read_root():
    return {"message": "Hello from Job Hunter API"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
