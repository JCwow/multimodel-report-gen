"""Shared tool implementations used by the MCP server and Claude Agent SDK."""

from __future__ import annotations

import asyncio
import json

from app import internal_systems
from app.sandbox import SandboxError, relative_to_sandbox, resolve_sandbox_path, run_with_timeout


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


async def transcribe_audio(audio_path: str) -> str:
    path = resolve_sandbox_path(audio_path, must_exist=True)
    from app.agent import speech_to_text_node

    audio_bytes = path.read_bytes()
    result = await run_with_timeout(
        asyncio.to_thread(speech_to_text_node, {"audio_bytes": audio_bytes}),
        name="transcribe_audio",
    )
    return result.get("transcript") or ""


async def analyze_slides(image_paths: list[str]) -> str:
    if not image_paths:
        return "（未提供簡報圖片）"
    resolved = [resolve_sandbox_path(p, must_exist=True) for p in image_paths]
    from app.agent import vision_analysis_node

    image_bytes_list = [path.read_bytes() for path in resolved]
    result = await run_with_timeout(
        asyncio.to_thread(
            vision_analysis_node,
            {"image_bytes_list": image_bytes_list},
        ),
        name="analyze_slides",
    )
    descriptions = result.get("image_descriptions") or []
    return "\n\n".join(descriptions) if descriptions else "（圖片無可讀資訊）"


async def synthesize_report(transcript: str, image_insights: str = "") -> str:
    from app.agent import synthesize_insights_node

    state = {
        "transcript": transcript or "",
        "image_descriptions": [image_insights] if image_insights else [],
    }
    result = await run_with_timeout(
        asyncio.to_thread(synthesize_insights_node, state),
        name="synthesize_report",
    )
    return result.get("final_report") or ""


async def analyze_meeting_files(audio_path: str, image_paths: list[str] | None = None) -> str:
    """Full multimodal pipeline, still executed inside the sandbox."""
    audio = resolve_sandbox_path(audio_path, must_exist=True)
    images = [resolve_sandbox_path(p, must_exist=True) for p in (image_paths or [])]
    from app.agent import multimodal_agent

    inputs = {
        "audio_bytes": audio.read_bytes(),
        "image_bytes_list": [path.read_bytes() for path in images],
        "transcript": "",
        "image_descriptions": [],
        "final_report": "",
    }
    result = await run_with_timeout(
        multimodal_agent.ainvoke(inputs),
        name="analyze_meeting_files",
    )
    return result.get("final_report", "無法生成報告")


def query_historical_meetings(query: str, limit: int = 3) -> str:
    from app.vector_store import search_reports

    results = search_reports(query=query, limit=limit)
    if not results:
        return "未找到相關歷史會議記錄（或向量庫未連線）。"
    formatted = []
    for idx, doc in enumerate(results, 1):
        formatted.append(f"### 歷史記錄 {idx}\n{doc['content']}\n")
    return "\n---\n".join(formatted)


def lookup_employee(query: str) -> str:
    hits = internal_systems.lookup_employee(query)
    if not hits:
        return f"內部目錄沒有符合「{query}」的人員。"
    return _json(hits)


def query_internal_api(resource: str, query: str) -> str:
    return _json(internal_systems.query_internal_api(resource, query))


def list_meeting_assets(prefix: str = "") -> str:
    return _json(internal_systems.list_meeting_assets(prefix))


def estimate_aws_cost(
    vcpu: float = 0.5,
    memory_gb: float = 1.0,
    hours_per_month: float = 730.0,
    bedrock_input_tokens: int = 2_000_000,
    bedrock_output_tokens: int = 400_000,
    model: str = "sonnet",
) -> str:
    return _json(
        internal_systems.estimate_aws_cost(
            vcpu=vcpu,
            memory_gb=memory_gb,
            hours_per_month=hours_per_month,
            bedrock_input_tokens=bedrock_input_tokens,
            bedrock_output_tokens=bedrock_output_tokens,
            model=model,
        )
    )


def format_error(exc: Exception) -> str:
    if isinstance(exc, SandboxError):
        return f"SANDBOX_DENIED: {exc}"
    return f"TOOL_ERROR: {exc}"


def sdk_result(text: str, *, is_error: bool = False) -> dict:
    payload = {"content": [{"type": "text", "text": text}]}
    if is_error:
        payload["isError"] = True
    return payload


def describe_sandbox_file(path: str) -> str:
    resolved = resolve_sandbox_path(path, must_exist=True)
    return _json(
        {
            "path": relative_to_sandbox(resolved),
            "bytes": resolved.stat().st_size,
            "suffix": resolved.suffix,
        }
    )
