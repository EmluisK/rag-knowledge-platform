#!/usr/bin/env python3
"""Validate document_chunks table with Great Expectations."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import pandas as pd
import psycopg2
import psycopg2.extras
import structlog
from great_expectations.dataset import PandasDataset

from config import get_settings

logger = structlog.get_logger(__name__)

def load_chunks_df(settings) -> pd.DataFrame:
 conn = psycopg2.connect(settings.postgres_dsn)
 try:
 with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
 cur.execute("SELECT * FROM document_chunks LIMIT 10000")
 rows = cur.fetchall()
 return pd.DataFrame([dict(r) for r in rows])
 finally:
 conn.close()

def run_validation(verbose: bool = False) -> bool:
 settings = get_settings()

 try:
 df = load_chunks_df(settings)
 except Exception as exc:
 logger.error("db_load_failed", error=str(exc))
 print(f" Could not load data: {exc}")
 return False

 if df.empty:
 print(" No chunks found — ingest documents first.")
 return False

 dataset = PandasDataset(df)
 results = []

 def check(name: str, result: dict) -> bool:
 success = result["success"]
 status = "" if success else ""
 if verbose or not success:
 print(f" {status} {name}")
 if not success and verbose:
 print(f" {result.get('result', {})}")
 results.append(success)
 return success

 print("\n── Great Expectations: document_chunks ──────────────\n")

 check("table has rows", {"success": len(df) > 0})

 check("column count == 8", dataset.expect_table_column_count_to_equal(8))

 check(
 "columns match expected set",
 dataset.expect_table_columns_to_match_set(
 {"id", "run_id", "object_name", "chunk_index", "char_start", "chunk_text", "chroma_id", "created_at"}
 ),
 )

 for col in ("chunk_text", "object_name", "chroma_id", "run_id"):
 check(f"{col} not null", dataset.expect_column_values_to_not_be_null(col))

 check(
 "chunk_text length 10–2000",
 dataset.expect_column_value_lengths_to_be_between("chunk_text", min_value=10, max_value=2000),
 )

 check(
 "object_name matches raw/ or processed/",
 dataset.expect_column_values_to_match_regex("object_name", r"^(raw|processed)/"),
 )

 check(
 "chunk_index between 0–500",
 dataset.expect_column_values_to_be_between("chunk_index", min_value=0, max_value=500),
 )

 passed = sum(results)
 total = len(results)
 print(f"\n── Results: {passed}/{total} passed ─────────────────────\n")

 return passed == total

def main():
 parser = argparse.ArgumentParser(description="Validate RAG document chunks")
 parser.add_argument("--verbose", "-v", action="store_true")
 args = parser.parse_args()

 ok = run_validation(verbose=args.verbose)
 sys.exit(0 if ok else 1)

if __name__ == "__main__":
 main()
