from __future__ import annotations

import time
import uuid
from io import BytesIO

import chromadb
import structlog

from config import Settings
from database import (
 create_ingest_run,
 insert_chunks,
 update_ingest_run,
)
from embed import EmbeddingService
from minio_store import MinIOStore
from models import IngestResult

logger = structlog.get_logger(__name__)

def _extract_text(content: bytes, object_name: str) -> str:
 """Extract plain text from bytes. Supports .md, .txt, .pdf."""
 if object_name.endswith(".pdf"):
 from pypdf import PdfReader
 reader = PdfReader(BytesIO(content))
 return "\n".join(p.extract_text() or "" for p in reader.pages)
 # markdown / plain text
 return content.decode("utf-8", errors="replace")

class IngestPipeline:
 def __init__(self, config: Settings) -> None:
 self._config = config
 self._minio = MinIOStore(config)
 self._embed = EmbeddingService(config)
 self._chroma = chromadb.HttpClient(
 host=config.chroma_host, port=config.chroma_port
 )

 def _get_collection(self):
 return self._chroma.get_or_create_collection(
 name=self._config.chroma_collection,
 metadata={"hnsw:space": "cosine"},
 )

 def run_document(self, object_name: str) -> IngestResult:
 t0 = time.time()
 run_id = create_ingest_run(self._config, object_name)
 log = logger.bind(object_name=object_name, run_id=run_id)

 try:
 # 1. Download
 log.info("ingest_download")
 content = self._minio.download_document(object_name)

 # 2. Extract text
 log.info("ingest_extract")
 text = _extract_text(content, object_name)
 if not text.strip():
 raise ValueError("Empty document after extraction")

 # 3. Chunk
 log.info("ingest_chunk")
 raw_chunks = self._embed.chunk_text(text)

 # 4. Embed (batch)
 log.info("ingest_embed", num_chunks=len(raw_chunks))
 vectors = self._embed.embed_batch([c.text for c in raw_chunks])

 # 5. Upsert to ChromaDB
 log.info("ingest_chroma_upsert")
 collection = self._get_collection()
 chunk_records: list[dict] = []
 ids, embeddings, documents, metadatas = [], [], [], []

 for chunk, vector in zip(raw_chunks, vectors):
 chroma_id = f"{run_id}_{chunk.index}"
 ids.append(chroma_id)
 embeddings.append(vector)
 documents.append(chunk.text)
 metadatas.append({
 "object_name": object_name,
 "chunk_index": chunk.index,
 "char_start": chunk.char_start,
 "run_id": run_id,
 })
 chunk_records.append({
 "index": chunk.index,
 "char_start": chunk.char_start,
 "text": chunk.text,
 "chroma_id": chroma_id,
 })

 collection.upsert(
 ids=ids,
 embeddings=embeddings,
 documents=documents,
 metadatas=metadatas,
 )

 # 6. Insert chunks to PostgreSQL
 log.info("ingest_postgres_insert")
 insert_chunks(self._config, run_id, object_name, chunk_records)

 # 7. Mark processed in MinIO
 self._minio.mark_processed(object_name)

 # 8. Store metadata
 elapsed_ms = int((time.time() - t0) * 1000)
 self._minio.upload_metadata(object_name, {
 "run_id": run_id,
 "object_name": object_name,
 "chunk_count": len(chunk_records),
 "elapsed_ms": elapsed_ms,
 })

 # 9. Update run record
 update_ingest_run(
 self._config,
 run_id,
 status="success",
 chunk_count=len(chunk_records),
 elapsed_ms=elapsed_ms,
 )

 log.info("ingest_complete", chunks=len(chunk_records), ms=elapsed_ms)
 return IngestResult(
 doc_id=run_id,
 object_name=object_name,
 chunk_count=len(chunk_records),
 elapsed_ms=elapsed_ms,
 )

 except Exception as exc:
 elapsed_ms = int((time.time() - t0) * 1000)
 update_ingest_run(
 self._config,
 run_id,
 status="failed",
 elapsed_ms=elapsed_ms,
 error_msg=str(exc),
 )
 log.error("ingest_failed", error=str(exc))
 raise
