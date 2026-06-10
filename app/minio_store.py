from __future__ import annotations

import json
from io import BytesIO

import boto3
import structlog
from botocore.exceptions import ClientError

from config import Settings

logger = structlog.get_logger(__name__)

class MinIOStore:
 def __init__(self, config: Settings) -> None:
 self._config = config
 self._client = boto3.client(
 "s3",
 endpoint_url=f"http://{config.minio_endpoint}",
 aws_access_key_id=config.minio_access_key,
 aws_secret_access_key=config.minio_secret_key,
 region_name="us-east-1",
 )
 self._bucket = config.minio_bucket
 self._ensure_bucket()

 def _ensure_bucket(self) -> None:
 try:
 self._client.head_bucket(Bucket=self._bucket)
 except ClientError:
 self._client.create_bucket(Bucket=self._bucket)
 logger.info("minio_bucket_created", bucket=self._bucket)

 def upload_document(self, local_path: str, object_name: str) -> str:
 """Upload a local file to raw/ prefix. Returns S3 URI."""
 key = f"raw/{object_name}" if not object_name.startswith("raw/") else object_name
 try:
 self._client.upload_file(local_path, self._bucket, key)
 uri = f"s3://{self._bucket}/{key}"
 logger.info("minio_upload_ok", uri=uri)
 return uri
 except Exception as exc:
 logger.error("minio_upload_failed", path=local_path, error=str(exc))
 raise

 def upload_bytes(self, data: bytes, object_name: str) -> str:
 """Upload raw bytes (e.g. scraped content)."""
 key = f"raw/{object_name}" if not object_name.startswith("raw/") else object_name
 try:
 self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
 uri = f"s3://{self._bucket}/{key}"
 logger.info("minio_upload_bytes_ok", key=key)
 return uri
 except Exception as exc:
 logger.error("minio_upload_bytes_failed", key=key, error=str(exc))
 raise

 def download_document(self, object_name: str) -> bytes:
 """Fetch document content from MinIO."""
 try:
 resp = self._client.get_object(Bucket=self._bucket, Key=object_name)
 return resp["Body"].read()
 except Exception as exc:
 logger.error("minio_download_failed", key=object_name, error=str(exc))
 raise

 def list_raw_documents(self) -> list[str]:
 """List all objects in raw/ prefix."""
 try:
 paginator = self._client.get_paginator("list_objects_v2")
 keys = []
 for page in paginator.paginate(Bucket=self._bucket, Prefix="raw/"):
 for obj in page.get("Contents", []):
 keys.append(obj["Key"])
 return keys
 except Exception as exc:
 logger.error("minio_list_failed", error=str(exc))
 return []

 def mark_processed(self, object_name: str) -> bool:
 """Copy from raw/ to processed/ prefix."""
 dest = object_name.replace("raw/", "processed/", 1)
 try:
 self._client.copy_object(
 Bucket=self._bucket,
 CopySource={"Bucket": self._bucket, "Key": object_name},
 Key=dest,
 )
 logger.info("minio_marked_processed", src=object_name, dest=dest)
 return True
 except Exception as exc:
 logger.error("minio_mark_processed_failed", error=str(exc))
 return False

 def upload_metadata(self, object_name: str, metadata: dict) -> bool:
 """Store JSON metadata to embeddings/ prefix."""
 key = "embeddings/" + object_name.split("/", 1)[-1] + ".json"
 try:
 body = json.dumps(metadata, default=str).encode()
 self._client.put_object(Bucket=self._bucket, Key=key, Body=body)
 return True
 except Exception as exc:
 logger.error("minio_metadata_failed", error=str(exc))
 return False

 def document_exists(self, object_name: str) -> bool:
 """Check if object exists in raw/."""
 try:
 self._client.head_object(Bucket=self._bucket, Key=object_name)
 return True
 except ClientError:
 return False
