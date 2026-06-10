from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras
import structlog

from config import Settings

logger = structlog.get_logger(__name__)

@contextmanager
def get_conn(settings: Settings) -> Generator[psycopg2.extensions.connection, None, None]:
 conn = psycopg2.connect(settings.postgres_dsn)
 try:
 yield conn
 conn.commit()
 except Exception:
 conn.rollback()
 raise
 finally:
 conn.close()

def ensure_schema(settings: Settings) -> None:
 """Create tables if they don't exist."""
 with get_conn(settings) as conn:
 with conn.cursor() as cur:
 cur.execute("""
 CREATE TABLE IF NOT EXISTS ingest_runs (
 id SERIAL PRIMARY KEY,
 run_id UUID NOT NULL DEFAULT gen_random_uuid(),
 object_name TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',
 chunk_count INTEGER,
 elapsed_ms INTEGER,
 error_msg TEXT,
 created_at TIMESTAMPTZ DEFAULT NOW(),
 updated_at TIMESTAMPTZ DEFAULT NOW()
 );

 CREATE TABLE IF NOT EXISTS document_chunks (
 id SERIAL PRIMARY KEY,
 run_id UUID NOT NULL,
 object_name TEXT NOT NULL,
 chunk_index INTEGER NOT NULL,
 char_start INTEGER NOT NULL,
 chunk_text TEXT NOT NULL,
 chroma_id TEXT NOT NULL,
 created_at TIMESTAMPTZ DEFAULT NOW()
 );

 CREATE INDEX IF NOT EXISTS idx_chunks_run_id ON document_chunks(run_id);
 CREATE INDEX IF NOT EXISTS idx_chunks_object_name ON document_chunks(object_name);
 CREATE INDEX IF NOT EXISTS idx_runs_object_name ON ingest_runs(object_name);
 CREATE INDEX IF NOT EXISTS idx_runs_status ON ingest_runs(status);
 """)
 logger.info("database_schema_ready")

def create_ingest_run(settings: Settings, object_name: str) -> str:
 run_id = str(uuid.uuid4())
 with get_conn(settings) as conn:
 with conn.cursor() as cur:
 cur.execute(
 """
 INSERT INTO ingest_runs (run_id, object_name, status)
 VALUES (%s, %s, 'processing')
 """,
 (run_id, object_name),
 )
 return run_id

def update_ingest_run(
 settings: Settings,
 run_id: str,
 status: str,
 chunk_count: int | None = None,
 elapsed_ms: int | None = None,
 error_msg: str | None = None,
) -> None:
 with get_conn(settings) as conn:
 with conn.cursor() as cur:
 cur.execute(
 """
 UPDATE ingest_runs
 SET status=%s, chunk_count=%s, elapsed_ms=%s, error_msg=%s, updated_at=NOW()
 WHERE run_id=%s
 """,
 (status, chunk_count, elapsed_ms, error_msg, run_id),
 )

def insert_chunks(
 settings: Settings,
 run_id: str,
 object_name: str,
 chunks: list[dict],
) -> None:
 with get_conn(settings) as conn:
 with conn.cursor() as cur:
 psycopg2.extras.execute_values(
 cur,
 """
 INSERT INTO document_chunks
 (run_id, object_name, chunk_index, char_start, chunk_text, chroma_id)
 VALUES %s
 """,
 [
 (run_id, object_name, c["index"], c["char_start"], c["text"], c["chroma_id"])
 for c in chunks
 ],
 )

def list_ingest_runs(settings: Settings) -> list[dict]:
 with get_conn(settings) as conn:
 with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
 cur.execute("SELECT * FROM ingest_runs ORDER BY created_at DESC LIMIT 100")
 return [dict(r) for r in cur.fetchall()]

def get_ingest_run(settings: Settings, run_id: int) -> dict | None:
 with get_conn(settings) as conn:
 with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
 cur.execute("SELECT * FROM ingest_runs WHERE id=%s", (run_id,))
 row = cur.fetchone()
 return dict(row) if row else None

def delete_ingest_run(settings: Settings, run_id: int) -> bool:
 with get_conn(settings) as conn:
 with conn.cursor() as cur:
 cur.execute("DELETE FROM document_chunks WHERE run_id IN (SELECT run_id FROM ingest_runs WHERE id=%s)", (run_id,))
 cur.execute("DELETE FROM ingest_runs WHERE id=%s", (run_id,))
 return cur.rowcount > 0

def get_ingested_object_names(settings: Settings) -> set[str]:
 with get_conn(settings) as conn:
 with conn.cursor() as cur:
 cur.execute("SELECT DISTINCT object_name FROM ingest_runs WHERE status='success'")
 return {row[0] for row in cur.fetchall()}
