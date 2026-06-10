from __future__ import annotations

import re
from dataclasses import dataclass

import structlog
from sentence_transformers import SentenceTransformer

from config import Settings

logger = structlog.get_logger(__name__)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

@dataclass
class ChunkMetadata:
 index: int
 char_start: int
 text: str

class EmbeddingService:
 def __init__(self, config: Settings) -> None:
 self._config = config
 logger.info("embedding_model_loading", model=config.embedding_model)
 self._model = SentenceTransformer(config.embedding_model)
 logger.info("embedding_model_ready")

 def embed_text(self, text: str) -> list[float]:
 return self._model.encode(text, normalize_embeddings=True).tolist()

 def embed_batch(self, texts: list[str]) -> list[list[float]]:
 return self._model.encode(texts, normalize_embeddings=True, batch_size=32).tolist()

 def chunk_text(
 self,
 text: str,
 chunk_size: int | None = None,
 overlap: int | None = None,
 ) -> list[ChunkMetadata]:
 chunk_size = chunk_size or self._config.chunk_size
 overlap = overlap or self._config.chunk_overlap

 # Split into sentences first
 sentences = _SENTENCE_END.split(text.strip())
 chunks: list[ChunkMetadata] = []
 current: list[str] = []
 current_len = 0
 char_cursor = 0
 chunk_start = 0

 for sentence in sentences:
 sentence = sentence.strip()
 if not sentence:
 continue

 if current_len + len(sentence) + 1 > chunk_size and current:
 chunk_text = " ".join(current)
 chunks.append(ChunkMetadata(
 index=len(chunks),
 char_start=chunk_start,
 text=chunk_text,
 ))
 # Overlap: keep last sentences until overlap budget
 overlap_buf: list[str] = []
 overlap_len = 0
 for s in reversed(current):
 if overlap_len + len(s) > overlap:
 break
 overlap_buf.insert(0, s)
 overlap_len += len(s) + 1
 current = overlap_buf
 current_len = overlap_len
 chunk_start = char_cursor

 current.append(sentence)
 current_len += len(sentence) + 1
 char_cursor += len(sentence) + 1

 if current:
 chunks.append(ChunkMetadata(
 index=len(chunks),
 char_start=chunk_start,
 text=" ".join(current),
 ))

 # Fallback: if no chunks were created, character-split
 if not chunks:
 for i in range(0, len(text), chunk_size - overlap):
 chunks.append(ChunkMetadata(
 index=len(chunks),
 char_start=i,
 text=text[i : i + chunk_size],
 ))

 logger.info("chunking_done", total_chunks=len(chunks))
 return chunks
