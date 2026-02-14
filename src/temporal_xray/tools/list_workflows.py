from __future__ import annotations

from ..temporal_client import get_temporal_client
from ..types import ListWorkflowsInput, ListWorkflowsOutput
from .shared import to_workflow_summary

STATUS_MAP = {
    "running": "Running",
    "completed": "Completed",
    "failed": "Failed",
    "timed_out": "TimedOut",
    "cancelled": "Canceled",
    "terminated": "Terminated",
}


def _escape_query_value(value: str) -> str:
    return value.replace("'", "''")


def _build_query(input: ListWorkflowsInput) -> str:
    if input.query:
        return input.query

    clauses: list[str] = []

    if input.workflow_type:
        clauses.append(f"WorkflowType = '{_escape_query_value(input.workflow_type)}'")

    if input.workflow_id:
        clauses.append(f"WorkflowId = '{_escape_query_value(input.workflow_id)}'")

    if input.status and input.status != "all":
        mapped = STATUS_MAP.get(input.status, input.status)
        clauses.append(f"ExecutionStatus = '{mapped}'")

    if input.start_time_from:
        clauses.append(f"StartTime >= '{input.start_time_from}'")

    if input.start_time_to:
        clauses.append(f"StartTime <= '{input.start_time_to}'")

    return " AND ".join(clauses)


async def list_workflows(input: ListWorkflowsInput) -> ListWorkflowsOutput:
    client = await get_temporal_client(input.namespace)
    query = _build_query(input)

    try:
        limit = input.limit or 10
        workflows = []
        has_more = False
        count = 0

        async for workflow in client.list_workflows(query=query or None):
            if count >= limit:
                has_more = True
                break
            workflows.append(to_workflow_summary(workflow))
            count += 1

        return ListWorkflowsOutput(
            workflows=workflows, total_count=count, has_more=has_more
        )
    except Exception as e:
        message = str(e)
        if "namespace" in message and "not found" in message:
            raise RuntimeError(
                f"Namespace not found. Verify TEMPORAL_NAMESPACE is correct. Details: {message}"
            ) from e
        if "UNAVAILABLE" in message or "connect" in message:
            raise RuntimeError(
                f"Cannot connect to Temporal server. Verify TEMPORAL_ADDRESS is correct and the server is running. Details: {message}"
            ) from e
        raise RuntimeError(f"Failed to list workflows: {message}") from e
