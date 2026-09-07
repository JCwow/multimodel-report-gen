"""MCP server exposing sandboxed meeting, internal-API, and AWS tools.

Transport: stdio (Cursor / Claude Agent SDK) or importable in-process for tests.
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

from mcp.server.mcpserver import MCPServer

from app.sandbox import SandboxError
from app.tools import (
    analyze_meeting_files as analyze_meeting_files_impl,
    analyze_slides as analyze_slides_impl,
    estimate_aws_cost as estimate_aws_cost_impl,
    format_error,
    list_meeting_assets as list_meeting_assets_impl,
    lookup_employee as lookup_employee_impl,
    query_historical_meetings as query_historical_meetings_impl,
    query_internal_api as query_internal_api_impl,
    synthesize_report as synthesize_report_impl,
    transcribe_audio as transcribe_audio_impl,
)

mcp = MCPServer("meetings")


@mcp.tool()
async def transcribe_audio(audio_path: str) -> str:
    """Transcribe a meeting audio file that already sits inside the sandbox."""
    try:
        return await transcribe_audio_impl(audio_path)
    except Exception as exc:
        return format_error(exc)


@mcp.tool()
async def analyze_slides(image_paths: list[str]) -> str:
    """Extract key data and text from sandboxed slide / whiteboard images."""
    try:
        return await analyze_slides_impl(image_paths)
    except Exception as exc:
        return format_error(exc)


@mcp.tool()
async def synthesize_report(transcript: str, image_insights: str = "") -> str:
    """Write a structured Markdown meeting report from transcript + slide insights."""
    try:
        return await synthesize_report_impl(transcript, image_insights)
    except Exception as exc:
        return format_error(exc)


@mcp.tool()
async def analyze_meeting_files(audio_path: str, image_paths: list[str] | None = None) -> str:
    """Analyze sandboxed meeting audio and slides, then return a Markdown report."""
    try:
        return await analyze_meeting_files_impl(audio_path, image_paths or [])
    except Exception as exc:
        return format_error(exc)


@mcp.tool()
async def query_historical_meetings(query: str, limit: int = 3) -> str:
    """Search indexed historical meeting reports in Qdrant (RAG)."""
    try:
        capped = max(1, min(int(limit), 10))
        return query_historical_meetings_impl(query, capped)
    except Exception as exc:
        return format_error(exc)


@mcp.tool()
async def lookup_employee(query: str) -> str:
    """Look up an employee in the internal HR directory."""
    try:
        return lookup_employee_impl(query)
    except Exception as exc:
        return format_error(exc)


@mcp.tool()
async def query_internal_api(resource: str, query: str) -> str:
    """Call the allowlisted internal API. resource must be employees, calendar, or health."""
    try:
        return query_internal_api_impl(resource, query)
    except (SandboxError, Exception) as exc:
        return format_error(exc)


@mcp.tool()
async def list_meeting_assets(prefix: str = "meetings/") -> str:
    """List meeting objects under the IAM-allowlisted S3 prefix (or local fixtures)."""
    try:
        return list_meeting_assets_impl(prefix)
    except Exception as exc:
        return format_error(exc)


@mcp.tool()
async def estimate_aws_cost(
    vcpu: float = 0.5,
    memory_gb: float = 1.0,
    hours_per_month: float = 730.0,
    bedrock_input_tokens: int = 2_000_000,
    bedrock_output_tokens: int = 400_000,
    model: str = "sonnet",
) -> str:
    """Estimate monthly AWS Fargate + Amazon Bedrock cost for this agent."""
    try:
        return estimate_aws_cost_impl(
            vcpu=vcpu,
            memory_gb=memory_gb,
            hours_per_month=hours_per_month,
            bedrock_input_tokens=bedrock_input_tokens,
            bedrock_output_tokens=bedrock_output_tokens,
            model=model,
        )
    except Exception as exc:
        return format_error(exc)


if __name__ == "__main__":
    mcp.run(transport="stdio")
