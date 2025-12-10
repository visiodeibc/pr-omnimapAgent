# syntax=docker/dockerfile:1
# ==============================================================================
# OmniMap Agent - Cloud-Agnostic Container
# ==============================================================================
# This Dockerfile is designed to work with any container runtime including:
# - Google Cloud Run
# - AWS ECS/Fargate
# - Azure Container Apps
# - Kubernetes
# - Docker Compose
# ==============================================================================

FROM python:3.11-slim AS base

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Pip settings
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user for security
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home appuser

WORKDIR /app

# ==============================================================================
# Dependencies Stage
# ==============================================================================
FROM base AS dependencies

# Install dependencies first for better layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ==============================================================================
# Final Stage
# ==============================================================================
FROM dependencies AS final

# Copy application code
COPY --chown=appuser:appuser . ./

# Switch to non-root user
USER appuser

# Default port (can be overridden via PORT env var)
ENV PORT=8080

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:${PORT}/health').raise_for_status()" || exit 1

# Expose the port
EXPOSE ${PORT}

# Start the application
# Uses shell form to support PORT environment variable substitution
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}
