"""Event processing: filtering, history summarization, and execution diffing."""

from __future__ import annotations

import json
from typing import Any

from .client import decode_payloads, format_duration, format_timestamp, timestamp_to_ms

# --- Event Type Resolution ---

EVENT_TYPE_MAP: dict[int, str] = {
    1: "WorkflowExecutionStarted", 2: "WorkflowExecutionCompleted",
    3: "WorkflowExecutionFailed", 4: "WorkflowExecutionTimedOut",
    5: "WorkflowTaskScheduled", 6: "WorkflowTaskStarted",
    7: "WorkflowTaskCompleted", 8: "WorkflowTaskTimedOut",
    9: "WorkflowTaskFailed", 10: "ActivityTaskScheduled",
    11: "ActivityTaskStarted", 12: "ActivityTaskCompleted",
    13: "ActivityTaskFailed", 14: "ActivityTaskTimedOut",
    15: "ActivityTaskCancelRequested", 16: "ActivityTaskCanceled",
    17: "TimerStarted", 18: "TimerFired", 19: "TimerCanceled",
    20: "WorkflowExecutionCancelRequested", 21: "WorkflowExecutionCanceled",
    22: "RequestCancelExternalWorkflowExecutionInitiated",
    23: "RequestCancelExternalWorkflowExecutionFailed",
    24: "ExternalWorkflowExecutionCancelRequested",
    25: "MarkerRecorded", 26: "WorkflowExecutionSignaled",
    27: "WorkflowExecutionTerminated", 28: "WorkflowExecutionContinuedAsNew",
    29: "StartChildWorkflowExecutionInitiated",
    30: "StartChildWorkflowExecutionFailed",
    31: "ChildWorkflowExecutionStarted", 32: "ChildWorkflowExecutionCompleted",
    33: "ChildWorkflowExecutionFailed", 34: "ChildWorkflowExecutionCanceled",
    35: "ChildWorkflowExecutionTimedOut", 36: "ChildWorkflowExecutionTerminated",
    37: "SignalExternalWorkflowExecutionInitiated",
    38: "SignalExternalWorkflowExecutionFailed",
    39: "ExternalWorkflowExecutionSignaled",
    40: "UpsertWorkflowSearchAttributes",
}

INTERNAL_EVENT_TYPES = frozenset({
    "WorkflowTaskScheduled", "WorkflowTaskStarted", "WorkflowTaskCompleted",
    "WorkflowTaskFailed", "WorkflowTaskTimedOut",
})

# Maps activity lifecycle events to (attribute_name, group_key).
ACTIVITY_LIFECYCLE = {
    "ActivityTaskStarted": ("activity_task_started_event_attributes", "started"),
    "ActivityTaskCompleted": ("activity_task_completed_event_attributes", "completed"),
    "ActivityTaskFailed": ("activity_task_failed_event_attributes", "failed"),
    "ActivityTaskTimedOut": ("activity_task_timed_out_event_attributes", "timed_out"),
    "ActivityTaskCanceled": ("activity_task_canceled_event_attributes", "canceled"),
}

SUMMARY_TRUNCATE_BYTES = 10240

# Terminal workflow event types mapped to (status_name, attributes_accessor).
TERMINAL_EVENTS = {
    "WorkflowExecutionCompleted": ("COMPLETED", "workflow_execution_completed_event_attributes"),
    "WorkflowExecutionFailed": ("FAILED", "workflow_execution_failed_event_attributes"),
    "WorkflowExecutionTimedOut": ("TIMED_OUT", None),
    "WorkflowExecutionCanceled": ("CANCELED", None),
    "WorkflowExecutionTerminated": ("TERMINATED", None),
}


def _event_type(event: Any) -> str:
    et = getattr(event, "event_type", None)
    if et is not None:
        return EVENT_TYPE_MAP.get(int(et), f"UnknownEventType({et})")
    return "Unknown"


def _find(events: list[Any], type_name: str) -> Any | None:
    for e in events:
        if _event_type(e) == type_name:
            return e
    return None


def _attr(obj: Any, *path: str) -> Any:
    """Safe nested attribute access: _attr(event, 'foo_attributes', 'bar', 'name')"""
    for p in path:
        if obj is None:
            return None
        obj = getattr(obj, p, None)
    return obj


def _summarize(value: Any) -> str:
    if value is None:
        return "null"
    text = json.dumps(value, default=str)
    return text if len(text) <= 200 else text[:197] + "..."


def _extract_failure(failure: Any) -> Any:
    if failure is None:
        return None
    return {
        "message": getattr(failure, "message", None) or "Unknown error",
        "type": getattr(failure, "type", None) or getattr(failure, "source", None) or "unknown",
        "stackTrace": getattr(failure, "stack_trace", None),
        "cause": _extract_failure(getattr(failure, "cause", None)),
    }


# --- Activity Grouping ---


def _group_activities(events: list[Any]) -> list[dict[str, Any]]:
    """Group events by activity into ordered dicts with scheduled/started/completed/failed etc."""
    groups: dict[str, dict[str, Any]] = {}
    scheduled_index: dict[str, str] = {}  # event_id -> activity_id

    for event in events:
        et = _event_type(event)

        if et == "ActivityTaskScheduled":
            attrs = _attr(event, "activity_task_scheduled_event_attributes")
            aid = _attr(attrs, "activity_id") or ""
            if not aid:
                continue
            atype = _attr(attrs, "activity_type", "name") or "Unknown"
            groups.setdefault(aid, {"activity_type": atype, "activity_id": aid})
            groups[aid]["scheduled"] = event
            scheduled_index[str(getattr(event, "event_id", ""))] = aid
            continue

        mapping = ACTIVITY_LIFECYCLE.get(et)
        if not mapping:
            continue
        attr_name, key = mapping
        attrs = getattr(event, attr_name, None)
        if not attrs:
            continue
        sid = str(getattr(attrs, "scheduled_event_id", "") or "")
        aid = scheduled_index.get(sid)
        if aid and aid in groups:
            groups[aid][key] = event

    return list(groups.values())


# --- History Summarization ---


def summarize_history(
    workflow_id: str,
    run_id: str,
    events: list[Any],
    detail_level: str = "summary",
    event_types: list[str] | None = None,
) -> dict[str, Any]:
    """Transform raw Temporal event history into a structured summary."""
    if detail_level == "full":
        return _build_full_history(workflow_id, run_id, events)

    filtered = events
    if event_types:
        type_set = {t.lower() for t in event_types}
        filtered = [e for e in events if _event_type(e).lower() in type_set]

    start_event = _find(events, "WorkflowExecutionStarted")
    start_attrs = _attr(start_event, "workflow_execution_started_event_attributes")
    workflow_type = _attr(start_attrs, "workflow_type", "name") or "Unknown"

    truncate_at = SUMMARY_TRUNCATE_BYTES if detail_level == "summary" else None
    wf_input = decode_payloads(_attr(start_attrs, "input", "payloads"), truncate_at)

    # Determine terminal status
    status, result, failure, close_time = "RUNNING", None, None, None
    for event in events:
        et = _event_type(event)
        terminal = TERMINAL_EVENTS.get(et)
        if not terminal:
            continue
        status, attrs_name = terminal
        close_time = format_timestamp(getattr(event, "event_time", None))
        if status == "COMPLETED" and attrs_name:
            attrs = getattr(event, attrs_name, None)
            result = decode_payloads(_attr(attrs, "result", "payloads"), truncate_at)
        elif status == "FAILED" and attrs_name:
            attrs = getattr(event, attrs_name, None)
            failure = _extract_failure(_attr(attrs, "failure"))
        break

    history: dict[str, Any] = {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "workflow_type": workflow_type,
        "status": status,
        "start_time": format_timestamp(getattr(start_event, "event_time", None)) or "",
        "close_time": close_time,
        "input": wf_input,
        "result": result,
        "timeline": _build_timeline(_group_activities(filtered), detail_level, truncate_at),
        "signals_received": _extract_signals(events, truncate_at),
        "timers_fired": _extract_timers(events),
        "child_workflows": _extract_child_workflows(events),
        "failure": failure,
    }

    if len(events) > 10000:
        history["warning"] = f"This workflow has {len(events)} events."

    return history


def _build_timeline(
    groups: list[dict[str, Any]],
    detail_level: str,
    truncate_at: int | None,
) -> list[dict[str, Any]]:
    timeline = []

    for i, g in enumerate(groups, 1):
        sched = g.get("scheduled")
        sched_attrs = _attr(sched, "activity_task_scheduled_event_attributes") if sched else None
        sched_time = getattr(sched, "event_time", None) if sched else None
        end_ev = g.get("completed") or g.get("failed") or g.get("timed_out") or g.get("canceled")
        end_time = getattr(end_ev, "event_time", None) if end_ev else None

        s_ms = timestamp_to_ms(sched_time)
        e_ms = timestamp_to_ms(end_time)
        duration_ms = int(e_ms - s_ms) if s_ms is not None and e_ms is not None else None

        input_val = decode_payloads(_attr(sched_attrs, "input", "payloads"), truncate_at)

        # Determine activity status and output/failure
        act_status, output, fail_msg = "scheduled", None, None
        if g.get("completed"):
            act_status = "completed"
            attrs = _attr(g["completed"], "activity_task_completed_event_attributes")
            output = decode_payloads(_attr(attrs, "result", "payloads"), truncate_at)
        elif g.get("failed"):
            act_status = "failed"
            attrs = _attr(g["failed"], "activity_task_failed_event_attributes")
            fail_msg = getattr(_attr(attrs, "failure"), "message", None) or "Unknown error"
        elif g.get("timed_out"):
            act_status = "timed_out"
        elif g.get("canceled"):
            act_status = "canceled"
        elif g.get("started"):
            act_status = "started"

        attempt = _attr(g.get("started"), "activity_task_started_event_attributes", "attempt") or 1
        retries = int(attempt) - 1 if int(attempt) > 1 else None

        entry: dict[str, Any] = {
            "step": i,
            "activity": g["activity_type"],
            "status": act_status,
            "duration_ms": duration_ms,
        }
        if retries:
            entry["retries"] = retries
        if detail_level == "summary":
            entry["input_summary"] = _summarize(input_val)
            entry["output_summary"] = _summarize(output)
        else:
            entry["input"] = input_val
            entry["output"] = output
        if fail_msg:
            entry["failure"] = fail_msg

        timeline.append(entry)

    return timeline


def _build_full_history(wf_id: str, run_id: str, events: list[Any]) -> dict[str, Any]:
    filtered = [e for e in events if _event_type(e) not in INTERNAL_EVENT_TYPES]
    start = _find(events, "WorkflowExecutionStarted")
    start_attrs = _attr(start, "workflow_execution_started_event_attributes")

    return {
        "workflow_id": wf_id,
        "run_id": run_id,
        "workflow_type": _attr(start_attrs, "workflow_type", "name") or "Unknown",
        "status": "FULL_HISTORY",
        "start_time": format_timestamp(getattr(start, "event_time", None)) or "",
        "close_time": None,
        "input": decode_payloads(_attr(start_attrs, "input", "payloads")),
        "result": None,
        "timeline": [
            {"step": i + 1, "activity": _event_type(e), "status": "event", "duration_ms": None, "input": str(e)}
            for i, e in enumerate(filtered)
        ],
        "signals_received": [], "timers_fired": [], "child_workflows": [],
        "failure": None,
        "warning": f"Full history with {len(events)} events ({len(filtered)} after filtering internal events).",
    }


def _extract_signals(events: list[Any], truncate_at: int | None) -> list[dict[str, Any]]:
    return [
        {
            "name": _attr(e, "workflow_execution_signaled_event_attributes", "signal_name") or "unknown",
            "time": format_timestamp(getattr(e, "event_time", None)) or "",
            "input": decode_payloads(
                _attr(e, "workflow_execution_signaled_event_attributes", "input", "payloads"),
                truncate_at,
            ),
        }
        for e in events if _event_type(e) == "WorkflowExecutionSignaled"
    ]


def _extract_timers(events: list[Any]) -> list[dict[str, str]]:
    starts: dict[str, Any] = {}
    for e in events:
        if _event_type(e) == "TimerStarted":
            tid = _attr(e, "timer_started_event_attributes", "timer_id") or ""
            if tid:
                starts[tid] = e

    return [
        {
            "timer_id": _attr(e, "timer_fired_event_attributes", "timer_id") or "unknown",
            "duration": format_duration(
                _attr(starts.get(_attr(e, "timer_fired_event_attributes", "timer_id") or ""),
                      "timer_started_event_attributes", "start_to_fire_timeout")
            ),
            "fired_time": format_timestamp(getattr(e, "event_time", None)) or "",
        }
        for e in events if _event_type(e) == "TimerFired"
    ]


def _extract_child_workflows(events: list[Any]) -> list[dict[str, str]]:
    children: dict[str, dict[str, str]] = {}
    event_handlers: dict[str, tuple[str, str, str]] = {
        "StartChildWorkflowExecutionInitiated": (
            "start_child_workflow_execution_initiated_event_attributes", "workflow_id", "initiated"),
        "ChildWorkflowExecutionStarted": (
            "child_workflow_execution_started_event_attributes", "workflow_execution", "started"),
        "ChildWorkflowExecutionCompleted": (
            "child_workflow_execution_completed_event_attributes", "workflow_execution", "completed"),
        "ChildWorkflowExecutionFailed": (
            "child_workflow_execution_failed_event_attributes", "workflow_execution", "failed"),
    }

    for e in events:
        handler = event_handlers.get(_event_type(e))
        if not handler:
            continue
        attr_name, id_path, new_status = handler
        attrs = getattr(e, attr_name, None)
        if not attrs:
            continue

        if id_path == "workflow_id":
            wf_id = getattr(attrs, "workflow_id", "") or ""
            wf_type = _attr(attrs, "workflow_type", "name") or "Unknown"
            children[wf_id] = {"workflow_id": wf_id, "workflow_type": wf_type, "status": new_status}
        else:
            we = getattr(attrs, id_path, None)
            wf_id = getattr(we, "workflow_id", "") if we else ""
            if wf_id in children:
                children[wf_id]["status"] = new_status

    return list(children.values())


# --- Execution Diffing ---


def diff_executions(history_a: dict, history_b: dict) -> dict[str, Any]:
    """Compare two workflow histories and return divergences."""
    tl_a, tl_b = history_a["timeline"], history_b["timeline"]
    return {
        "divergences": _find_data_divergences(tl_a, tl_b),
        "structural_differences": _find_structural_diffs(tl_a, tl_b),
        "signals": _find_signal_diffs(history_a, history_b),
    }


def _find_data_divergences(tl_a: list, tl_b: list) -> list[dict]:
    divergences = []
    used_b: set[int] = set()

    for step_a in tl_a:
        step_b = None
        for i, sb in enumerate(tl_b):
            if i not in used_b and sb["activity"] == step_a["activity"]:
                step_b = sb
                used_b.add(i)
                break
        if step_b is None:
            continue

        # Compare input, output, status, retries
        for field in ("input", "output"):
            val_a = step_a.get(field) or step_a.get(f"{field}_summary")
            val_b = step_b.get(field) or step_b.get(f"{field}_summary")
            for d in _deep_diff(val_a, val_b, field):
                divergences.append({
                    "step": step_a["step"], "activity": step_a["activity"], **d
                })

        if step_a["status"] != step_b["status"]:
            divergences.append({
                "step": step_a["step"], "activity": step_a["activity"],
                "field": "status", "value_a": step_a["status"], "value_b": step_b["status"],
                "note": f"Activity {step_a['activity']} has different status in each execution",
            })

        if (step_a.get("retries") or 0) != (step_b.get("retries") or 0):
            divergences.append({
                "step": step_a["step"], "activity": step_a["activity"],
                "field": "retries", "value_a": step_a.get("retries", 0), "value_b": step_b.get("retries", 0),
                "note": f"Different retry counts for {step_a['activity']}",
            })

    return divergences


def _find_structural_diffs(tl_a: list, tl_b: list) -> dict:
    types_a = [s["activity"] for s in tl_a]
    types_b = [s["activity"] for s in tl_b]
    set_a, set_b = set(types_a), set(types_b)

    common_a = [t for t in types_a if t in set_b]
    common_b = [t for t in types_b if t in set_a]

    return {
        "activities_only_in_a": list(set_a - set_b),
        "activities_only_in_b": list(set_b - set_a),
        "different_execution_order": common_a != common_b and bool(common_a),
    }


def _find_signal_diffs(ha: dict, hb: dict) -> dict:
    sigs_a = {s["name"] for s in ha.get("signals_received", [])}
    sigs_b = {s["name"] for s in hb.get("signals_received", [])}
    return {
        "signals_only_in_a": list(sigs_a - sigs_b),
        "signals_only_in_b": list(sigs_b - sigs_a),
    }


def _deep_diff(a: Any, b: Any, base: str) -> list[dict]:
    if a == b:
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        results = []
        for key in set(a) | set(b):
            results.extend(_deep_diff(a.get(key), b.get(key), f"{base}.{key}"))
        return results
    if isinstance(a, list) and isinstance(b, list):
        results = []
        for i in range(max(len(a), len(b))):
            results.extend(_deep_diff(
                a[i] if i < len(a) else None,
                b[i] if i < len(b) else None,
                f"{base}[{i}]",
            ))
        return results
    return [{"field": base, "value_a": a, "value_b": b, "note": f"Different values at {base}"}]
