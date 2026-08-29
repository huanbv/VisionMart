# =============================================================
# VisionMart - Developer Makefile
# =============================================================

SHELL := /bin/bash
COMPOSE := docker compose

.DEFAULT_GOAL := help

# ---------- Meta ----------
.PHONY: help
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------- Lifecycle ----------
.PHONY: setup
setup: ## Initial project setup (env + pre-commit)
	@cp -n .env.example .env || true
	@pre-commit install || true
	@echo "Setup complete."

.PHONY: build
build: ## Build all docker images
	$(COMPOSE) build

.PHONY: up
up: ## Start all services in background
	$(COMPOSE) up -d

.PHONY: down
down: ## Stop and remove all services
	$(COMPOSE) down

.PHONY: restart
restart: down up ## Restart all services

.PHONY: ps
ps: ## List running services
	$(COMPOSE) ps

.PHONY: logs
logs: ## Tail logs for all services
	$(COMPOSE) logs -f --tail=200

# ---------- Shells ----------
.PHONY: backend-shell
backend-shell: ## Open a shell inside the backend container
	$(COMPOSE) exec backend bash

.PHONY: frontend-shell
frontend-shell: ## Open a shell inside the frontend container
	$(COMPOSE) exec frontend sh

.PHONY: ai-shell
ai-shell: ## Open a shell inside the ai-engine container
	$(COMPOSE) exec ai-engine bash

# ---------- Quality ----------
.PHONY: lint
lint: ## Run linters across the monorepo
	@echo "==> Python (ruff)"
	@cd backend && ruff check . || true
	@cd ai-engine && ruff check . || true
	@echo "==> Frontend (eslint)"
	@cd frontend && npm run lint || true

.PHONY: format
format: ## Auto-format the monorepo
	@echo "==> Python (black + isort)"
	@cd backend && black . && isort . || true
	@cd ai-engine && black . && isort . || true
	@echo "==> Frontend (prettier)"
	@cd frontend && npm run format || true

.PHONY: test
test: ## Run all tests
	@cd backend && pytest -q || true
	@cd ai-engine && pytest -q || true
	@cd frontend && npm test --silent || true

# ---------- Database ----------
.PHONY: db-migrate
db-migrate: ## Apply database migrations
	$(COMPOSE) exec backend alembic upgrade head

.PHONY: db-revision
db-revision: ## Create a new alembic revision (msg="...")
	$(COMPOSE) exec backend alembic revision --autogenerate -m "$(msg)"

# ---------- Cleanup ----------
.PHONY: clean
clean: ## Remove containers, volumes, and dangling images
	$(COMPOSE) down -v --remove-orphans
	docker image prune -f
