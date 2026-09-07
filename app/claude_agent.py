"""Claude Agent SDK orchestrator: autonomous planning + MCP tool use.

Built-in Claude Code tools (Bash/Read/Write) are stripped. The model can only
call allowlisted MCP tools, which themselves go through app.sandbox.
"""

from __future__ import annotations

import inspect
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

from app.config import (
    AGENT_MAX_BUDGET_USD,
    AGENT_MAX_TURNS,
    AWS_REGION,
    MCP_TRANSPORT,
    ROOT,
    bedrock_requested,
    has_anthropic_credentials,
    use_bedrock,
)
from app.sandbox import sandbox_root
from app.tools import (
    analyze_meeting_files,
    analyze_slides,
    estimate_aws_cost,
    format_error,
    list_meeting_assets,
    lookup_employee,
    query_historical_meetings,
    query_internal_api,
    sdk_result,
    synthesize_report,
    transcribe_audio,
)

SYSTEM_PROMPT = """你是企業會議洞察 Agent。先規劃再執行，必要時多步呼叫工具。

規則：
1. 有語音就呼叫 transcribe_audio；有簡報圖就呼叫 analyze_slides。
2. 報告中的人名、負責人，用 lookup_employee 或 query_internal_api 對內部目錄。
3. 使用者提到歷史會議、上次決議、未完成事項時，呼叫 query_historical_meetings。
4. 被問到部署成本、Fargate、Bedrock 時，呼叫 estimate_aws_cost。
5. 需要會議檔案清單時，呼叫 list_meeting_assets（僅允許 meetings/ 前綴）。
6. 也可以直接呼叫 analyze_meeting_files 一次跑完整流水線。
7. 最後產出 Markdown 報告，必須包含：
   - 會議核心主題與目標
   - 簡報數據與逐字稿交叉對照
   - 關鍵決策與 Action Items（執行人 + 時程）
8. 禁止讀取沙箱外檔案、禁止猜測內部憑證、禁止要求 Bash/Read/Write。
"""

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "transcript": {"type": "string"},
        "image_insights": {"type": "array", "items": {"type": "string"}},
        "report": {"type": "string"},
        "tools_used": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["report"],
}

MCP_TOOL_NAMES = [
    "mcp__meetings__transcribe_audio",
    "mcp__meetings__analyze_slides",
    "mcp__meetings__synthesize_report",
    "mcp__meetings__analyze_meeting_files",
    "mcp__meetings__query_historical_meetings",
    "mcp__meetings__lookup_employee",
    "mcp__meetings__query_internal_api",
    "mcp__meetings__list_meeting_assets",
    "mcp__meetings__estimate_aws_cost",
]


def _wrap(fn: Callable):
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            signature = inspect.signature(fn)
            kwargs = {key: value for key, value in args.items() if key in signature.parameters}
            result = fn(**kwargs)
            if hasattr(result, "__await__"):
                result = await result
            return sdk_result(str(result))
        except Exception as exc:
            return sdk_result(format_error(exc), is_error=True)

    return handler


def build_sdk_mcp_server():
    from claude_agent_sdk import create_sdk_mcp_server, tool

    @tool("transcribe_audio", "Transcribe a sandboxed meeting audio file.", {"audio_path": str})
    async def transcribe_audio_tool(args):
        return await _wrap(transcribe_audio)(args)

    @tool(
        "analyze_slides",
        "Extract data and text from sandboxed slide images.",
        {"image_paths": list},
    )
    async def analyze_slides_tool(args):
        return await _wrap(analyze_slides)(args)

    @tool(
        "synthesize_report",
        "Write a structured meeting report from transcript and slide insights.",
        {"transcript": str},
    )
    async def synthesize_report_tool(args):
        return await _wrap(synthesize_report)(args)

    @tool(
        "analyze_meeting_files",
        "Run the full multimodal meeting pipeline on sandboxed files.",
        {"audio_path": str},
    )
    async def analyze_meeting_files_tool(args):
        image_paths = args.get("image_paths") or []
        try:
            text = await analyze_meeting_files(args["audio_path"], image_paths)
            return sdk_result(text)
        except Exception as exc:
            return sdk_result(format_error(exc), is_error=True)

    @tool(
        "query_historical_meetings",
        "Search indexed historical meeting reports (RAG).",
        {"query": str},
    )
    async def query_historical_meetings_tool(args):
        return await _wrap(query_historical_meetings)(args)

    @tool("lookup_employee", "Look up an employee in the internal directory.", {"query": str})
    async def lookup_employee_tool(args):
        return await _wrap(lookup_employee)(args)

    @tool(
        "query_internal_api",
        "Call the allowlisted internal API (employees|calendar|health).",
        {"resource": str, "query": str},
    )
    async def query_internal_api_tool(args):
        return await _wrap(query_internal_api)(args)

    @tool(
        "list_meeting_assets",
        "List meeting objects under the allowlisted S3 prefix.",
        {},
    )
    async def list_meeting_assets_tool(args):
        return await _wrap(list_meeting_assets)({"prefix": args.get("prefix", "")})

    @tool(
        "estimate_aws_cost",
        "Estimate monthly Fargate + Bedrock cost for this agent.",
        {},
    )
    async def estimate_aws_cost_tool(args):
        return await _wrap(estimate_aws_cost)(args)

    return create_sdk_mcp_server(
        name="meetings",
        version="1.0.0",
        tools=[
            transcribe_audio_tool,
            analyze_slides_tool,
            synthesize_report_tool,
            analyze_meeting_files_tool,
            query_historical_meetings_tool,
            lookup_employee_tool,
            query_internal_api_tool,
            list_meeting_assets_tool,
            estimate_aws_cost_tool,
        ],
    )


def build_stdio_mcp_config() -> dict[str, Any]:
    env = {key: value for key, value in os.environ.items() if value is not None}
    env.setdefault("SANDBOX_ROOT", str(sandbox_root()))
    return {
        "meetings": {
            "type": "stdio",
            "command": sys.executable,
            "args": [str(ROOT / "mcp_server.py")],
            "env": env,
        }
    }


def build_mcp_servers() -> dict[str, Any]:
    if MCP_TRANSPORT == "stdio":
        return build_stdio_mcp_config()
    return {"meetings": build_sdk_mcp_server()}


def _clear_macos_quarantine() -> None:
    """First launch of the bundled CLI often hangs under Gatekeeper."""
    try:
        import claude_agent_sdk
    except ImportError:
        return
    bundled = Path(claude_agent_sdk.__file__).resolve().parent / "_bundled" / "claude"
    if not bundled.is_file():
        return
    try:
        subprocess.run(
            ["xattr", "-d", "com.apple.quarantine", str(bundled)],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return


def is_sdk_startup_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    markers = (
        "control request timeout",
        "claude code not found",
        "cli not found",
        "cli connection",
        "could not load credentials",
        "credit balance",
        "invalid api key",
        "authentication",
        "api error",
    )
    return any(marker in text for marker in markers)


def build_agent_options():
    from claude_agent_sdk import ClaudeAgentOptions

    _clear_macos_quarantine()

    # Keep initialize from sitting on the default 60s timeout when the CLI hangs.
    os.environ.setdefault("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "20000")

    env = {
        "API_TIMEOUT_MS": os.getenv("API_TIMEOUT_MS", "120000"),
        "CLAUDE_CODE_MAX_RETRIES": os.getenv("CLAUDE_CODE_MAX_RETRIES", "2"),
        "CLAUDE_CODE_STREAM_CLOSE_TIMEOUT": os.environ["CLAUDE_CODE_STREAM_CLOSE_TIMEOUT"],
        # Prevent the AWS SDK from stalling on 169.254.169.254 during local runs.
        "AWS_EC2_METADATA_DISABLED": os.getenv("AWS_EC2_METADATA_DISABLED", "true"),
    }
    for key in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
        if os.getenv(key):
            env[key] = os.environ[key]
    if use_bedrock():
        env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        env["AWS_REGION"] = AWS_REGION
        env["AWS_EC2_METADATA_DISABLED"] = "false"
    else:
        # Inherited process env may have CLAUDE_CODE_USE_BEDROCK=1; overlay it off.
        # Empty string is falsy in the CLI; do not use "0" (non-empty is truthy).
        env["CLAUDE_CODE_USE_BEDROCK"] = ""
        if bedrock_requested():
            logger.warning(
                "CLAUDE_CODE_USE_BEDROCK is set but AWS credentials were not found; "
                "using ANTHROPIC_API_KEY instead"
            )

    stderr_chunks: list[str] = []

    def _stderr(line: str) -> None:
        stderr_chunks.append(line)
        logger.warning("claude-cli: %s", line.rstrip())

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers=build_mcp_servers(),
        tools=[],
        allowed_tools=MCP_TOOL_NAMES + ["mcp__meetings__*"],
        disallowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"],
        permission_mode="dontAsk",
        max_turns=AGENT_MAX_TURNS,
        max_budget_usd=AGENT_MAX_BUDGET_USD,
        cwd=str(ROOT),
        setting_sources=[],
        strict_mcp_config=True,
        env=env,
        stderr=_stderr,
    )
    options._stderr_chunks = stderr_chunks  # type: ignore[attr-defined]
    return options


def build_prompt(
    *,
    audio_path: str | None,
    image_paths: list[str],
    user_query: str | None = None,
) -> str:
    lines = [
        "請分析這場會議並產出結構化報告。",
        f"沙箱工作目錄：{sandbox_root()}",
    ]
    if audio_path:
        lines.append(f"語音檔（沙箱相對路徑）：{audio_path}")
    if image_paths:
        lines.append("簡報圖：" + ", ".join(image_paths))
    if user_query:
        lines.append(f"額外指示：{user_query}")
    lines.append("先規劃要呼叫哪些工具，再逐步執行，最後只回傳符合 schema 的 JSON。")
    return "\n".join(lines)


def _tool_names_from_message(message: Any) -> list[str]:
    names: list[str] = []
    content = getattr(message, "content", None)
    if not content:
        return names
    for block in content:
        name = getattr(block, "name", None) or (
            block.get("name") if isinstance(block, dict) else None
        )
        if name:
            names.append(str(name))
    return names


async def run_claude_agent(
    *,
    audio_path: str | None = None,
    image_paths: list[str] | None = None,
    user_query: str | None = None,
) -> dict[str, Any]:
    if not has_anthropic_credentials():
        raise RuntimeError(
            "Claude Agent SDK 需要 ANTHROPIC_API_KEY 或 CLAUDE_CODE_USE_BEDROCK=1"
        )

    from claude_agent_sdk import ResultMessage, query

    prompt = build_prompt(
        audio_path=audio_path,
        image_paths=image_paths or [],
        user_query=user_query,
    )
    tools_used: list[str] = []
    final_text = ""
    structured: dict[str, Any] | None = None
    options = build_agent_options()

    try:
        async for message in query(prompt=prompt, options=options):
            tools_used.extend(_tool_names_from_message(message))
            if isinstance(message, ResultMessage):
                final_text = message.result or ""
                structured_attr = getattr(message, "structured_output", None)
                if isinstance(structured_attr, dict):
                    structured = structured_attr
    except Exception as exc:
        stderr = "".join(getattr(options, "_stderr_chunks", []) or [])
        if stderr:
            raise RuntimeError(f"{exc}\nclaude-cli stderr:\n{stderr[-4000:]}") from exc
        raise

    if structured:
        report = structured.get("report") or final_text
        return {
            "transcript": structured.get("transcript") or "",
            "image_insights": structured.get("image_insights") or [],
            "report": report,
            "tools_used": structured.get("tools_used") or tools_used,
        }

    return {
        "transcript": "",
        "image_insights": [],
        "report": final_text,
        "tools_used": tools_used,
    }


def claude_sdk_importable() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401

        return True
    except ImportError:
        return False
