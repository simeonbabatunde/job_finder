FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency definitions
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-install-project

# Copy project
COPY . .

# Install project
RUN uv sync --frozen

# Expose port
EXPOSE 8000

# Run commands using the environment
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
