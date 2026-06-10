-- Create airflow database
CREATE DATABASE airflow;

-- Connect to ragdb for RAG schema
\c ragdb;

CREATE TABLE IF NOT EXISTS ingest_runs (
 id SERIAL PRIMARY KEY,
 run_id UUID NOT NULL DEFAULT gen_random_uuid(),
 object_name TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',
 chunk_count INTEGER,
 elapsed_ms INTEGER,
 error_msg TEXT,
 created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
 updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_chunks (
 id SERIAL PRIMARY KEY,
 run_id UUID NOT NULL,
 object_name TEXT NOT NULL,
 chunk_index INTEGER NOT NULL,
 char_start INTEGER NOT NULL,
 chunk_text TEXT NOT NULL,
 chroma_id TEXT NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_run_id ON document_chunks(run_id);
CREATE INDEX IF NOT EXISTS idx_chunks_object_name ON document_chunks(object_name);
CREATE INDEX IF NOT EXISTS idx_runs_object_name ON ingest_runs(object_name);
CREATE INDEX IF NOT EXISTS idx_runs_status ON ingest_runs(status);
