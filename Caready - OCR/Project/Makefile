# Linux/macOS/CI equivalent of tasks.ps1.
# The primary development environment is Windows - see tasks.ps1 there.

.DEFAULT_GOAL := help
.PHONY: help up down reset logs seed migrate revision check test test-api test-seed test-web lint format gen-key

API_DIR := services/api
WEB_DIR := apps/web

help:
	@echo "Caready"
	@echo "  up          Build and start the full stack (seeds automatically)"
	@echo "  down        Stop the stack, keep volumes"
	@echo "  reset       Stop and DELETE all volumes (destroys the database)"
	@echo "  logs        Tail logs"
	@echo "  seed        Seed synthetic data           (ARGS='--reset --no-images')"
	@echo "  migrate     Apply migrations"
	@echo "  revision    Autogenerate a migration      (M='what changed')"
	@echo "  check       Verify schema matches ORM metadata"
	@echo "  test        Run every test suite"
	@echo "  lint        Ruff check + web lint"
	@echo "  format      Ruff format"
	@echo "  gen-key     Generate a PII encryption key"

up:
	@test -f .env || cp .env.example .env
	docker compose up --build -d
	@echo ""
	@echo "  Web         http://localhost:3000"
	@echo "  API docs    http://localhost:8000/docs"
	@echo "  MinIO       http://localhost:9001"
	@echo "  MLflow      http://localhost:5500"
	@echo ""
	@echo "  Demo login: inspektur@caready.local / caready-dev-2026"
	@echo ""
	@echo "  ALL DATA IS SYNTHETIC AND HAS NO REAL-WORLD VALIDITY."

down:
	docker compose down

reset:
	@echo "This DELETES the database, object storage, and MLflow volumes."
	@read -p 'Type "yes" to continue: ' answer; [ "$$answer" = "yes" ] || exit 1
	docker compose down -v

logs:
	docker compose logs -f

seed:
	docker compose run --rm seed python /app/seed/run_seed.py $(ARGS)

migrate:
	cd $(API_DIR) && alembic upgrade head

revision:
	cd $(API_DIR) && alembic revision --autogenerate -m "$(M)"

check:
	cd $(API_DIR) && alembic check

test-api:
	cd $(API_DIR) && pytest

test-seed:
	pytest seed/tests -v

test-web:
	cd $(WEB_DIR) && npm test

test: test-api test-seed test-web

lint:
	ruff check services packages seed
	cd $(WEB_DIR) && npm run lint

format:
	ruff format services packages seed

gen-key:
	@python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
	@echo "Prepend to PII_ENCRYPTION_KEYS. Keep the old key until re-encryption completes."
