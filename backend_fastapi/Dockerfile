# ==========================
#  FASTAPI BACKEND DOCKERFILE
# ==========================

# Base image
FROM public.ecr.aws/docker/library/python:3.11-slim

# Working directory
WORKDIR /app

# Copy backend source
COPY backend_fastapi/ /app/backend_fastapi/

# Copy Alembic config and migrations
COPY alembic.ini /app/alembic.ini

# Gunicorn reads backend_fastapi/deployment/gunicorn.conf.py at startup (see scripts/start_backend.sh),
# so the deploy directory has to exist inside the image.
COPY backend_fastapi/app/migrations/ /app/backend_fastapi/app/migrations/

# The application dependencies rely on pre-built wheels, so we can skip installing
# heavy system build tools. Removing the previous apt-get step avoids sporadic
# network resolution failures when fetching Debian packages during Docker builds.

# F-33: except for postgresql-client. POST /backup/create and /backup/restore
# shell out to pg_dump / pg_restore, and without those binaries in the image
# they return 501 — i.e. every deployment matching this repo's own Postgres
# default had no working backup or restore path at all. `--no-install-recommends`
# keeps this to the client tools; the retry loop mirrors the pip step below,
# for the same flaky-DNS reason.
RUN set -eux; \
    for attempt in 1 2 3; do \
        apt-get update && \
        apt-get install -y --no-install-recommends postgresql-client && \
        rm -rf /var/lib/apt/lists/* && break; \
        if [ "$attempt" -eq 3 ]; then \
            echo "apt-get install postgresql-client failed after ${attempt} attempts" >&2; \
            exit 1; \
        fi; \
        echo "apt-get failed (attempt ${attempt}); retrying in 10s…" >&2; \
        sleep 10; \
    done

# Install Python dependencies with extra resilience against transient DNS failures
# that previously caused builds to abort with "Temporary failure in name resolution".
# We keep pip's own retry logic but wrap it in a short shell loop so Docker BuildKit
# re-attempts the installation a few more times before giving up, giving environments
# with flaky outbound connectivity a better chance to succeed.
ENV PIP_DEFAULT_TIMEOUT=60 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://pypi.org/simple

# Install from requirements.lock, not requirements.txt. requirements.txt pins
# only the 29 direct dependencies; every transitive dependency underneath them
# floated, so two builds of the same commit could ship different code (the
# lockfile was generated and committed for exactly this reason, then never
# wired up to anything). The lock is pip-compile output covering all 73
# packages, and CI asserts it stays consistent with requirements.txt.
RUN set -eux; \
    for attempt in 1 2 3 4 5; do \
        pip install --no-cache-dir --retries 5 --default-timeout "$PIP_DEFAULT_TIMEOUT" -r /app/backend_fastapi/requirements.lock && break; \
        if [ "$attempt" -eq 5 ]; then \
            echo "Pip install failed after ${attempt} attempts" >&2; \
            exit 1; \
        fi; \
        echo "Pip install failed (attempt ${attempt}); retrying in 10s…" >&2; \
        sleep 10; \
    done

# Fix line endings and make scripts executable
RUN find /app/backend_fastapi/scripts -type f -name "*.sh" -exec sed -i 's/\r$//' {} \; \
    && chmod +x /app/backend_fastapi/scripts/*.sh

# Ensure Alembic migrations are present with predictable permissions
RUN test -f /app/backend_fastapi/app/migrations/env.py \
    && mkdir -p /app/backend_fastapi/app/migrations/versions \
    && chmod -R u=rwX,go=rX /app/backend_fastapi/app/migrations

# Pre-create persistent storage directories so Docker named volumes inherit
# the correct ownership (appuser) on first use.
RUN mkdir -p \
        /app/storage/profile_uploads \
        /app/storage/branding/uploads \
        /app/storage/branding/public

# Set environment variables
ENV ALEMBIC_CONFIG=/app/alembic.ini \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend_fastapi

# Create app user for better security
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser /app
USER appuser

# Start backend
ENTRYPOINT ["/usr/bin/env", "sh", "/app/backend_fastapi/scripts/start_backend.sh"]
