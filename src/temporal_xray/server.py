"""Temporal X-Ray MCP server — 7 read-only debugging tools for Temporal workflows."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .client import (
    TemporalConfig,
    close_connection,
    connect_to_server,
    get_connection_status,
    get_temporal_client,
    to_workflow_summary,
)
from .transformers import diff_executions, summarize_history

mcp = FastMCP("temporal-xray")

# --- Shared Helpers ---

STATUS_MAP = {
    "running": "Running", "completed": "Completed", "failed": "Failed",
    "timed_out": "TimedOut", "cancelled": "Canceled", "terminated": "Terminated",
}


def _escape(v: str) -> str:
    return v.replace("'", "''")


def _raise_friendly(e: Exception, context: str) -> None:
    """Re-raise with a user-friendly message based on common Temporal error patterns."""
    msg = str(e)
    if "namespace" in msg and "not found" in msg:
        raise RuntimeError(f"Namespace not found. Verify TEMPORAL_NAMESPACE. Details: {msg}") from e
    if "UNAVAILABLE" in msg or "connect" in msg.lower():
        raise RuntimeError(f"Cannot connect to Temporal server. Details: {msg}") from e
    if "not found" in msg.lower():
        raise RuntimeError(f"Not found: {context}. Details: {msg}") from e
    if "permission" in msg.lower() or "unauthorized" in msg.lower():
        raise RuntimeError(f"Permission denied for {context}.") from e
    raise RuntimeError(f"Failed to {context}: {msg}") from e


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


# --- Tools ---


@mcp.tool()
async def list_workflows(
    namespace: Annotated[str | None, Field(description="Temporal namespace to query")] = None,
    workflow_type: Annotated[str | None, Field(description="Filter by workflow type name")] = None,
    workflow_id: Annotated[str | None, Field(description="Filter by exact workflow ID")] = None,
    status: Annotated[str | None, Field(description="Filter by execution status: running, completed, failed, timed_out, cancelled, terminated, all")] = None,
    query: Annotated[str | None, Field(description="Raw Temporal visibility query for advanced filtering")] = None,
    start_time_from: Annotated[str | None, Field(description="Only executions started after this ISO time")] = None,
    start_time_to: Annotated[str | None, Field(description="Only executions started before this ISO time")] = None,
    limit: Annotated[int, Field(description="Number of results (max 50)", ge=1, le=50)] = 10,
) -> str:
    """List and search Temporal workflow executions. Filter by workflow type, ID, status, time range, or raw visibility query. Use this to find specific executions for investigation."""
    try:
        client = await get_temporal_client(namespace)

        if query:
            q = query
        else:
            clauses = []
            if workflow_type:
                clauses.append(f"WorkflowType = '{_escape(workflow_type)}'")
            if workflow_id:
                clauses.append(f"WorkflowId = '{_escape(workflow_id)}'")
            if status and status != "all":
                clauses.append(f"ExecutionStatus = '{STATUS_MAP.get(status, status)}'")
            if start_time_from:
                clauses.append(f"StartTime >= '{start_time_from}'")
            if start_time_to:
                clauses.append(f"StartTime <= '{start_time_to}'")
            q = " AND ".join(clauses)

        workflows, has_more, count = [], False, 0
        async for wf in client.list_workflows(query=q or None):
            if count >= limit:
                has_more = True
                break
            workflows.append(to_workflow_summary(wf))
            count += 1

        return _json({"workflows": workflows, "total_count": count, "has_more": has_more})
    except Exception as e:
        _raise_friendly(e, "list workflows")


@mcp.tool()
async def get_workflow_history(
    workflow_id: Annotated[str, Field(description="Workflow execution ID")],
    namespace: Annotated[str | None, Field(description="Temporal namespace to query")] = None,
    run_id: Annotated[str | None, Field(description="Run ID (defaults to latest run)")] = None,
    detail_level: Annotated[str, Field(description="Level of detail: summary, standard, or full")] = "summary",
    event_types: Annotated[list[str] | None, Field(description="Filter to specific event types")] = None,
) -> str:
    """Get the execution history of a Temporal workflow. Returns a timeline of activities with their inputs, outputs, durations, and any failures. Use detail_level 'summary' for overview, 'standard' for full payloads, 'full' for raw events."""
    try:
        client = await get_temporal_client(namespace)
        handle = client.get_workflow_handle(workflow_id, run_id=run_id)
        history = await handle.fetch_history()
        events = list(history.events) if history.events else []

        if not events:
            raise RuntimeError(
                f"No workflow found with ID '{workflow_id}'. "
                "The workflow may have been archived or the ID may be incorrect."
            )

        desc = await handle.describe()
        effective_run_id = run_id or desc.run_id

        return _json(summarize_history(
            workflow_id, effective_run_id, events,
            detail_level=detail_level, event_types=event_types,
        ))
    except RuntimeError:
        raise
    except Exception as e:
        _raise_friendly(e, f"get history for workflow '{workflow_id}'")


@mcp.tool()
async def get_workflow_stack_trace(
    workflow_id: Annotated[str, Field(description="Workflow execution ID")],
    namespace: Annotated[str | None, Field(description="Temporal namespace to query")] = None,
    run_id: Annotated[str | None, Field(description="Run ID (defaults to latest run)")] = None,
) -> str:
    """Get the current stack trace and pending activities of a running Temporal workflow. Shows where the workflow is blocked and what it's waiting for."""
    try:
        client = await get_temporal_client(namespace)
        handle = client.get_workflow_handle(workflow_id, run_id=run_id)
        desc = await handle.describe()

        trace = ""
        try:
            trace = await handle.query("__stack_trace")
        except Exception:
            trace = "Stack trace unavailable (workflow may not be running or query handler not registered)"

        start = desc.start_time
        now = datetime.now(timezone.utc)

        # Extract pending activities from raw description
        pending = []
        raw = getattr(desc, "raw", None) or getattr(desc, "raw_description", None)
        if raw and hasattr(raw, "pending_activities") and raw.pending_activities:
            state_names = {0: "UNSPECIFIED", 1: "SCHEDULED", 2: "STARTED", 3: "CANCEL_REQUESTED"}
            for pa in raw.pending_activities:
                at = getattr(getattr(pa, "activity_type", None), "name", "Unknown")
                st = getattr(pa, "state", None)
                state_str = state_names.get(int(st), str(st)) if st is not None else "unknown"
                sched = getattr(pa, "scheduled_time", None)
                sched_str = sched.isoformat() if hasattr(sched, "isoformat") else ""
                lf = getattr(getattr(pa, "last_failure", None), "message", None)
                pending.append({
                    "activity_type": at, "state": state_str,
                    "scheduled_time": sched_str, "attempt": int(getattr(pa, "attempt", 1)),
                    "last_failure": lf,
                })

        return _json({
            "workflow_id": workflow_id,
            "status": desc.status.name if hasattr(desc.status, "name") else str(desc.status),
            "running_since": start.isoformat() if start else now.isoformat(),
            "duration_so_far_ms": int((now - start).total_seconds() * 1000) if start else 0,
            "stack_trace": str(trace),
            "pending_activities": pending,
        })
    except Exception as e:
        _raise_friendly(e, f"get stack trace for workflow '{workflow_id}'")


@mcp.tool()
async def compare_executions(
    workflow_id_a: Annotated[str, Field(description='Workflow ID of the "good" execution')],
    workflow_id_b: Annotated[str, Field(description='Workflow ID of the "bad" execution')],
    namespace: Annotated[str | None, Field(description="Temporal namespace to query")] = None,
    run_id_a: Annotated[str | None, Field(description="Run ID for execution A")] = None,
    run_id_b: Annotated[str | None, Field(description="Run ID for execution B")] = None,
) -> str:
    """Compare two Temporal workflow executions to find where they diverge. Identifies data differences in activity inputs/outputs, structural differences (different activities executed), and signal differences. Ideal for investigating why one execution succeeded and another failed."""
    try:
        client = await get_temporal_client(namespace)

        async def fetch(wf_id: str, rid: str | None) -> dict:
            handle = client.get_workflow_handle(wf_id, run_id=rid)
            history = await handle.fetch_history()
            events = list(history.events) if history.events else []
            desc = await handle.describe()
            return summarize_history(wf_id, rid or desc.run_id, events, detail_level="standard")

        hist_a, hist_b = await asyncio.gather(
            fetch(workflow_id_a, run_id_a),
            fetch(workflow_id_b, run_id_b),
        )

        return _json({
            "execution_a": {"workflow_id": hist_a["workflow_id"], "status": hist_a["status"], "workflow_type": hist_a["workflow_type"]},
            "execution_b": {"workflow_id": hist_b["workflow_id"], "status": hist_b["status"], "workflow_type": hist_b["workflow_type"]},
            "same_workflow_type": hist_a["workflow_type"] == hist_b["workflow_type"],
            **diff_executions(hist_a, hist_b),
        })
    except Exception as e:
        _raise_friendly(e, "compare executions")


@mcp.tool()
async def describe_task_queue(
    task_queue: Annotated[str, Field(description="Task queue name")],
    namespace: Annotated[str | None, Field(description="Temporal namespace to query")] = None,
    task_queue_type: Annotated[str, Field(description="Type of task queue: workflow or activity")] = "workflow",
) -> str:
    """Describe a Temporal task queue to check worker health. Shows active pollers, their versions, last access times, and processing rates. Useful for diagnosing infrastructure issues and version mismatches."""
    from temporalio.api.enums.v1 import TaskQueueType
    from temporalio.api.taskqueue.v1 import TaskQueue as TQProto
    from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest

    try:
        client = await get_temporal_client(namespace)
        tq_type = TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY if task_queue_type == "activity" else TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW

        resp = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace=client.namespace,
                task_queue=TQProto(name=task_queue, kind=1),
                task_queue_type=tq_type,
            )
        )

        pollers = []
        for p in resp.pollers or []:
            lat = getattr(p, "last_access_time", None)
            lat_str = lat.isoformat() if hasattr(lat, "isoformat") else ""
            wv = getattr(getattr(p, "worker_version_capabilities", None), "build_id", None)
            pollers.append({
                "identity": p.identity or "unknown",
                "last_access_time": lat_str,
                "rate_per_second": p.rate_per_second or 0,
                "worker_version": wv,
            })

        return _json({
            "task_queue": task_queue,
            "pollers": pollers,
            "backlog_count": 0,
            "versions_active": list({p["worker_version"] for p in pollers if p["worker_version"]}),
        })
    except Exception as e:
        _raise_friendly(e, f"describe task queue '{task_queue}'")


@mcp.tool()
async def search_workflow_data(
    workflow_type: Annotated[str, Field(description="Workflow type to search")],
    query: Annotated[str, Field(description="Temporal visibility query")],
    namespace: Annotated[str | None, Field(description="Temporal namespace to query")] = None,
    aggregate: Annotated[str, Field(description="Aggregation mode: count, list, or sample")] = "list",
    limit: Annotated[int, Field(description="Max results", ge=1, le=50)] = 20,
) -> str:
    """Search and aggregate Temporal workflow data using visibility queries. Find patterns across many executions — count affected workflows, list them, or get a sample. Useful for detecting widespread silent failures."""
    try:
        client = await get_temporal_client(namespace)
        escaped = _escape(workflow_type)
        full_query = query if "WorkflowType" in query else f"WorkflowType = '{escaped}' AND {query}"

        if aggregate == "count":
            sample_ids, count = [], 0
            async for wf in client.list_workflows(query=full_query):
                count += 1
                if len(sample_ids) < 3:
                    sample_ids.append(wf.id)
                if count >= 10000:
                    break
            return _json({"query": full_query, "count": count, "time_range": "query-defined", "sample_workflow_ids": sample_ids})

        effective_limit = min(limit or 3, 5) if aggregate == "sample" else (limit or 20)
        workflows, sample_ids, count = [], [], 0
        async for wf in client.list_workflows(query=full_query):
            if count >= effective_limit:
                break
            sample_ids.append(wf.id)
            if aggregate != "sample" or count < 3:
                workflows.append(to_workflow_summary(wf))
            count += 1

        result: dict[str, Any] = {
            "query": full_query, "count": count, "time_range": "query-defined",
            "sample_workflow_ids": sample_ids[:5],
        }
        if aggregate == "list":
            result["workflows"] = workflows
        return _json(result)
    except Exception as e:
        _raise_friendly(e, "search workflow data")


@mcp.tool()
async def temporal_connection(
    action: Annotated[str, Field(description="'status' to check current connection, 'connect' to establish a new one")] = "status",
    address: Annotated[str | None, Field(description="Temporal server address (e.g., localhost:7233)")] = None,
    namespace: Annotated[str | None, Field(description="Default namespace for this connection")] = None,
    api_key: Annotated[str | None, Field(description="API key for Temporal Cloud authentication")] = None,
    tls_cert_path: Annotated[str | None, Field(description="Path to TLS client certificate")] = None,
    tls_key_path: Annotated[str | None, Field(description="Path to TLS client key")] = None,
) -> str:
    """Check or change the Temporal server connection. Use action 'status' to see current connection info, or 'connect' to switch to a different server or namespace. Useful for working with multiple environments (dev, staging, prod)."""
    if action == "connect":
        if not address and not namespace:
            raise RuntimeError("Provide at least an address or namespace to connect.")
        current = get_connection_status()
        status = await connect_to_server(TemporalConfig(
            address=address or current["address"],
            namespace=namespace or current["namespace"],
            tls_cert_path=tls_cert_path, tls_key_path=tls_key_path, api_key=api_key,
        ))
        return _json({**status, "connected": True})

    return _json(get_connection_status())


# --- Entry Point ---


def main() -> None:
    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        asyncio.run(close_connection())


if __name__ == "__main__":
    main()
