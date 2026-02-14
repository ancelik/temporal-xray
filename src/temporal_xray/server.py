from __future__ import annotations

import asyncio
import json
import signal
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .temporal_client import close_connection
from .types import (
    CompareExecutionsInput,
    DescribeTaskQueueInput,
    GetWorkflowHistoryInput,
    GetWorkflowStackTraceInput,
    ListWorkflowsInput,
    SearchWorkflowDataInput,
    TemporalConnectionInput,
)
from .tools.list_workflows import list_workflows
from .tools.get_workflow_history import get_workflow_history
from .tools.get_workflow_stack_trace import get_workflow_stack_trace
from .tools.compare_executions import compare_executions
from .tools.describe_task_queue import describe_task_queue
from .tools.search_workflow_data import search_workflow_data
from .tools.temporal_connection import temporal_connection

TOOLS = [
    {
        "name": "list_workflows",
        "description": "List and search Temporal workflow executions. Filter by workflow type, ID, status, time range, or raw visibility query. Use this to find specific executions for investigation.",
        "input_model": ListWorkflowsInput,
        "handler": list_workflows,
    },
    {
        "name": "get_workflow_history",
        "description": "Get the execution history of a Temporal workflow. Returns a timeline of activities with their inputs, outputs, durations, and any failures. Use detail_level 'summary' for overview, 'standard' for full payloads, 'full' for raw events.",
        "input_model": GetWorkflowHistoryInput,
        "handler": get_workflow_history,
    },
    {
        "name": "get_workflow_stack_trace",
        "description": "Get the current stack trace and pending activities of a running Temporal workflow. Shows where the workflow is blocked and what it's waiting for.",
        "input_model": GetWorkflowStackTraceInput,
        "handler": get_workflow_stack_trace,
    },
    {
        "name": "compare_executions",
        "description": "Compare two Temporal workflow executions to find where they diverge. Identifies data differences in activity inputs/outputs, structural differences (different activities executed), and signal differences. Ideal for investigating why one execution succeeded and another failed.",
        "input_model": CompareExecutionsInput,
        "handler": compare_executions,
    },
    {
        "name": "describe_task_queue",
        "description": "Describe a Temporal task queue to check worker health. Shows active pollers, their versions, last access times, and processing rates. Useful for diagnosing infrastructure issues and version mismatches.",
        "input_model": DescribeTaskQueueInput,
        "handler": describe_task_queue,
    },
    {
        "name": "search_workflow_data",
        "description": "Search and aggregate Temporal workflow data using visibility queries. Find patterns across many executions — count affected workflows, list them, or get a sample. Useful for detecting widespread silent failures.",
        "input_model": SearchWorkflowDataInput,
        "handler": search_workflow_data,
    },
    {
        "name": "temporal_connection",
        "description": "Check or change the Temporal server connection. Use action 'status' to see current connection info, or 'connect' to switch to a different server or namespace. Useful for working with multiple environments (dev, staging, prod).",
        "input_model": TemporalConnectionInput,
        "handler": temporal_connection,
    },
]

app = Server("temporal-xray")


@app.list_tools()
async def list_tools() -> list[Tool]:
    tools = []
    for tool_def in TOOLS:
        schema = tool_def["input_model"].model_json_schema()
        tools.append(
            Tool(
                name=tool_def["name"],
                description=tool_def["description"],
                inputSchema=schema,
            )
        )
    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    for tool_def in TOOLS:
        if tool_def["name"] == name:
            try:
                parsed = tool_def["input_model"].model_validate(arguments)
                result = await tool_def["handler"](parsed)
                if hasattr(result, "model_dump"):
                    data = result.model_dump(exclude_none=True)
                else:
                    data = result
                return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]
            except Exception as e:
                message = str(e)
                return [TextContent(type="text", text=json.dumps({"error": message}, indent=2))]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}, indent=2))]


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        asyncio.run(close_connection())
    except Exception as e:
        print(f"Failed to start MCP server: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
