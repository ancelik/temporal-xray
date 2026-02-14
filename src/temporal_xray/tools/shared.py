from __future__ import annotations

from typing import Any

from ..types import WorkflowSummary


def to_workflow_summary(workflow: Any) -> WorkflowSummary:
    """Convert a Temporal workflow listing entry to a WorkflowSummary."""
    start_time = workflow.start_time.isoformat() if workflow.start_time else ""
    close_time = workflow.close_time.isoformat() if workflow.close_time else None
    duration_ms = None
    if workflow.start_time and workflow.close_time:
        delta = workflow.close_time - workflow.start_time
        duration_ms = int(delta.total_seconds() * 1000)

    search_attrs = {}
    if workflow.search_attributes:
        # temporalio Python SDK returns SearchAttributes as a mapping
        for key, values in workflow.search_attributes.items():
            search_attrs[key] = values[0] if len(values) == 1 else list(values)

    return WorkflowSummary(
        workflow_id=workflow.id,
        run_id=workflow.run_id,
        workflow_type=workflow.workflow_type,
        status=workflow.status.name if hasattr(workflow.status, "name") else str(workflow.status),
        start_time=start_time,
        close_time=close_time,
        duration_ms=duration_ms,
        task_queue=workflow.task_queue,
        search_attributes=search_attrs,
    )
