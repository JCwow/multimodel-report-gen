"""Adapters for internal DB, internal HTTP APIs, and AWS services.

Live endpoints are used when env vars are set; otherwise deterministic fixtures
stand in so evals and local demos stay offline-safe.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import (
    AWS_MEETING_BUCKET,
    AWS_MEETING_PREFIX,
    AWS_REGION,
    INTERNAL_API_BASE_URL,
)
from app.sandbox import SandboxError

EMPLOYEES = [
    {
        "id": "E001",
        "name": "林佳穎",
        "role": "北區業務主管",
        "email": "chia-ying.lin@internal.example",
        "team": "sales",
    },
    {
        "id": "E002",
        "name": "陳志明",
        "role": "營運經理",
        "email": "chih-ming.chen@internal.example",
        "team": "ops",
    },
    {
        "id": "E003",
        "name": "王雅婷",
        "role": "財務分析師",
        "email": "ya-ting.wang@internal.example",
        "team": "finance",
    },
    {
        "id": "E004",
        "name": "李國豪",
        "role": "IT 平台負責人",
        "email": "kuo-hao.lee@internal.example",
        "team": "platform",
    },
]

CALENDAR_EVENTS = [
    {
        "id": "CAL-204",
        "title": "Q2 北區營運檢討",
        "owner": "林佳穎",
        "date": "2026-06-12",
        "action_items_open": 3,
    },
    {
        "id": "CAL-218",
        "title": "門市擴點 dig-in",
        "owner": "陳志明",
        "date": "2026-07-03",
        "action_items_open": 1,
    },
]

# Approximate public list prices used for planning (USD, us-east-1).
FARGATE_VCPU_HOUR = 0.04048
FARGATE_GB_HOUR = 0.004445
BEDROCK_SONNET_INPUT_PER_1M = 3.00
BEDROCK_SONNET_OUTPUT_PER_1M = 15.00
BEDROCK_HAIKU_INPUT_PER_1M = 0.80
BEDROCK_HAIKU_OUTPUT_PER_1M = 4.00


def lookup_employee(query: str) -> list[dict[str, Any]]:
    needle = (query or "").strip().lower()
    if not needle:
        return []
    hits = []
    for row in EMPLOYEES:
        blob = " ".join(str(v) for v in row.values()).lower()
        if needle in blob:
            hits.append(row)
    return hits


def query_internal_api(resource: str, query: str) -> dict[str, Any]:
    """Query a mock (or real) internal REST API with an allowlisted resource."""
    allowed = {"employees", "calendar", "health"}
    if resource not in allowed:
        raise SandboxError(f"internal API resource not allowlisted: {resource}")

    if INTERNAL_API_BASE_URL:
        url = f"{INTERNAL_API_BASE_URL}/{resource}"
        with httpx.Client(timeout=10.0, trust_env=False) as client:
            response = client.get(url, params={"q": query})
            response.raise_for_status()
            return response.json()

    if resource == "employees":
        return {"source": "fixture", "results": lookup_employee(query)}
    if resource == "calendar":
        needle = (query or "").lower()
        results = [
            event
            for event in CALENDAR_EVENTS
            if needle in json.dumps(event, ensure_ascii=False).lower()
        ]
        return {"source": "fixture", "results": results}
    return {"source": "fixture", "status": "ok"}


def _s3_prefix_allowed(key_or_prefix: str) -> str:
    prefix = AWS_MEETING_PREFIX if AWS_MEETING_PREFIX.endswith("/") else AWS_MEETING_PREFIX + "/"
    cleaned = (key_or_prefix or prefix).lstrip("/")
    if cleaned.startswith(prefix) or prefix.startswith(cleaned):
        if ".." in cleaned or cleaned.startswith("/"):
            raise SandboxError("invalid S3 key")
        return cleaned
    raise SandboxError(
        f"S3 prefix not allowed: {key_or_prefix!r} (must be under {prefix!r})"
    )


def list_meeting_assets(prefix: str = "") -> dict[str, Any]:
    """List meeting objects in the allowlisted S3 prefix, or return fixtures."""
    safe_prefix = _s3_prefix_allowed(prefix or AWS_MEETING_PREFIX)
    if AWS_MEETING_BUCKET:
        import boto3

        client = boto3.client("s3", region_name=AWS_REGION)
        response = client.list_objects_v2(
            Bucket=AWS_MEETING_BUCKET,
            Prefix=safe_prefix,
            MaxKeys=20,
        )
        keys = [item["Key"] for item in response.get("Contents", [])]
        return {
            "source": "aws",
            "bucket": AWS_MEETING_BUCKET,
            "prefix": safe_prefix,
            "keys": keys,
        }

    return {
        "source": "fixture",
        "bucket": AWS_MEETING_BUCKET or "meeting-insights-demo",
        "prefix": safe_prefix,
        "keys": [
            f"{safe_prefix}2026-06-12/q2-review.mp3",
            f"{safe_prefix}2026-06-12/slides.png",
        ],
    }


def estimate_aws_cost(
    vcpu: float = 0.5,
    memory_gb: float = 1.0,
    hours_per_month: float = 730.0,
    bedrock_input_tokens: int = 2_000_000,
    bedrock_output_tokens: int = 400_000,
    model: str = "sonnet",
) -> dict[str, Any]:
    """Estimate Fargate + Bedrock monthly cost for capacity planning."""
    if vcpu <= 0 or vcpu > 16 or memory_gb <= 0 or memory_gb > 32:
        raise SandboxError("vcpu/memory out of allowed planning range")
    if hours_per_month < 0 or hours_per_month > 744:
        raise SandboxError("hours_per_month out of range")
    if bedrock_input_tokens < 0 or bedrock_output_tokens < 0:
        raise SandboxError("token counts must be >= 0")
    if bedrock_input_tokens > 50_000_000 or bedrock_output_tokens > 50_000_000:
        raise SandboxError("token counts exceed planning cap")

    fargate = (vcpu * FARGATE_VCPU_HOUR + memory_gb * FARGATE_GB_HOUR) * hours_per_month
    if model == "haiku":
        in_rate, out_rate = BEDROCK_HAIKU_INPUT_PER_1M, BEDROCK_HAIKU_OUTPUT_PER_1M
    else:
        in_rate, out_rate = BEDROCK_SONNET_INPUT_PER_1M, BEDROCK_SONNET_OUTPUT_PER_1M
        model = "sonnet"

    bedrock = (
        bedrock_input_tokens / 1_000_000 * in_rate
        + bedrock_output_tokens / 1_000_000 * out_rate
    )
    total = round(fargate + bedrock, 2)
    return {
        "region": AWS_REGION,
        "model": model,
        "fargate_usd": round(fargate, 2),
        "bedrock_usd": round(bedrock, 2),
        "total_usd": total,
        "notes": [
            "Fargate prices are on-demand us-east-1 approximations.",
            "Graviton (ARM64) typically cuts Fargate compute ~20%.",
            "Cap live runs with AGENT_MAX_BUDGET_USD and AGENT_MAX_TURNS.",
        ],
    }
