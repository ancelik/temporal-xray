from __future__ import annotations

from ..temporal_client import get_temporal_client
from ..types import SearchWorkflowDataInput, SearchWorkflowDataOutput
from .shared import to_workflow_summary


async def search_workflow_data(input: SearchWorkflowDataInput) -> SearchWorkflowDataOutput:
    client = await get_temporal_client(input.namespace)

    escaped_type = input.workflow_type.replace("'", "''")
    full_query = (
        input.query
        if "WorkflowType" in input.query
        else f"WorkflowType = '{escaped_type}' AND {input.query}"
    )

    try:
        if input.aggregate == "count":
            return await _count_workflows(client, full_query)

        limit = (
            min(input.limit or 3, 5)
            if input.aggregate == "sample"
            else input.limit or 20
        )

        workflows = []
        sample_ids: list[str] = []
        count = 0

        async for workflow in client.list_workflows(query=full_query):
            if count >= limit:
                break
            sample_ids.append(workflow.id)
            if input.aggregate != "sample" or count < 3:
                workflows.append(to_workflow_summary(workflow))
            count += 1

        return SearchWorkflowDataOutput(
            query=full_query,
            count=count,
            time_range="query-defined",
            sample_workflow_ids=sample_ids[:5],
            workflows=workflows if input.aggregate == "list" else None,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to search workflow data: {e}") from e


async def _count_workflows(client, query: str) -> SearchWorkflowDataOutput:
    sample_ids: list[str] = []
    count = 0

    async for workflow in client.list_workflows(query=query):
        count += 1
        if len(sample_ids) < 3:
            sample_ids.append(workflow.id)
        if count >= 10000:
            break

    return SearchWorkflowDataOutput(
        query=query,
        count=count,
        time_range="query-defined",
        sample_workflow_ids=sample_ids,
    )
