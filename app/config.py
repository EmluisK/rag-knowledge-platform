from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

class Settings:
 # MinIO
 minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "localhost:9100")
 minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
 minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")
 minio_bucket: str = os.getenv("MINIO_BUCKET", "rag-documents")

 # PostgreSQL
 postgres_user: str = os.getenv("POSTGRES_USER", "raguser")
 postgres_password: str = os.getenv("POSTGRES_PASSWORD", "ragpassword")
 postgres_db: str = os.getenv("POSTGRES_DB", "ragdb")
 postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
 postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))

 @property
 def postgres_dsn(self) -> str:
 return (
 f"postgresql://{self.postgres_user}:{self.postgres_password}"
 f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
 )

 # ChromaDB
 chroma_host: str = os.getenv("CHROMA_HOST", "localhost")
 chroma_port: int = int(os.getenv("CHROMA_PORT", "8200"))

 # Ollama
 ollama_host: str = os.getenv("OLLAMA_HOST", "localhost")
 ollama_port: int = int(os.getenv("OLLAMA_PORT", "11434"))
 ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

 @property
 def ollama_base_url(self) -> str:
 return f"http://{self.ollama_host}:{self.ollama_port}"

 # Embedding
 embedding_model: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
 chunk_size: int = int(os.getenv("CHUNK_SIZE", "512"))
 chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "64"))
 top_k: int = int(os.getenv("TOP_K", "5"))

 # ChromaDB collection name
 chroma_collection: str = "cloudflare_docs"

@lru_cache
def get_settings() -> Settings:
 return Settings()
