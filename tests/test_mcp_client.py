import pytest

from mcp_client import call_tool, in_process_server, list_tools


@pytest.mark.asyncio
async def test_in_process_client_lists_and_calls_safe_tools():
    from mcp import Client

    async with Client(in_process_server()) as client:
        names = await list_tools(client)
        assert "lookup_employee" in names
        assert "estimate_aws_cost" in names
        assert "query_internal_api" in names

        employee = await call_tool(client, "lookup_employee", {"query": "林佳穎"})
        assert "E001" in employee

        denied = await call_tool(
            client,
            "query_internal_api",
            {"resource": "payroll", "query": "bonus"},
        )
        assert "SANDBOX_DENIED" in denied

        cost = await call_tool(client, "estimate_aws_cost", {"vcpu": 1, "memory_gb": 2})
        assert "total_usd" in cost
