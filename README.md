# Job Finder

Job Finder is an AI-assisted job search and application workspace. The product goal is to let a user upload a resume, save their job preferences and profile, discover matching roles, generate application materials, track application status, and optionally use a browser agent to fill or submit applications.

This project currently uses the name "Job Hunter" in parts of the UI and API. Keep that naming consistent until a final brand decision is made.

## Current Stack

- Frontend: React 19, TypeScript, Vite, Tailwind CSS 4
- Backend: FastAPI, SQLModel, PostgreSQL, LangGraph, LangChain
- Job discovery: python-jobspy plus custom scrapers
- LLM providers: OpenAI, OpenRouter, Gemini, Ollama support through `backend/app/agent/llm_factory.py`
- Browser automation: Playwright for form filling and optional submission
- Local orchestration: Docker Compose
- Python dependency manager: uv through `backend/pyproject.toml` and `backend/uv.lock`

## Product Shape

The current app already supports the main workflow:

1. Sign in or register.
2. Upload a resume.
3. Fill a personal profile for application forms and cover letters.
4. Set job preferences and target companies.
5. Run the agent to search, analyze, and optionally auto-submit.
6. Review matched jobs and application status.
7. Prepare a cover letter, tailored summary, Q&A answers, interview prep, and company brief for a selected job.

## Design Direction

The next UI pass should follow the same practical, research-dashboard design language used in the Influence Chart project:

- Light operational surface: `#f6f8fb`
- Primary ink: `#172033`
- Muted text: `#657084`
- Borders: `#dce2ea`
- Soft fill: `#eef3f7`
- Accent: `#176b63`
- Accent soft: `#dff3ee`
- Positive state: `#177245`

That means the Job Finder interface should feel like a focused career operations dashboard: dense, calm, scannable, and useful immediately. Avoid decorative gradient orbs, oversized hero treatment, nested cards, and emoji-led controls.

Detailed UI direction is in [docs/UI_UX_DIRECTION.md](./docs/UI_UX_DIRECTION.md).

## Project Docs

- [Implementation Plan](./docs/IMPLEMENTATION_PLAN.md)
- [UI/UX Direction](./docs/UI_UX_DIRECTION.md)
- [Handoff](./docs/HANDOFF.md)
- [Frontend README](./frontend/README.md)
- [Backend README](./backend/README.md)

## Local Development

Recommended full stack:

```bash
docker compose up --build
```

Frontend only:

```bash
cd frontend
npm install
npm run dev
```

Backend only:

```bash
cd backend
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Default URLs:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Postgres: `localhost:5432`

## Important Current Risks

- Auth now uses signed bearer tokens stored in local storage. This is better than the old email header but should move to hardened sessions or JWT infrastructure before production.
- Resume and preferences are scoped to the active user in the core backend flows.
- Database startup uses `SQLModel.metadata.create_all` plus a lightweight versioned migration table. Alembic is still a good future upgrade before production.
- The previous backend README contained a plaintext OpenRouter key. It has been removed from docs, but the key should be rotated if it was real.
- Daily agent-run quotas, pro/admin auto-submit gating, persisted agent run logs, and auto-apply audit records are implemented.
- The focused backend API contract suite now covers auth, ownership, migrations, application queries, quotas, and agent run persistence.

See [docs/IMPLEMENTATION_PLAN.md](./docs/IMPLEMENTATION_PLAN.md) for the staged fix plan.
