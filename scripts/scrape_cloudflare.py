#!/usr/bin/env python3
"""
Cloudflare docs scraper.

Uses Cloudflare's official LLM-friendly endpoints:
 - https://developers.cloudflare.com/llms.txt (index of all pages)
 - Accept: text/markdown header to get clean Markdown from any page

Uploads scraped articles to MinIO raw/ prefix.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Add app/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
from config import get_settings
from minio_store import MinIOStore

logger = structlog.get_logger(__name__)

LLMS_INDEX_URL = "https://developers.cloudflare.com/llms.txt"
BASE_URL = "https://developers.cloudflare.com"

# Product sections to focus on (keeps scope manageable for a school project)
ALLOWED_PREFIXES = [
 "/workers/",
 "/pages/",
 "/r2/",
 "/kv/",
 "/d1/",
 "/dns/",
 "/ssl/",
 "/waf/",
 "/firewall/",
 "/cache/",
 "/speed/",
]

def fetch_index(max_urls: int) -> list[str]:
 """Fetch llms.txt and extract doc page URLs."""
 logger.info("fetching_llms_index", url=LLMS_INDEX_URL)
 resp = httpx.get(LLMS_INDEX_URL, timeout=30, follow_redirects=True)
 resp.raise_for_status()

 urls = []
 for line in resp.text.splitlines():
 line = line.strip()
 if not line or line.startswith("#"):
 continue
 # Lines look like: https://developers.cloudflare.com/workers/... or relative paths
 if line.startswith("http"):
 url = line
 elif line.startswith("/"):
 url = BASE_URL + line
 else:
 continue

 parsed = urlparse(url)
 path = parsed.path

 # Filter to allowed product sections
 if any(path.startswith(p) for p in ALLOWED_PREFIXES):
 urls.append(url)

 if len(urls) >= max_urls:
 break

 logger.info("index_urls_found", count=len(urls))
 return urls

def fetch_markdown(url: str) -> str | None:
 """Fetch a page as Markdown using Cloudflare's official header."""
 try:
 resp = httpx.get(
 url,
 headers={"Accept": "text/markdown"},
 timeout=20,
 follow_redirects=True,
 )
 if resp.status_code == 200 and resp.text.strip():
 return resp.text
 return None
 except Exception as exc:
 logger.warning("fetch_failed", url=url, error=str(exc))
 return None

def url_to_object_name(url: str) -> str:
 """Convert URL to a safe MinIO object name."""
 parsed = urlparse(url)
 # e.g. /workers/get-started/ -> workers__get-started.md
 slug = parsed.path.strip("/").replace("/", "__")
 if not slug:
 slug = hashlib.md5(url.encode()).hexdigest()[:8]
 return f"{slug}.md"

def main():
 parser = argparse.ArgumentParser(description="Scrape Cloudflare docs into MinIO")
 parser.add_argument("--max", type=int, default=50, help="Max pages to scrape")
 parser.add_argument("--delay", type=float, default=0.5, help="Delay between requests (s)")
 parser.add_argument("--dry-run", action="store_true", help="Print URLs only, don't upload")
 args = parser.parse_args()

 settings = get_settings()
 store = MinIOStore(settings) if not args.dry_run else None

 urls = fetch_index(args.max)
 if not urls:
 logger.error("no_urls_found")
 sys.exit(1)

 uploaded = 0
 skipped = 0
 failed = 0

 for i, url in enumerate(urls, 1):
 object_name = f"raw/{url_to_object_name(url)}"
 log = logger.bind(url=url, object_name=object_name, progress=f"{i}/{len(urls)}")

 if args.dry_run:
 print(f"[DRY RUN] {url} -> {object_name}")
 continue

 if store.document_exists(object_name):
 log.info("skip_already_exists")
 skipped += 1
 continue

 markdown = fetch_markdown(url)
 if not markdown:
 log.warning("skip_no_content")
 failed += 1
 continue

 # Prepend source URL as metadata comment
 content = f"<!-- source: {url} -->\n\n{markdown}"

 try:
 store.upload_bytes(content.encode("utf-8"), url_to_object_name(url))
 log.info("uploaded_ok", bytes=len(content))
 uploaded += 1
 except Exception as exc:
 log.error("upload_failed", error=str(exc))
 failed += 1

 time.sleep(args.delay)

 if not args.dry_run:
 logger.info(
 "scraping_complete",
 uploaded=uploaded,
 skipped=skipped,
 failed=failed,
 )
 print(f"\n Done: {uploaded} uploaded, {skipped} skipped, {failed} failed")
 print(f" Check MinIO console: http://localhost:9101")
 print(f" Now run: make ingest")

if __name__ == "__main__":
 main()
