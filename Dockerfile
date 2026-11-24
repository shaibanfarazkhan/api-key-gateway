FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:${PATH}" \
    RUFF_CACHE_DIR=/tmp/ruff-cache \
    MYPY_CACHE_DIR=/tmp/mypy-cache

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --create-home app

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY migrations ./migrations
COPY tests ./tests
COPY docs ./docs
COPY scripts ./scripts
COPY alembic.ini ./

# Install locked runtime and CI dependencies. Mypy 1.15 avoids the Pydantic
# plugin internal error seen with the newer lockfile release.
RUN pip install --no-cache-dir uv && \
    uv sync --frozen --all-groups --no-editable && \
    uv pip install --python .venv/bin/python mypy==1.15.0 && \
    uv cache clean && \
    pip uninstall -y uv

USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
