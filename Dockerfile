# ─────────────────────────────────────────────────────────────────────────────
# Agentic Game-Builder AI  –  Dockerfile (Gemini ADK Edition)
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: build dependencies ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: lean runtime ─────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Non-root user for security
RUN useradd -m -u 1000 agent

WORKDIR /app

# Copy source (respects .dockerignore)
COPY --chown=agent:agent . .

# Output directory – made world-writable so bind-mounts work
# regardless of the host user's UID
RUN mkdir -p /output && chmod 777 /output

# Runtime environment
ENV OUTPUT_DIR=/output \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER agent

# Interactive CLI – run with:
#   docker run -it --rm \
#     -e GEMINI_API_KEY=AIza... \
#     -v "$(pwd)/output:/output" \
#     game-builder-agent [optional inline game idea]
ENTRYPOINT ["python", "agent.py"]
