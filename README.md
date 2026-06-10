# RAG Knowledge Platform

A local, end-to-end Retrieval-Augmented Generation (RAG) system built from scratch over Cloudflare's official developer documentation. The system lets you ask natural language questions and get accurate, source-cited answers drawn directly from Cloudflare's help articles — no hallucination of API names, no outdated guesses, just answers grounded in the real docs.

Built without LangChain or any RAG framework. Every component — scraping, chunking, embedding, retrieval, generation, orchestration — is wired together manually so the full pipeline is visible and understandable.

---

## Purpose

Cloudflare has hundreds of documentation pages across products like Workers, Pages, R2, D1, KV, DNS, SSL, and WAF. Finding the right answer often means searching across multiple pages or reading through long reference docs. This system solves that by:

- Scraping Cloudflare's documentation and storing it locally
- Breaking articles into semantically meaningful chunks and embedding them as vectors
- Accepting a natural language question, finding the most relevant chunks via similarity search, and passing them to a local LLM to generate a grounded answer
- Citing which documents the answer came from so you can verify or read further

The practical use case is a developer assistant: instead of searching `developers.cloudflare.com`, you ask a question and get a direct answer with sources.

---

## How It Works

### 1. Scraping

Cloudflare officially supports LLM ingestion. Their docs site exposes two mechanisms:

- `https://developers.cloudflare.com/llms.txt` — a full index of all documentation pages, designed specifically for AI tools
- Any page returns clean Markdown when requested with an `Accept: text/markdown` HTTP header

The scraper (`scripts/scrape_cloudflare.py`) fetches the index, filters to the product sections you care about (Workers, Pages, R2, KV, D1, DNS, SSL, WAF, Cache by default), then downloads each page as Markdown. No HTML parsing, no browser automation, no robots.txt violations. The raw Markdown files are uploaded to MinIO under the `raw/` prefix.

### 2. Object Storage (MinIO)

MinIO is an S3-compatible object store that runs locally in Docker. Documents move through three prefixes:

- `raw/` — freshly scraped, not yet processed
- `processed/` — successfully ingested into the vector store
- `embeddings/` — JSON metadata files storing chunk counts and run info

Using an object store rather than a local filesystem means the scraping step and the ingestion step are decoupled. You can re-run ingestion without re-scraping, and the Airflow DAG can inspect what is pending vs. done.

### 3. Ingestion Pipeline (Airflow DAG)

Apache Airflow orchestrates ingestion as a four-task DAG (`rag_ingestion_pipeline`):

1. `list_pending_documents` — queries MinIO for files in `raw/` that have no successful ingest run in PostgreSQL
2. `validate_documents` — checks each file exists, is not empty, and is under 10MB before passing it forward
3. `ingest_documents` — calls the RAG API `POST /ingest` for each validated document, which runs the full ingest pipeline
4. `log_summary` — reports counts of ingested, skipped, and failed documents

Tasks pass data between each other using Airflow's XCom system. The DAG is triggered manually (`make ingest`) but can be scheduled.

### 4. Chunking

Each document is split into chunks before embedding. The chunker (`app/embed.py`) works sentence-first: it splits on sentence boundaries (`.`, `!`, `?`) and accumulates sentences until the chunk reaches the configured size (default 512 characters). When a chunk is full, it saves a configurable overlap (default 64 characters) of the previous chunk's tail into the next chunk, so context is not lost at boundaries. If the text has no sentence punctuation, it falls back to character-based splitting.

This approach preserves meaning better than a naive character split, since a chunk will not cut mid-sentence.

### 5. Embedding

Each chunk is embedded using `all-MiniLM-L6-v2`, a sentence-transformer model that produces 384-dimensional vectors. It runs locally (no external API calls). Embeddings are normalized so cosine similarity can be computed as a dot product, which ChromaDB handles efficiently.

The model is small enough to run on CPU in reasonable time and produces good semantic representations for technical documentation text.

### 6. Vector Store (ChromaDB)

ChromaDB stores the chunk embeddings alongside metadata (source document, chunk index, character offset, run ID). At query time, the question is embedded with the same model and ChromaDB performs an approximate nearest-neighbor search using cosine similarity, returning the top-K most relevant chunks.

ChromaDB runs as a Docker service with a persistent volume so the index survives restarts.

### 7. Metadata Store (PostgreSQL)

PostgreSQL stores two tables:

- `ingest_runs` — one row per document ingestion attempt, tracking status, chunk count, elapsed time, and any error message
- `document_chunks` — one row per chunk, recording the text, source document, position, and ChromaDB ID

This gives a full audit trail of what has been ingested, when, and how many chunks it produced. It also powers the deduplication logic so the same document is not ingested twice.

### 8. Generation (Ollama)

Once relevant chunks are retrieved, they are formatted into a context block and passed to a locally running LLM via Ollama. The default model is `llama3.2:3b`, which runs on CPU and fits in ~4GB of RAM. The system prompt instructs the model to answer only from the provided context and to say so clearly if the context does not contain the answer.

Ollama runs on the host machine (not in Docker) and is reached from the API container via `host.docker.internal`. If Ollama is not running, the API degrades gracefully and returns the retrieved chunks directly so you still get the source material.

### 9. REST API (FastAPI)

The RAG API (`app/main.py`) exposes the ingestion and query functionality over HTTP. It is the single entry point for all pipeline operations and is what the Airflow DAG, the CLI, and direct `curl` calls all talk to.

### 10. Data Validation (Great Expectations)

After ingestion, `scripts/validate_documents.py` runs a suite of expectations against the `document_chunks` table: column presence, null checks, text length bounds, object name format, and chunk index range. This catches malformed ingestion runs before they pollute the vector store with bad data.

---

## Technology Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| REST API | FastAPI | Fast, async, auto-generates OpenAPI docs |
| LLM | Ollama + llama3.2:3b | Runs locally, no API costs |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Small, fast, good quality for technical text |
| Vector store | ChromaDB | Purpose-built for embeddings, simple to run locally |
| Metadata store | PostgreSQL | Reliable, queryable audit trail |
| Object store | MinIO | S3-compatible, runs locally, decouples scrape from ingest |
| Orchestration | Apache Airflow | Industry-standard, XCom for task data passing |
| Data validation | Great Expectations | Declarative quality checks on ingested data |
| Data source | Cloudflare developers.cloudflare.com | Official LLM-friendly markdown endpoint |
| Containerisation | Docker + Docker Compose | All services in one `docker compose up` |

---

## Project Structure

```
rag-knowledge-platform/
  app/                        FastAPI application
    main.py                   API routes (health, ingest, query, documents)
    config.py                 Settings loaded from environment
    ingest.py                 Full ingestion pipeline (download, chunk, embed, store)
    retrieve.py               Vector search and context formatting
    generate.py               Ollama generation with graceful fallback
    embed.py                  Sentence-aware chunker + embedding service
    database.py               PostgreSQL helpers (runs, chunks, audit)
    minio_store.py            MinIO upload/download/list wrapper
    models.py                 Pydantic request and response models
    requirements-app.txt      Python dependencies for the API container
  dags/
    rag_ingestion_dag.py      Airflow DAG with 4 tasks
  scripts/
    scrape_cloudflare.py      Cloudflare docs scraper
    document_seeder.py        Synthetic document generator for testing
    query_cli.py              Interactive terminal query interface
    validate_documents.py     Great Expectations validation runner
  expectations/
    document_suite.json       GE expectation suite definition
  postgres/
    init.sql                  Schema for ingest_runs and document_chunks
  ollama/
    pull_model.sh             Helper script to pull llama3.2:3b
  docker-compose.yml          All 8 services
  Makefile                    Developer commands
  requirements.txt            Dependencies for running scripts locally
  .env.example                Environment variable template
```

---

## Services and Ports

| Service | Local Port | Purpose |
|---------|-----------|---------|
| rag-api | 8100 | FastAPI REST API + OpenAPI docs at /docs |
| chromadb | 8200 | Vector store HTTP API |
| minio | 9100 | MinIO S3 API |
| minio console | 9101 | MinIO browser UI |
| postgres | 5450 | PostgreSQL (raguser / ragpassword) |
| airflow-webserver | 8180 | Airflow DAG management UI |
| ollama | 11434 | LLM inference (runs on host, not Docker) |

---

## Running the System

### Prerequisites

- Docker and Docker Compose installed
- Python 3.11 (not 3.12+, packages do not have wheels yet)
- [Ollama](https://ollama.com) installed on your machine

### Step 1 — Set up the LLM

Install Ollama from https://ollama.com, then pull the model and start the server:

```bash
ollama pull llama3.2:3b
ollama serve
```

Keep `ollama serve` running in a separate terminal for the duration. The model is about 2.5GB.

### Step 2 — Configure environment

```bash
cp .env.example .env
```

If you will run scripts (scraping, querying) from outside Docker, edit `.env` and change the hostnames to `localhost`:

```
MINIO_ENDPOINT=localhost:9100
POSTGRES_HOST=localhost
CHROMA_HOST=localhost
```

Leave them as `minio`, `postgres`, `chromadb` if you only use the API container and Airflow.

### Step 3 — Start all services

```bash
docker compose up -d --build
```

Wait about 60 seconds for all services to become healthy. Check status with:

```bash
docker compose ps
```

### Step 4 — Set up the database schema

```bash
make setup
```

This creates the `ingest_runs` and `document_chunks` tables in PostgreSQL.

### Step 5 — Install local Python dependencies

For running scripts outside Docker you need a virtual environment:

```bash
sudo apt install python3.11 python3.11-venv -y      # Debian/Ubuntu
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 6 — Scrape Cloudflare docs

```bash
source .venv/bin/activate
python scripts/scrape_cloudflare.py --max 50
```

This fetches up to 50 pages from Cloudflare's docs (Workers, Pages, R2, KV, D1, DNS, SSL, WAF, Cache) and uploads them as Markdown to MinIO. Increase `--max` for broader coverage. You can preview what will be scraped without uploading:

```bash
python scripts/scrape_cloudflare.py --max 50 --dry-run
```

Browse uploaded files at http://localhost:9101 (minioadmin / minioadmin).

### Step 7 — Ingest documents

Trigger the Airflow DAG:

```bash
make ingest
```

Monitor the run at http://localhost:8180 (admin / admin). The DAG validates pending documents then calls the API to chunk, embed, and store each one. This takes a few minutes depending on how many documents you scraped.

To skip Airflow and ingest directly via the API:

```bash
make ingest-direct
```

### Step 8 — Query

Launch the interactive CLI:

```bash
source .venv/bin/activate
make query
```

Or send a direct API request:

```bash
curl -X POST http://localhost:8100/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "How do I deploy a Cloudflare Worker?", "top_k": 5}'
```

The full OpenAPI interface is at http://localhost:8100/docs.

### Step 9 — Validate data quality (optional)

```bash
source .venv/bin/activate
make validate
```

Runs the Great Expectations suite against the ingested chunks and reports pass/fail for each expectation.

---

## All Makefile Commands

| Command | Description |
|---------|-------------|
| `make help` | List all commands |
| `make up` | Start all Docker services |
| `make down` | Stop all services |
| `make restart` | Restart services |
| `make logs` | Tail logs (use SERVICE=name to filter) |
| `make shell` | Open a shell in the rag-api container |
| `make setup` | Create PostgreSQL schema |
| `make install` | Install local Python dependencies via pip |
| `make scrape` | Scrape Cloudflare docs into MinIO |
| `make scrape-dry` | Preview scrape targets without uploading |
| `make seed` | Upload 30 synthetic test documents |
| `make ingest` | Trigger Airflow ingestion DAG |
| `make ingest-direct` | Ingest all pending docs via API directly |
| `make query` | Interactive query CLI |
| `make query-test` | One-shot test query |
| `make health` | Check API health and service status |
| `make validate` | Run Great Expectations data validation |
| `make clean` | Delete all Docker volumes and data |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check for all services |
| POST | /ingest | Ingest a single document by object name |
| POST | /ingest/all | Batch ingest all pending raw documents |
| POST | /query | Ask a question, get an answer with sources |
| GET | /documents | List all ingestion runs |
| GET | /documents/{id} | Get details of a specific run |
| DELETE | /documents/{id} | Delete a run and its chunk records |

---

## Troubleshooting

**Services not starting:**
```bash
docker compose ps
docker compose logs -f
```

**Cannot connect to MinIO from scripts:**
Make sure `.env` has `MINIO_ENDPOINT=localhost:9100` when running scripts outside Docker.

**Ollama not responding:**
```bash
ollama serve          # start in a separate terminal
ollama list           # confirm llama3.2:3b is pulled
```

**ChromaDB collection is empty after ingest:**
```bash
make ingest-direct    # bypass Airflow for a quick test
curl http://localhost:8200/api/v1/heartbeat
```

**PostgreSQL schema missing:**
```bash
make setup
```
