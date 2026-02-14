from __future__ import annotations

import json
from typing import Any

from ..temporal_client import decode_single_payload
from ..types import TimelineStep, WorkflowHistory
from .event_filter import (
    filter_by_event_types,
    filter_internal_events,
    group_activity_events,
    resolve_event_type,
)

SUMMARY_TRUNCATE_BYTES = 10240  # 10KB


def summarize_history(
    workflow_id: str,
    run_id: str,
    events: list[Any],
    *,
    detail_level: str = "summary",
    event_types: list[str] | None = None,
) -> WorkflowHistory:
    """Transform raw Temporal event history into a structured WorkflowHistory."""
    if detail_level == "full":
        return _build_full_history(workflow_id, run_id, events)

    filtered_events = filter_by_event_types(events, event_types) if event_types else events

    start_event = _find_event(events, "WorkflowExecutionStarted")
    completed_event = _find_event(events, "WorkflowExecutionCompleted")
    failed_event = _find_event(events, "WorkflowExecutionFailed")
    timed_out_event = _find_event(events, "WorkflowExecutionTimedOut")
    canceled_event = _find_event(events, "WorkflowExecutionCanceled")
    terminated_event = _find_event(events, "WorkflowExecutionTerminated")

    start_attrs = getattr(start_event, "workflow_execution_started_event_attributes", None)
    wf_type_obj = getattr(start_attrs, "workflow_type", None) if start_attrs else None
    workflow_type = getattr(wf_type_obj, "name", None) or "Unknown"

    truncate_at = SUMMARY_TRUNCATE_BYTES if detail_level == "summary" else None
    workflow_input = decode_single_payload(
        getattr(start_attrs, "input", None) if start_attrs else None,
        truncate_at,
    )

    status = "RUNNING"
    result: Any = None
    failure: Any = None
    close_time: str | None = None

    if completed_event:
        status = "COMPLETED"
        attrs = getattr(completed_event, "workflow_execution_completed_event_attributes", None)
        result = decode_single_payload(getattr(attrs, "result", None) if attrs else None, truncate_at)
        close_time = _format_timestamp(getattr(completed_event, "event_time", None))
    elif failed_event:
        status = "FAILED"
        attrs = getattr(failed_event, "workflow_execution_failed_event_attributes", None)
        failure = _extract_failure(getattr(attrs, "failure", None) if attrs else None)
        close_time = _format_timestamp(getattr(failed_event, "event_time", None))
    elif timed_out_event:
        status = "TIMED_OUT"
        close_time = _format_timestamp(getattr(timed_out_event, "event_time", None))
    elif canceled_event:
        status = "CANCELED"
        close_time = _format_timestamp(getattr(canceled_event, "event_time", None))
    elif terminated_event:
        status = "TERMINATED"
        close_time = _format_timestamp(getattr(terminated_event, "event_time", None))

    start_time = _format_timestamp(getattr(start_event, "event_time", None)) or ""

    activity_groups = group_activity_events(filtered_events)
    timeline = _build_timeline(activity_groups, detail_level, truncate_at)

    signals = _extract_signals(events, truncate_at)
    timers = _extract_timers(events)
    child_workflows = _extract_child_workflows(events)

    history = WorkflowHistory(
        workflow_id=workflow_id,
        run_id=run_id,
        workflow_type=workflow_type,
        status=status,
        start_time=start_time,
        close_time=close_time,
        input=workflow_input,
        result=result,
        timeline=timeline,
        signals_received=signals,
        timers_fired=timers,
        child_workflows=child_workflows,
        failure=failure,
    )

    if len(events) > 10000:
        history.warning = f"This workflow has {len(events)} events. The summary may take a moment to generate."

    return history


def _find_event(events: list[Any], event_type: str) -> Any | None:
    for e in events:
        if resolve_event_type(e) == event_type:
            return e
    return None


def _build_timeline(
    groups: dict[str, Any],
    detail_level: str,
    truncate_at: int | None,
) -> list[TimelineStep]:
    timeline: list[TimelineStep] = []
    step = 0

    for group in groups.values():
        step += 1
        scheduled_attrs = getattr(
            getattr(group, "scheduled", None),
            "activity_task_scheduled_event_attributes",
            None,
        )

        scheduled_time = getattr(group.scheduled, "event_time", None) if group.scheduled else None
        end_event = group.completed or group.failed or group.timed_out or group.canceled
        end_time = getattr(end_event, "event_time", None) if end_event else None

        duration_ms = _compute_duration_ms(scheduled_time, end_time)

        input_val = decode_single_payload(
            getattr(scheduled_attrs, "input", None) if scheduled_attrs else None,
            truncate_at,
        )

        activity_status = "scheduled"
        output: Any = None
        failure_msg: str | None = None
        retries: int | None = None

        if group.completed:
            activity_status = "completed"
            attrs = getattr(group.completed, "activity_task_completed_event_attributes", None)
            output = decode_single_payload(getattr(attrs, "result", None) if attrs else None, truncate_at)
        elif group.failed:
            activity_status = "failed"
            attrs = getattr(group.failed, "activity_task_failed_event_attributes", None)
            failure_obj = getattr(attrs, "failure", None) if attrs else None
            failure_msg = _extract_failure_message(failure_obj)
        elif group.timed_out:
            activity_status = "timed_out"
        elif group.canceled:
            activity_status = "canceled"
        elif group.started:
            activity_status = "started"

        started_attrs = getattr(
            getattr(group, "started", None),
            "activity_task_started_event_attributes",
            None,
        )
        attempt = getattr(started_attrs, "attempt", 1) if started_attrs else 1
        if attempt > 1:
            retries = attempt - 1

        entry = TimelineStep(
            step=step,
            activity=group.activity_type,
            status=activity_status,
            duration_ms=int(duration_ms) if duration_ms is not None else None,
            retries=retries if retries else None,
        )

        if detail_level == "summary":
            entry.input_summary = _summarize_value(input_val)
            entry.output_summary = _summarize_value(output)
        else:
            entry.input = input_val
            entry.output = output

        if failure_msg:
            entry.failure = failure_msg

        timeline.append(entry)

    return timeline


def _build_full_history(
    workflow_id: str,
    run_id: str,
    events: list[Any],
) -> WorkflowHistory:
    filtered = filter_internal_events(events)

    start_event = _find_event(events, "WorkflowExecutionStarted")
    start_attrs = getattr(start_event, "workflow_execution_started_event_attributes", None)
    wf_type_obj = getattr(start_attrs, "workflow_type", None) if start_attrs else None
    workflow_type = getattr(wf_type_obj, "name", None) or "Unknown"

    timeline = [
        TimelineStep(
            step=i + 1,
            activity=resolve_event_type(event),
            status="event",
            duration_ms=None,
            input=_event_to_dict(event),
        )
        for i, event in enumerate(filtered)
    ]

    return WorkflowHistory(
        workflow_id=workflow_id,
        run_id=run_id,
        workflow_type=workflow_type,
        status="FULL_HISTORY",
        start_time=_format_timestamp(getattr(start_event, "event_time", None)) or "",
        close_time=None,
        input=decode_single_payload(getattr(start_attrs, "input", None) if start_attrs else None),
        result=None,
        timeline=timeline,
        signals_received=[],
        timers_fired=[],
        child_workflows=[],
        failure=None,
        warning=f"Full history with {len(events)} events ({len(filtered)} after filtering internal events).",
    )


def _extract_signals(events: list[Any], truncate_at: int | None) -> list[dict[str, Any]]:
    signals = []
    for e in events:
        if resolve_event_type(e) != "WorkflowExecutionSignaled":
            continue
        attrs = getattr(e, "workflow_execution_signaled_event_attributes", None)
        signals.append({
            "name": getattr(attrs, "signal_name", "unknown") if attrs else "unknown",
            "time": _format_timestamp(getattr(e, "event_time", None)) or "",
            "input": decode_single_payload(getattr(attrs, "input", None) if attrs else None, truncate_at),
        })
    return signals


def _extract_timers(events: list[Any]) -> list[dict[str, str]]:
    timer_starts: dict[str, Any] = {}

    for e in events:
        if resolve_event_type(e) == "TimerStarted":
            attrs = getattr(e, "timer_started_event_attributes", None)
            timer_id = getattr(attrs, "timer_id", "") if attrs else ""
            if timer_id:
                timer_starts[timer_id] = e

    timers = []
    for e in events:
        if resolve_event_type(e) != "TimerFired":
            continue
        attrs = getattr(e, "timer_fired_event_attributes", None)
        timer_id = getattr(attrs, "timer_id", "unknown") if attrs else "unknown"
        start_event = timer_starts.get(timer_id)
        start_attrs = getattr(start_event, "timer_started_event_attributes", None) if start_event else None
        duration = _format_duration(
            getattr(start_attrs, "start_to_fire_timeout", None) if start_attrs else None
        )
        timers.append({
            "timer_id": timer_id,
            "duration": duration,
            "fired_time": _format_timestamp(getattr(e, "event_time", None)) or "",
        })
    return timers


def _extract_child_workflows(events: list[Any]) -> list[dict[str, str]]:
    children: dict[str, dict[str, str]] = {}

    for e in events:
        event_type = resolve_event_type(e)

        if event_type == "StartChildWorkflowExecutionInitiated":
            attrs = getattr(e, "start_child_workflow_execution_initiated_event_attributes", None)
            if not attrs:
                continue
            wf_id = getattr(attrs, "workflow_id", "") or ""
            wf_type_obj = getattr(attrs, "workflow_type", None)
            wf_type = getattr(wf_type_obj, "name", None) or "Unknown"
            children[wf_id] = {
                "workflow_id": wf_id,
                "workflow_type": wf_type,
                "status": "initiated",
            }
        elif event_type == "ChildWorkflowExecutionStarted":
            attrs = getattr(e, "child_workflow_execution_started_event_attributes", None)
            if not attrs:
                continue
            we = getattr(attrs, "workflow_execution", None)
            wf_id = getattr(we, "workflow_id", "") if we else ""
            if wf_id in children:
                children[wf_id]["status"] = "started"
        elif event_type == "ChildWorkflowExecutionCompleted":
            attrs = getattr(e, "child_workflow_execution_completed_event_attributes", None)
            if not attrs:
                continue
            we = getattr(attrs, "workflow_execution", None)
            wf_id = getattr(we, "workflow_id", "") if we else ""
            if wf_id in children:
                children[wf_id]["status"] = "completed"
        elif event_type == "ChildWorkflowExecutionFailed":
            attrs = getattr(e, "child_workflow_execution_failed_event_attributes", None)
            if not attrs:
                continue
            we = getattr(attrs, "workflow_execution", None)
            wf_id = getattr(we, "workflow_id", "") if we else ""
            if wf_id in children:
                children[wf_id]["status"] = "failed"

    return list(children.values())


# --- Utility Functions ---


def _format_timestamp(ts: Any) -> str | None:
    """Format a protobuf Timestamp or datetime to ISO string."""
    if ts is None:
        return None
    # temporalio Python SDK returns datetime objects for event_time
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    # Fallback for raw protobuf timestamp
    if hasattr(ts, "seconds"):
        from datetime import datetime, timezone
        seconds = int(ts.seconds) if ts.seconds else 0
        nanos = int(ts.nanos) if hasattr(ts, "nanos") and ts.nanos else 0
        dt = datetime.fromtimestamp(seconds + nanos / 1e9, tz=timezone.utc)
        return dt.isoformat()
    return None


def _compute_duration_ms(start: Any, end: Any) -> float | None:
    """Compute duration in milliseconds between two timestamps."""
    start_ms = _timestamp_to_ms(start)
    end_ms = _timestamp_to_ms(end)
    if start_ms is None or end_ms is None:
        return None
    return end_ms - start_ms


def _timestamp_to_ms(ts: Any) -> float | None:
    if ts is None:
        return None
    if hasattr(ts, "timestamp"):
        return ts.timestamp() * 1000
    if hasattr(ts, "seconds"):
        seconds = int(ts.seconds) if ts.seconds else 0
        nanos = int(ts.nanos) if hasattr(ts, "nanos") and ts.nanos else 0
        return seconds * 1000 + nanos / 1_000_000
    return None


def _format_duration(duration: Any) -> str:
    if duration is None:
        return "unknown"
    if hasattr(duration, "total_seconds"):
        seconds = int(duration.total_seconds())
    elif hasattr(duration, "seconds"):
        seconds = int(duration.seconds) if duration.seconds else 0
    else:
        return "unknown"

    if seconds >= 3600:
        return f"{round(seconds / 3600)}h"
    if seconds >= 60:
        return f"{round(seconds / 60)}m"
    return f"{seconds}s"


def _extract_failure(failure: Any) -> Any:
    if failure is None:
        return None
    return {
        "message": getattr(failure, "message", None) or "Unknown error",
        "type": getattr(failure, "type", None) or getattr(failure, "source", None) or "unknown",
        "stackTrace": getattr(failure, "stack_trace", None) or None,
        "cause": _extract_failure(getattr(failure, "cause", None)),
    }


def _extract_failure_message(failure: Any) -> str:
    if failure is None:
        return "Unknown error"
    return getattr(failure, "message", None) or "Unknown error"


def _summarize_value(value: Any) -> str:
    if value is None:
        return "null"
    text = json.dumps(value, default=str)
    if len(text) <= 200:
        return text
    return text[:197] + "..."


def _event_to_dict(event: Any) -> Any:
    """Best-effort convert an event to a serializable dict."""
    if hasattr(event, "__dict__"):
        return str(event)
    return str(event)
