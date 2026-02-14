from __future__ import annotations

import asyncio

from ..transformers.diff_engine import diff_executions
from ..types import CompareExecutionsInput, CompareExecutionsOutput, GetWorkflowHistoryInput
from .get_workflow_history import get_workflow_history


async def compare_executions(input: CompareExecutionsInput) -> CompareExecutionsOutput:
    """Compare two Temporal workflow executions to find where they diverge."""
    history_a, history_b = await asyncio.gather(
        get_workflow_history(
            GetWorkflowHistoryInput(
                namespace=input.namespace,
                workflow_id=input.workflow_id_a,
                run_id=input.run_id_a,
                detail_level="standard",
            )
        ),
        get_workflow_history(
            GetWorkflowHistoryInput(
                namespace=input.namespace,
                workflow_id=input.workflow_id_b,
                run_id=input.run_id_b,
                detail_level="standard",
            )
        ),
    )

    diff = diff_executions(history_a, history_b)

    return CompareExecutionsOutput(
        execution_a={
            "workflow_id": history_a.workflow_id,
            "status": history_a.status,
            "workflow_type": history_a.workflow_type,
        },
        execution_b={
            "workflow_id": history_b.workflow_id,
            "status": history_b.status,
            "workflow_type": history_b.workflow_type,
        },
        same_workflow_type=history_a.workflow_type == history_b.workflow_type,
        **diff,
    )
