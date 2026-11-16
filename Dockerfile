FROM python:3.12-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python packages. PIP_INDEX_URL / PIP_TRUSTED_HOST point pip at an
# internal mirror (Nexus, Artifactory, devpi ...) when the build host cannot
# reach pypi.org; empty = pypi.org.
ARG PIP_INDEX_URL=
ARG PIP_TRUSTED_HOST=
COPY requirements.txt .
RUN [ -n "$PIP_INDEX_URL" ] || unset PIP_INDEX_URL; \
    [ -n "$PIP_TRUSTED_HOST" ] || unset PIP_TRUSTED_HOST; \
    pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# Final application image
FROM python:3.12-slim AS app

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-installed Python packages from builder
COPY --from=builder /usr/local /usr/local/

COPY . .
CMD ["/bin/bash", "run.sh"]
