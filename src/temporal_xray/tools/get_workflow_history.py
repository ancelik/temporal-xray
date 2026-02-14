from __future__ import annotations

from ..temporal_client import get_temporal_client
from ..transformers.history_summarizer import summarize_history
from ..types import GetWorkflowHistoryInput, WorkflowHistory


async def get_workflow_history(input: GetWorkflowHistoryInput) -> WorkflowHistory:
    client = await get_temporal_client(input.namespace)

    try:
        handle = client.get_workflow_handle(input.workflow_id, run_id=input.run_id)

        history = await handle.fetch_history()
        events = list(history.events) if history.events else []

        if not events:
            raise RuntimeError(
                f"No workflow found with ID '{input.workflow_id}'. "
                "The workflow may have been archived or the ID may be incorrect."
            )

        description = await handle.describe()
        run_id = input.run_id or description.run_id

        return summarize_history(
            input.workflow_id,
            run_id,
            events,
            detail_level=input.detail_level or "summary",
            event_types=input.event_types,
        )
    except RuntimeError:
        raise
    except Exception as e:
        message = str(e)
        if "not found" in message.lower() or "NotFound" in message:
            raise RuntimeError(
                f"No workflow found with ID '{input.workflow_id}'. "
                "The workflow may have been archived or the ID may be incorrect."
            ) from e
        if "permission" in message.lower() or "Unauthorized" in message:
            raise RuntimeError(
                "Permission denied. The configured credentials don't have read access to this namespace."
            ) from e
        raise RuntimeError(f"Failed to get workflow history: {message}") from e
