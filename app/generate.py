from __future__ import annotations

import httpx
import structlog

from config import Settings
from models import GenerationResult

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are a helpful assistant that answers questions about Cloudflare products
and documentation. Use ONLY the provided context to answer. If the context doesn't contain
the answer, say so clearly. Always cite the source documents you used."""

class GenerationService:
 def __init__(self, config: Settings) -> None:
 self._config = config
 self._base_url = config.ollama_base_url
 self._model = config.ollama_model

 def _is_available(self) -> bool:
 try:
 resp = httpx.get(f"{self._base_url}/api/tags", timeout=3.0)
 return resp.status_code == 200
 except Exception:
 return False

 def answer(
 self,
 question: str,
 context: str,
 sources_cited: list[str],
 ) -> GenerationResult:
 if not self._is_available():
 logger.warning("ollama_unavailable")
 return GenerationResult(
 answer=(
 " Ollama is not running. Start it with `ollama serve` then pull the model.\n\n"
 f"Retrieved context (top chunks):\n\n{context[:1000]}..."
 ),
 model=self._model,
 ollama_available=False,
 )

 prompt = (
 f"{SYSTEM_PROMPT}\n\n"
 f"Context:\n{context}\n\n"
 f"Sources: {', '.join(sources_cited)}\n\n"
 f"Question: {question}\n\nAnswer:"
 )

 try:
 resp = httpx.post(
 f"{self._base_url}/api/generate",
 json={"model": self._model, "prompt": prompt, "stream": False},
 timeout=120.0,
 )
 resp.raise_for_status()
 data = resp.json()
 return GenerationResult(
 answer=data.get("response", "").strip(),
 model=self._model,
 prompt_tokens=data.get("prompt_eval_count"),
 ollama_available=True,
 )
 except Exception as exc:
 logger.error("ollama_generate_failed", error=str(exc))
 return GenerationResult(
 answer=f"Generation failed: {exc}\n\nContext:\n{context[:800]}",
 model=self._model,
 ollama_available=False,
 )
