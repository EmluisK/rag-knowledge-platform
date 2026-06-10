from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from database import (
 delete_ingest_run,
 ensure_schema,
 get_ingest_run,
 list_ingest_runs,
)
from generate import GenerationService
from ingest import IngestPipeline
from minio_store import MinIOStore
from models import (
 DocumentRunResponse,
 HealthResponse,
 IngestRequest,
 IngestResult,
 QueryRequest,
 QueryResponse,
)
from retrieve import RetrievalService

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── Lazy singletons ───────────────────────────────────────────
_pipeline: IngestPipeline | None = None
_retrieval: RetrievalService | None = None
_generation: GenerationService | None = None

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
 global _pipeline, _retrieval, _generation
 logger.info("startup_begin")
 ensure_schema(settings)
 _pipeline = IngestPipeline(settings)
 _retrieval = RetrievalService(settings)
 _generation = GenerationService(settings)
 logger.info("startup_complete")
 yield
 logger.info("shutdown")

app = FastAPI(
 title="Cloudflare Docs RAG API",
 description="RAG system over Cloudflare help articles",
 version="1.0.0",
 lifespan=lifespan,
)

app.add_middleware(
 CORSMiddleware,
 allow_origins=["*"],
 allow_methods=["*"],
 allow_headers=["*"],
)

# ── Health ────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
def health():
 services: dict[str, str] = {}

 # PostgreSQL
 try:
 from database import get_conn
 with get_conn(settings) as conn:
 conn.cursor().execute("SELECT 1")
 services["postgres"] = "ok"
 except Exception as exc:
 services["postgres"] = f"error: {exc}"

 # MinIO
 try:
 MinIOStore(settings).list_raw_documents()
 services["minio"] = "ok"
 except Exception as exc:
 services["minio"] = f"error: {exc}"

 # ChromaDB
 try:
 import httpx
 r = httpx.get(f"http://{settings.chroma_host}:{settings.chroma_port}/api/v1/heartbeat", timeout=3)
 services["chromadb"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
 except Exception as exc:
 services["chromadb"] = f"error: {exc}"

 # Ollama
 try:
 import httpx
 r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3)
 services["ollama"] = "ok" if r.status_code == 200 else "unavailable"
 except Exception:
 services["ollama"] = "unavailable (start with: ollama serve)"

 overall = "ok" if all("error" not in v for v in services.values()) else "degraded"
 return HealthResponse(status=overall, services=services, timestamp=datetime.now(timezone.utc))

# ── Ingestion ─────────────────────────────────────────────────

@app.post("/ingest", response_model=IngestResult)
def ingest_single(req: IngestRequest):
 try:
 return _pipeline.run_document(req.object_name)
 except Exception as exc:
 raise HTTPException(status_code=500, detail=str(exc))

@app.post("/ingest/all", response_model=list[IngestResult])
def ingest_all():
 from database import get_ingested_object_names
 store = MinIOStore(settings)
 all_docs = store.list_raw_documents()
 already_done = get_ingested_object_names(settings)
 pending = [d for d in all_docs if d not in already_done]

 results = []
 for obj in pending:
 try:
 results.append(_pipeline.run_document(obj))
 except Exception as exc:
 logger.error("batch_ingest_item_failed", obj=obj, error=str(exc))
 return results

# ── Query ─────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
 t0 = time.time()
 chunks = _retrieval.search(req.question, top_k=req.top_k)
 if not chunks:
 raise HTTPException(status_code=404, detail="No relevant documents found. Ingest documents first.")

 context = _retrieval.format_context(chunks)
 sources = _retrieval.format_sources(chunks)
 source_names = list({c.object_name for c in chunks})

 gen = _generation.answer(req.question, context, source_names)

 return QueryResponse(
 question=req.question,
 answer=gen.answer,
 sources=sources,
 model=gen.model,
 ollama_available=gen.ollama_available,
 elapsed_ms=int((time.time() - t0) * 1000),
 )

# ── Documents ─────────────────────────────────────────────────

@app.get("/documents", response_model=list[DocumentRunResponse])
def list_documents():
 return list_ingest_runs(settings)

@app.get("/documents/{doc_id}", response_model=DocumentRunResponse)
def get_document(doc_id: int):
 row = get_ingest_run(settings, doc_id)
 if not row:
 raise HTTPException(status_code=404, detail="Not found")
 return row

@app.delete("/documents/{doc_id}")
def delete_document(doc_id: int):
 ok = delete_ingest_run(settings, doc_id)
 if not ok:
 raise HTTPException(status_code=404, detail="Not found")
 return {"deleted": doc_id}
