"""Runtime configuration for the agent, sandbox, MCP, and AWS adapters."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SANDBOX_ROOT = Path(os.getenv("SANDBOX_ROOT", ROOT / "sandbox_workspace")).resolve()
TOOL_TIMEOUT_SEC = float(os.getenv("TOOL_TIMEOUT_SEC", "120"))
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", str(25 * 1024 * 1024)))

AGENT_BACKEND = os.getenv("AGENT_BACKEND", "auto").strip().lower()
AGENT_MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "12"))
AGENT_MAX_BUDGET_USD = float(os.getenv("AGENT_MAX_BUDGET_USD", "0.50"))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "sdk").strip().lower()

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
AWS_MEETING_BUCKET = os.getenv("AWS_MEETING_BUCKET", "")
AWS_MEETING_PREFIX = os.getenv("AWS_MEETING_PREFIX", "meetings/")
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "").rstrip("/")

CLAUDE_CODE_USE_BEDROCK = os.getenv("CLAUDE_CODE_USE_BEDROCK", "").strip() in {
    "1",
    "true",
    "True",
    "yes",
}


def has_anthropic_credentials() -> bool:
    if CLAUDE_CODE_USE_BEDROCK:
        return True
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY"))
