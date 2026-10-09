.DEFAULT_GOAL := help

PYTHON := $(shell which python3)
VENV ?= .venv
BIN := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin,$(dir $(PYTHON)))

.PHONY: help
help: ## Display this help message
	@echo ""
	@echo "Bulk Action Platform - Development Makefile"
	@echo "==========================================="
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""

.PHONY: venv
venv: ## Create Python virtual environment
	$(PYTHON) -m venv $(VENV)
	@echo "Virtualenv created at $(VENV). Run 'source $(VENV)/bin/activate' to use."

.PHONY: install
install: ## Install python dependencies
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt

.PHONY: migrate
migrate: ## Apply database migrations
	$(BIN)/python manage.py migrate

.PHONY: makemigrations
makemigrations: ## Generate new database migrations
	$(BIN)/python manage.py makemigrations entities bulk_actions

.PHONY: server
server: ## Run Django development server on port 8000
	$(BIN)/python manage.py runserver 0.0.0.0:8000

.PHONY: superuser
superuser: ## Create default admin user (admin / admin123)
	$(BIN)/python manage.py create_admin

.PHONY: worker
worker: ## Start Celery worker with 4 concurrency
	$(BIN)/celery -A config worker --loglevel=INFO -c 4

.PHONY: beat
beat: ## Start Celery Beat scheduler
	$(BIN)/celery -A config beat --loglevel=INFO

.PHONY: worker-beat
worker-beat: ## Start combined Celery worker and beat (development only)
	$(BIN)/celery -A config worker --beat --loglevel=INFO -c 2

.PHONY: shell
shell: ## Open Django interactive shell
	$(BIN)/python manage.py shell

.PHONY: test
test: ## Run full test suite with pytest
	$(BIN)/pytest -v

.PHONY: test-fast
test-fast: ## Run pytest without verbose tracebacks
	$(BIN)/pytest -q

.PHONY: lint
lint: ## Run Ruff linter checks
	$(BIN)/ruff check .

.PHONY: format
format: ## Format code and auto-fix linter issues with Ruff
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

.PHONY: seed
seed: ## Seed database with 1,000 sample contacts
	$(BIN)/python manage.py seed_data --count=1000

.PHONY: seed-large
seed-large: ## Seed database with 10,000 sample contacts (for load testing)
	$(BIN)/python manage.py seed_data --count=10000

.PHONY: docker-up
docker-up: ## Start Postgres 17 and Redis containers via Docker Compose
	docker compose up -d

.PHONY: docker-down
docker-down: ## Stop Docker Compose containers
	docker compose down

.PHONY: db-dump
db-dump: ## Export PostgreSQL database dump to dump.sql
	docker exec -i postgres pg_dump -U postgres -d bulk_action_db > dump.sql

.PHONY: db-restore
db-restore: ## Restore PostgreSQL database from dump.sql
	docker exec -i postgres psql -U postgres -d bulk_action_db < dump.sql

.PHONY: clean
clean: ## Remove Python cache files and build artifacts
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
