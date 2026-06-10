"""
Airflow DAG: rag_ingestion_pipeline

4 tasks:
 1. list_pending_documents - find raw/ docs not yet ingested
 2. validate_documents - basic GE-style checks on pending list
 3. ingest_documents - call RAG API /ingest for each
 4. log_summary - report counts
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

API_URL = os.getenv("RAG_API_URL", "http://rag-api:8000")

default_args = {
 "owner": "rag-team",
 "retries": 2,
 "retry_delay": timedelta(minutes=1),
 "email_on_failure": False,
}

# ── Task functions ────────────────────────────────────────────

def list_pending_documents(**context):
 """Find raw/ docs that haven't been successfully ingested yet."""
 import httpx

 # Get all raw docs from MinIO via API (list_raw_documents exposed through health)
 # We call /ingest/all listing logic via a dedicated endpoint instead
 resp = httpx.get(f"{API_URL}/documents", timeout=30)
 resp.raise_for_status()
 ingested_objects = {doc["object_name"] for doc in resp.json() if doc["status"] == "success"}

 # List raw docs from MinIO — we call the API helper
 import boto3, json
 minio_endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
 access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
 secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
 bucket = os.getenv("MINIO_BUCKET", "rag-documents")

 s3 = boto3.client(
 "s3",
 endpoint_url=f"http://{minio_endpoint}",
 aws_access_key_id=access_key,
 aws_secret_access_key=secret_key,
 region_name="us-east-1",
 )

 paginator = s3.get_paginator("list_objects_v2")
 raw_docs = []
 for page in paginator.paginate(Bucket=bucket, Prefix="raw/"):
 for obj in page.get("Contents", []):
 key = obj["Key"]
 if key not in ingested_objects:
 raw_docs.append(key)

 print(f"Found {len(raw_docs)} pending documents")
 context["ti"].xcom_push(key="pending_docs", value=raw_docs)
 return len(raw_docs)

def validate_documents(**context):
 """Basic validation on pending documents before ingestion."""
 pending = context["ti"].xcom_pull(task_ids="list_pending_documents", key="pending_docs") or []

 if not pending:
 print("No pending documents to validate")
 context["ti"].xcom_push(key="validated_docs", value=[])
 return 0

 import boto3
 minio_endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
 s3 = boto3.client(
 "s3",
 endpoint_url=f"http://{minio_endpoint}",
 aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
 aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
 region_name="us-east-1",
 )
 bucket = os.getenv("MINIO_BUCKET", "rag-documents")

 validated = []
 rejected = []
 for key in pending:
 try:
 meta = s3.head_object(Bucket=bucket, Key=key)
 size = meta["ContentLength"]
 if size < 10:
 print(f" REJECT (too small): {key} ({size} bytes)")
 rejected.append(key)
 elif size > 10 * 1024 * 1024: # 10MB
 print(f" REJECT (too large): {key} ({size} bytes)")
 rejected.append(key)
 else:
 validated.append(key)
 except Exception as exc:
 print(f" REJECT (head failed): {key} — {exc}")
 rejected.append(key)

 print(f"Validated {len(validated)}, rejected {len(rejected)}")
 context["ti"].xcom_push(key="validated_docs", value=validated)
 context["ti"].xcom_push(key="rejected_docs", value=rejected)
 return len(validated)

def ingest_documents(**context):
 """Ingest each validated document via the RAG API."""
 import httpx

 validated = context["ti"].xcom_pull(task_ids="validate_documents", key="validated_docs") or []
 if not validated:
 print("Nothing to ingest")
 context["ti"].xcom_push(key="ingest_results", value={"success": 0, "failed": 0})
 return

 success, failed = 0, 0
 for obj in validated:
 try:
 resp = httpx.post(
 f"{API_URL}/ingest",
 json={"object_name": obj},
 timeout=120,
 )
 if resp.status_code == 200:
 data = resp.json()
 print(f" {obj} ({data.get('chunk_count', '?')} chunks, {data.get('elapsed_ms', '?')}ms)")
 success += 1
 else:
 print(f" {obj} — HTTP {resp.status_code}: {resp.text[:200]}")
 failed += 1
 except Exception as exc:
 print(f" {obj} — {exc}")
 failed += 1

 context["ti"].xcom_push(key="ingest_results", value={"success": success, "failed": failed})

def log_summary(**context):
 """Log final ingestion summary."""
 results = context["ti"].xcom_pull(task_ids="ingest_documents", key="ingest_results") or {}
 pending = context["ti"].xcom_pull(task_ids="list_pending_documents", key="pending_docs") or []
 rejected = context["ti"].xcom_pull(task_ids="validate_documents", key="rejected_docs") or []

 print("=" * 50)
 print(" RAG Ingestion Pipeline Summary")
 print("=" * 50)
 print(f" Pending found : {len(pending)}")
 print(f" Rejected : {len(rejected)}")
 print(f" Ingested OK : {results.get('success', 0)}")
 print(f" Ingested FAILED : {results.get('failed', 0)}")
 print("=" * 50)

# ── DAG definition ────────────────────────────────────────────

with DAG(
 dag_id="rag_ingestion_pipeline",
 default_args=default_args,
 description="Ingest Cloudflare docs from MinIO into ChromaDB",
 schedule=None, # manual trigger
 start_date=datetime(2025, 1, 1),
 catchup=False,
 tags=["rag", "cloudflare"],
) as dag:

 t1 = PythonOperator(
 task_id="list_pending_documents",
 python_callable=list_pending_documents,
 )

 t2 = PythonOperator(
 task_id="validate_documents",
 python_callable=validate_documents,
 )

 t3 = PythonOperator(
 task_id="ingest_documents",
 python_callable=ingest_documents,
 )

 t4 = PythonOperator(
 task_id="log_summary",
 python_callable=log_summary,
 )

 t1 >> t2 >> t3 >> t4
