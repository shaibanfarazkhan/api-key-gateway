.PHONY: install install-dev run migrate revision lint format typecheck test ci compose-up compose-down

install:
	uv sync

install-dev:
	uv sync --all-groups

run:
	uv run uvicorn app.main:app --reload

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(message)"

lint:
	uv run ruff check .

format:
	uv run ruff check --fix .
	uv run ruff format .
	uv run black .

typecheck:
	uv run python -m mypy .

test:
	uv run python -m pytest

ci: lint
	uv run ruff format --check .
	uv run black --check .
	uv run python -m mypy .
	uv run python -m pytest

compose-up:
	docker compose up --build -d

compose-down:
	docker compose down
