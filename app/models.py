from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ── Request models ────────────────────────────────────────────

class IngestRequest(BaseModel):
 object_name: str = Field(..., description="MinIO object path, e.g. raw/doc.md")

class QueryRequest(BaseModel):
 question: str = Field(..., min_length=3, description="Natural language question")
 top_k: int = Field(5, ge=1, le=20)

# ── Response models ───────────────────────────────────────────

class ChunkMetadata(BaseModel):
 index: int
 char_start: int
 text: str

class IngestResult(BaseModel):
 doc_id: str
 object_name: str
 chunk_count: int
 elapsed_ms: int
 status: str = "success"

class RetrievedChunk(BaseModel):
 chunk_id: str
 object_name: str
 chunk_text: str
 relevance_score: float
 chunk_index: int

class GenerationResult(BaseModel):
 answer: str
 model: str
 prompt_tokens: int | None = None
 ollama_available: bool = True

class QueryResponse(BaseModel):
 question: str
 answer: str
 sources: list[dict[str, Any]]
 model: str
 ollama_available: bool
 elapsed_ms: int

class HealthResponse(BaseModel):
 status: str
 services: dict[str, str]
 timestamp: datetime

class DocumentRunResponse(BaseModel):
 id: int
 run_id: str
 object_name: str
 status: str
 chunk_count: int | None
 elapsed_ms: int | None
 error_msg: str | None
 created_at: datetime
 updated_at: datetime
