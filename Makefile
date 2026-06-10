.PHONY: help up down restart logs shell setup scrape scrape-dry seed ingest ingest-direct query query-test health validate clean install

# ── Config ────────────────────────────────────────────────────
API_URL ?= http://localhost:8100
AIRFLOW_URL ?= http://localhost:8180
SERVICE ?= rag-api

# Auto-detect python and use python -m pip (avoids pip/install binary conflicts)
PYTHON := $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null)
PIP := $(PYTHON) -m pip

help: ## Show all targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf " \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo " Python → $(PYTHON)"
	@echo " Pip → $(PIP)"

install: ## Install script dependencies locally
	@if ! $(PYTHON) -m pip --version > /dev/null 2>&1; then \
		echo "pip not found, installing via get-pip.py..."; \
		curl -sS https://bootstrap.pypa.io/get-pip.py | $(PYTHON); \
	fi
	$(PYTHON) -m pip install -r requirements.txt

# ── Docker ────────────────────────────────────────────────────

up: ## Start all services
	@cp -n .env.example .env 2>/dev/null || true
	docker compose up -d --build
	@echo ""
	@echo "Services starting..."
	@echo " RAG API → http://localhost:8100/docs"
	@echo " MinIO → http://localhost:9101 (minioadmin/minioadmin)"
	@echo " Airflow → http://localhost:8180 (admin/admin)"
	@echo " ChromaDB → http://localhost:8200"
	@echo ""
	@echo "Wait ~60s for all services to be healthy, then: make setup"

down: ## Stop all services
	docker compose down

restart: ## Restart services
	docker compose restart

logs: ## Tail logs (SERVICE=name to filter)
	docker compose logs -f $(SERVICE)

shell: ## Bash into rag-api container
	docker compose exec rag-api bash

# ── Setup ─────────────────────────────────────────────────────

setup: ## Create DB schema and ChromaDB collections
	@echo "Creating PostgreSQL schema..."
	docker compose exec -T postgres psql -U raguser -d ragdb -c \
		"CREATE TABLE IF NOT EXISTS ingest_runs (id SERIAL PRIMARY KEY, run_id UUID DEFAULT gen_random_uuid(), object_name TEXT NOT NULL, status TEXT DEFAULT 'pending', chunk_count INTEGER, elapsed_ms INTEGER, error_msg TEXT, created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW());"
	docker compose exec -T postgres psql -U raguser -d ragdb -c \
		"CREATE TABLE IF NOT EXISTS document_chunks (id SERIAL PRIMARY KEY, run_id UUID NOT NULL, object_name TEXT NOT NULL, chunk_index INTEGER NOT NULL, char_start INTEGER NOT NULL, chunk_text TEXT NOT NULL, chroma_id TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW());"
	@echo " Schema ready"
	@echo " ChromaDB collection will auto-create on first ingest"

# ── Data ──────────────────────────────────────────────────────

scrape: ## Scrape Cloudflare docs into MinIO (--max 50 by default)
	$(PYTHON) -m ensurepip --upgrade 2>/dev/null || true
	$(PYTHON) -m pip install -q httpx boto3 structlog python-dotenv
	$(PYTHON) scripts/scrape_cloudflare.py --max 50

scrape-dry: ## Preview what will be scraped (no upload)
	$(PYTHON) scripts/scrape_cloudflare.py --max 50 --dry-run

seed: ## Generate 30 synthetic test documents in MinIO
	$(PYTHON) -m ensurepip --upgrade 2>/dev/null || true
	$(PYTHON) -m pip install -q boto3 structlog python-dotenv
	$(PYTHON) scripts/document_seeder.py --count 30

# ── Airflow ───────────────────────────────────────────────────

ingest: ## Trigger the Airflow ingestion DAG
	@echo "Triggering Airflow DAG: rag_ingestion_pipeline"
	docker compose exec airflow-webserver airflow dags trigger rag_ingestion_pipeline
	@echo ""
	@echo "Monitor at: http://localhost:8180/dags/rag_ingestion_pipeline"

ingest-direct: ## Ingest all raw docs directly via API (skip Airflow)
	curl -s -X POST $(API_URL)/ingest/all | $(PYTHON) -m json.tool

# ── Query ─────────────────────────────────────────────────────

query: ## Launch interactive query CLI
	$(PYTHON) -m ensurepip --upgrade 2>/dev/null || true
	$(PYTHON) -m pip install -q httpx rich python-dotenv
	RAG_API_URL=$(API_URL) $(PYTHON) scripts/query_cli.py

query-test: ## Quick one-shot query test
	curl -s -X POST $(API_URL)/query \
		-H 'Content-Type: application/json' \
		-d '{"question": "How do I deploy a Worker?", "top_k": 3}' \
		| $(PYTHON) -m json.tool

health: ## Check API health
	curl -s $(API_URL)/health | $(PYTHON) -m json.tool

# ── Validation ────────────────────────────────────────────────

validate: ## Run Great Expectations validation suite
	$(PYTHON) -m ensurepip --upgrade 2>/dev/null || true
	$(PYTHON) -m pip install -q great-expectations pandas psycopg2-binary structlog python-dotenv
	$(PYTHON) scripts/validate_documents.py --verbose

# ── Cleanup ───────────────────────────────────────────────────

clean: ## Remove all Docker volumes and data
	@read -p "This will delete ALL data. Continue? [y/N] " ans; \
	if [ "$$ans" = "y" ]; then \
		docker compose down -v --remove-orphans; \
		echo " Cleaned up"; \
	else \
		echo "Aborted."; \
	fi
