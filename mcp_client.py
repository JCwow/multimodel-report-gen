"""MCP client for the meetings server.

Used by evals, local demos, and as the reference Client implementation.
Connect in-process (tests) or via stdio (production-shaped).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

_ROOT = os.path.dirname(os.path.abspath(__file__))


def stdio_params() -> StdioServerParameters:
    env = {key: value for key, value in os.environ.items() if value is not None}
    return StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(_ROOT, "mcp_server.py")],
        env=env,
    )


def in_process_server():
    from mcp_server import mcp

    return mcp


async def list_tools(client: Client) -> list[str]:
    listing = await client.list_tools()
    tools = getattr(listing, "tools", listing)
    return [tool.name for tool in tools]


async def call_tool(client: Client, name: str, arguments: dict[str, Any] | None = None) -> str:
    result = await client.call_tool(name, arguments or {}, read_timeout_seconds=60.0)
    if getattr(result, "structured_content", None):
        return json.dumps(result.structured_content, ensure_ascii=False, indent=2)
    chunks = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            chunks.append(text)
    if chunks:
        return "\n".join(chunks)
    return str(result)


async def connect_in_process() -> Client:
    return Client(in_process_server())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MCP client for the meetings server")
    parser.add_argument("action", choices=["list", "call"], help="list tools or call one")
    parser.add_argument("tool", nargs="?", help="tool name for call")
    parser.add_argument(
        "--transport",
        choices=["memory", "stdio"],
        default="memory",
        help="memory talks to MCPServer in-process; stdio spawns mcp_server.py",
    )
    parser.add_argument(
        "--args",
        default="{}",
        help="JSON object of tool arguments",
    )
    return parser.parse_args()


async def _run() -> None:
    args = parse_args()
    arguments = json.loads(args.args)
    if args.transport == "stdio":
        cm = Client(stdio_client(stdio_params()))
    else:
        cm = Client(in_process_server())

    async with cm as client:
        if args.action == "list":
            print(json.dumps(await list_tools(client), ensure_ascii=False, indent=2))
            return
        if not args.tool:
            raise SystemExit("call requires a tool name")
        print(await call_tool(client, args.tool, arguments))


if __name__ == "__main__":
    asyncio.run(_run())
