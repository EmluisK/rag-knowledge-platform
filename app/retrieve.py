from __future__ import annotations

import chromadb
import structlog

from config import Settings
from embed import EmbeddingService
from models import RetrievedChunk

logger = structlog.get_logger(__name__)

class RetrievalService:
 def __init__(self, config: Settings) -> None:
 self._config = config
 self._embed = EmbeddingService(config)
 self._chroma = chromadb.HttpClient(
 host=config.chroma_host, port=config.chroma_port
 )

 def _collection(self):
 return self._chroma.get_or_create_collection(
 name=self._config.chroma_collection,
 metadata={"hnsw:space": "cosine"},
 )

 def search(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
 k = top_k or self._config.top_k
 query_vec = self._embed.embed_text(query)
 collection = self._collection()

 try:
 results = collection.query(
 query_embeddings=[query_vec],
 n_results=min(k, collection.count() or 1),
 include=["documents", "metadatas", "distances"],
 )
 except Exception as exc:
 logger.error("chroma_query_failed", error=str(exc))
 return []

 chunks: list[RetrievedChunk] = []
 for doc, meta, dist in zip(
 results["documents"][0],
 results["metadatas"][0],
 results["distances"][0],
 ):
 chunks.append(RetrievedChunk(
 chunk_id=meta.get("run_id", "unknown"),
 object_name=meta.get("object_name", "unknown"),
 chunk_text=doc,
 relevance_score=round(1.0 - dist, 4),
 chunk_index=int(meta.get("chunk_index", 0)),
 ))

 logger.info("retrieval_done", query=query[:60], hits=len(chunks))
 return chunks

 def format_context(self, chunks: list[RetrievedChunk]) -> str:
 parts = []
 for i, c in enumerate(chunks, 1):
 parts.append(f"[Source {i}: {c.object_name}]\n{c.chunk_text}")
 return "\n\n---\n\n".join(parts)

 def format_sources(self, chunks: list[RetrievedChunk]) -> list[dict]:
 return [
 {
 "object_name": c.object_name,
 "relevance_score": c.relevance_score,
 "chunk_index": c.chunk_index,
 "excerpt": c.chunk_text[:200] + "..." if len(c.chunk_text) > 200 else c.chunk_text,
 }
 for c in chunks
 ]
