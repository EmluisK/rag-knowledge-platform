#!/usr/bin/env python3
"""Generate synthetic Cloudflare-themed documents and upload to MinIO."""
from __future__ import annotations

import argparse
import random
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
from config import get_settings
from minio_store import MinIOStore

PIPELINES = ["workers-build", "pages-deploy", "r2-sync", "d1-migrate", "kv-refresh"]
SEVERITIES = ["P1", "P2", "P3"]
ROOT_CAUSES = [
 "memory limit exceeded in Workers runtime",
 "R2 bucket policy misconfiguration",
 "D1 read replica lag caused stale data",
 "KV write conflict during high concurrency",
 "Pages build cache invalidation failure",
]

INCIDENT_TEMPLATE = """# Incident Report {incident_id}

**Severity:** {severity}
**Pipeline:** {pipeline}
**MTTR:** {mttr} minutes

## Summary
An incident occurred in the {pipeline} pipeline with severity {severity}.

## Root Cause
{root_cause}

## Timeline
- 00:00 Alert triggered
- 00:05 On-call engineer paged
- 00:{detect:02d} Root cause identified
- 00:{resolve:02d} Fix deployed and verified

## Resolution
The issue was resolved by {resolution}.

## Prevention
To prevent recurrence: {prevention}
"""

DQ_TEMPLATE = """# Data Quality Report

**Pipeline:** {pipeline}
**Dataset:** {dataset}
**Total Rows:** {total_rows}
**Failures:** {failures}
**Expectation Type:** {expectation_type}

## Overview
Quality check for {dataset} in the {pipeline} pipeline.

## Results
- Pass rate: {pass_rate:.1f}%
- Failed rows: {failures} / {total_rows}
- Expectation violated: `{expectation_type}`

## Affected Columns
{columns}

## Recommended Action
{action}
"""

ADR_TEMPLATE = """# ADR-{num:03d}: {title}

**Status:** {status}
**Date:** 2025-0{month}-{day:02d}

## Context
{context}

## Decision
{decision}

## Consequences
**Positive:** {positive}
**Negative:** {negative}

## Alternatives Considered
{alternatives}
"""

def gen_incident(i: int) -> tuple[str, str]:
 detect = random.randint(5, 15)
 resolve = detect + random.randint(5, 30)
 content = INCIDENT_TEMPLATE.format(
 incident_id=f"INC-{2500 + i}",
 severity=random.choice(SEVERITIES),
 pipeline=random.choice(PIPELINES),
 mttr=resolve,
 root_cause=random.choice(ROOT_CAUSES),
 detect=detect,
 resolve=resolve,
 resolution=random.choice(["rolling back the deployment", "increasing memory limits", "patching the KV client"]),
 prevention=random.choice(["add canary deployments", "improve monitoring thresholds", "add load tests to CI"]),
 )
 return f"raw/incidents/incident_{i:03d}.md", content

def gen_dq_report(i: int) -> tuple[str, str]:
 total = random.randint(10000, 1000000)
 failures = random.randint(0, int(total * 0.05))
 content = DQ_TEMPLATE.format(
 pipeline=random.choice(PIPELINES),
 dataset=f"cloudflare_{random.choice(['logs', 'analytics', 'requests', 'dns_queries'])}_{i}",
 total_rows=total,
 failures=failures,
 expectation_type=random.choice([
 "expect_column_values_to_not_be_null",
 "expect_column_values_to_be_between",
 "expect_column_values_to_match_regex",
 ]),
 pass_rate=(total - failures) / total * 100,
 columns="\n".join(f"- {c}" for c in random.sample(["timestamp", "request_id", "status_code", "region", "latency_ms"], 3)),
 action=random.choice([
 "Investigate upstream data source",
 "Add null-check to ingestion pipeline",
 "Update regex pattern for new format",
 ]),
 )
 return f"raw/quality/dq_report_{i:03d}.md", content

ADR_TOPICS = [
 ("Use R2 for static asset storage", "We evaluated S3 vs R2 vs GCS for static assets.", "R2 with zero egress costs", "No transfer fees from Cloudflare edge.", "Vendor lock-in to Cloudflare ecosystem.", "S3 (higher egress), GCS (different pricing model)"),
 ("Adopt Workers for edge compute", "Latency-sensitive APIs need to run close to users.", "Deploy on Cloudflare Workers", "Sub-millisecond cold starts at edge.", "250ms CPU time limit per request.", "Lambda@Edge (complex), Fastly (higher cost)"),
 ("Use D1 as primary database for read-heavy workloads", "Need a globally replicated SQLite database.", "Cloudflare D1 with read replicas", "Automatic global replication.", "Still in beta, limited advanced SQL features.", "PlanetScale (MySQL), Neon (Postgres)"),
]

def gen_adr(i: int) -> tuple[str, str]:
 topic = ADR_TOPICS[i % len(ADR_TOPICS)]
 content = ADR_TEMPLATE.format(
 num=i + 1,
 title=topic[0],
 status=random.choice(["Accepted", "Proposed", "Deprecated"]),
 month=random.randint(1, 9),
 day=random.randint(1, 28),
 context=topic[1],
 decision=topic[2],
 positive=topic[3],
 negative=topic[4],
 alternatives=topic[5],
 )
 return f"raw/adrs/adr_{i:03d}.md", content

def main():
 parser = argparse.ArgumentParser(description="Seed synthetic documents")
 parser.add_argument("--count", type=int, default=30, help="Total docs (split evenly across 3 types)")
 args = parser.parse_args()

 settings = get_settings()
 store = MinIOStore(settings)

 n = args.count // 3
 docs = (
 [gen_incident(i) for i in range(n)]
 + [gen_dq_report(i) for i in range(n)]
 + [gen_adr(i) for i in range(n)]
 )

 for key, content in docs:
 obj_name = key.split("raw/", 1)[-1]
 store.upload_bytes(content.encode(), obj_name)
 print(f" {key}")

 print(f"\n Seeded {len(docs)} synthetic documents into MinIO")

if __name__ == "__main__":
 main()
