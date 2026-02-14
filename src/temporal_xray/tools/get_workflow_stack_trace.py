from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..temporal_client import get_temporal_client
from ..types import GetWorkflowStackTraceInput, StackTraceOutput

PENDING_ACTIVITY_STATES = {
    0: "UNSPECIFIED",
    1: "SCHEDULED",
    2: "STARTED",
    3: "CANCEL_REQUESTED",
}


async def get_workflow_stack_trace(input: GetWorkflowStackTraceInput) -> StackTraceOutput:
    client = await get_temporal_client(input.namespace)

    try:
        handle = client.get_workflow_handle(input.workflow_id, run_id=input.run_id)

        description = await handle.describe()

        stack_trace = ""
        try:
            stack_trace = await handle.query("__stack_trace")
        except Exception:
            stack_trace = "Stack trace unavailable (workflow may not be running or query handler not registered)"

        start_time = description.start_time
        start_time_str = start_time.isoformat() if start_time else datetime.now(timezone.utc).isoformat()

        now = datetime.now(timezone.utc)
        duration_ms = int((now - start_time).total_seconds() * 1000) if start_time else 0

        pending_activities = _extract_pending_activities(description)

        return StackTraceOutput(
            workflow_id=input.workflow_id,
            status=description.status.name if hasattr(description.status, "name") else str(description.status),
            running_since=start_time_str,
            duration_so_far_ms=duration_ms,
            stack_trace=str(stack_trace),
            pending_activities=pending_activities,
        )
    except Exception as e:
        message = str(e)
        if "not found" in message.lower() or "NotFound" in message:
            raise RuntimeError(
                f"No workflow found with ID '{input.workflow_id}'. "
                "The workflow may have been archived or the ID may be incorrect."
            ) from e
        raise RuntimeError(f"Failed to get workflow stack trace: {message}") from e


def _extract_pending_activities(description: Any) -> list[dict[str, Any]]:
    """Extract pending activities from a workflow description."""
    raw = getattr(description, "raw", None) or getattr(description, "raw_description", None)
    if not raw:
        return []

    pending = getattr(raw, "pending_activities", None)
    if not pending:
        return []

    result = []
    for pa in pending:
        activity_type_obj = getattr(pa, "activity_type", None)
        activity_type = getattr(activity_type_obj, "name", "Unknown") if activity_type_obj else "Unknown"

        state = getattr(pa, "state", None)
        if isinstance(state, int):
            state_str = PENDING_ACTIVITY_STATES.get(state, f"UNKNOWN({state})")
        elif state is not None:
            state_str = str(state)
        else:
            state_str = "unknown"

        scheduled_time = getattr(pa, "scheduled_time", None)
        scheduled_time_str = ""
        if scheduled_time:
            if hasattr(scheduled_time, "isoformat"):
                scheduled_time_str = scheduled_time.isoformat()
            elif hasattr(scheduled_time, "seconds"):
                scheduled_time_str = datetime.fromtimestamp(
                    int(scheduled_time.seconds or 0), tz=timezone.utc
                ).isoformat()

        attempt = getattr(pa, "attempt", 1)
        last_failure_obj = getattr(pa, "last_failure", None)
        last_failure = getattr(last_failure_obj, "message", None) if last_failure_obj else None

        result.append({
            "activity_type": activity_type,
            "state": state_str,
            "scheduled_time": scheduled_time_str,
            "attempt": int(attempt) if attempt else 1,
            "last_failure": last_failure,
        })

    return result
