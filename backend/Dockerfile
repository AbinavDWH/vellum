# Multi-stage minimal production Dockerfile for Vellum Backend API & Engine
# Stage 1: Build & Dependency compilation
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install pinned Terraform CLI binary
ARG TERRAFORM_VERSION=1.9.8
RUN curl -s https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip -o /tmp/terraform.zip \
    && unzip /tmp/terraform.zip -d /usr/local/bin/ \
    && rm /tmp/terraform.zip \
    && chmod +x /usr/local/bin/terraform

# Build isolated Python virtual environment with minimal footprint
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -U pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    # Prune pip, setuptools, build caches, and test artifacts from runtime venv
    && /opt/venv/bin/pip uninstall -y pip setuptools || true \
    && find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true \
    && find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true \
    && find /opt/venv -type f -name "*.pyc" -delete \
    && find /opt/venv -type f -name "*.pyo" -delete

# Stage 2: Minimal hardened runtime
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="Vellum Backend" \
      org.opencontainers.image.description="AI-Driven Autonomous Infrastructure Designer Backend" \
      org.opencontainers.image.vendor="Vellum Team"

# Create unprivileged system user and group (Least Privilege)
RUN groupadd -g 10001 vellum \
    && useradd -u 10001 -g vellum -s /bin/bash -m vellum

# Copy binary & stripped dependencies from builder
COPY --from=builder /usr/local/bin/terraform /usr/local/bin/terraform
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy application source only
COPY --chown=vellum:vellum app/ ./app/

# Create runtime scratch directories with correct permissions
RUN mkdir -p /app/terraform-workspace && chown -R vellum:vellum /app

# Run as non-root user
USER vellum

EXPOSE 8000

# Automated native Python healthcheck (zero external curl dependency)
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
