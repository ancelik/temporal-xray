from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Event types that are internal Temporal bookkeeping noise.
INTERNAL_EVENT_TYPES = frozenset({
    "WorkflowTaskScheduled",
    "WorkflowTaskStarted",
    "WorkflowTaskCompleted",
    "WorkflowTaskFailed",
    "WorkflowTaskTimedOut",
})

# Maps Temporal event type enum values to readable names.
EVENT_TYPE_MAP: dict[int, str] = {
    1: "WorkflowExecutionStarted",
    2: "WorkflowExecutionCompleted",
    3: "WorkflowExecutionFailed",
    4: "WorkflowExecutionTimedOut",
    5: "WorkflowTaskScheduled",
    6: "WorkflowTaskStarted",
    7: "WorkflowTaskCompleted",
    8: "WorkflowTaskTimedOut",
    9: "WorkflowTaskFailed",
    10: "ActivityTaskScheduled",
    11: "ActivityTaskStarted",
    12: "ActivityTaskCompleted",
    13: "ActivityTaskFailed",
    14: "ActivityTaskTimedOut",
    15: "ActivityTaskCancelRequested",
    16: "ActivityTaskCanceled",
    17: "TimerStarted",
    18: "TimerFired",
    19: "TimerCanceled",
    20: "WorkflowExecutionCancelRequested",
    21: "WorkflowExecutionCanceled",
    22: "RequestCancelExternalWorkflowExecutionInitiated",
    23: "RequestCancelExternalWorkflowExecutionFailed",
    24: "ExternalWorkflowExecutionCancelRequested",
    25: "MarkerRecorded",
    26: "WorkflowExecutionSignaled",
    27: "WorkflowExecutionTerminated",
    28: "WorkflowExecutionContinuedAsNew",
    29: "StartChildWorkflowExecutionInitiated",
    30: "StartChildWorkflowExecutionFailed",
    31: "ChildWorkflowExecutionStarted",
    32: "ChildWorkflowExecutionCompleted",
    33: "ChildWorkflowExecutionFailed",
    34: "ChildWorkflowExecutionCanceled",
    35: "ChildWorkflowExecutionTimedOut",
    36: "ChildWorkflowExecutionTerminated",
    37: "SignalExternalWorkflowExecutionInitiated",
    38: "SignalExternalWorkflowExecutionFailed",
    39: "ExternalWorkflowExecutionSignaled",
    40: "UpsertWorkflowSearchAttributes",
}

# Maps activity lifecycle events to their attribute name and group field.
ACTIVITY_LIFECYCLE_EVENTS: dict[str, tuple[str, str]] = {
    "ActivityTaskStarted": ("activity_task_started_event_attributes", "started"),
    "ActivityTaskCompleted": ("activity_task_completed_event_attributes", "completed"),
    "ActivityTaskFailed": ("activity_task_failed_event_attributes", "failed"),
    "ActivityTaskTimedOut": ("activity_task_timed_out_event_attributes", "timed_out"),
    "ActivityTaskCanceled": ("activity_task_canceled_event_attributes", "canceled"),
}


def resolve_event_type(event: Any) -> str:
    """Extract the event type string from a history event."""
    event_type = getattr(event, "event_type", None)
    if event_type is not None:
        num = int(event_type) if not isinstance(event_type, int) else event_type
        return EVENT_TYPE_MAP.get(num, f"UnknownEventType({num})")
    return "Unknown"


def filter_by_event_types(events: list[Any], event_types: list[str]) -> list[Any]:
    """Filter events to only the types the user requested."""
    type_set = {t.lower() for t in event_types}
    return [e for e in events if resolve_event_type(e).lower() in type_set]


def filter_internal_events(events: list[Any]) -> list[Any]:
    """Remove internal Temporal bookkeeping events."""
    return [e for e in events if resolve_event_type(e) not in INTERNAL_EVENT_TYPES]


@dataclass
class ActivityEventGroup:
    activity_type: str
    activity_id: str
    scheduled: Any = None
    started: Any = None
    completed: Any = None
    failed: Any = None
    timed_out: Any = None
    canceled: Any = None


def group_activity_events(events: list[Any]) -> dict[str, ActivityEventGroup]:
    """Group events by activity, pairing scheduled/started/completed/failed events."""
    groups: dict[str, ActivityEventGroup] = {}
    scheduled_event_index: dict[str, str] = {}  # event_id -> activity_id

    for event in events:
        event_type = resolve_event_type(event)

        if event_type == "ActivityTaskScheduled":
            attrs = getattr(event, "activity_task_scheduled_event_attributes", None)
            if attrs is None:
                continue
            activity_id = getattr(attrs, "activity_id", None) or ""
            if not activity_id:
                continue
            activity_type_obj = getattr(attrs, "activity_type", None)
            activity_type = getattr(activity_type_obj, "name", None) or "Unknown"
            if activity_id not in groups:
                groups[activity_id] = ActivityEventGroup(
                    activity_type=activity_type, activity_id=activity_id
                )
            groups[activity_id].scheduled = event
            event_id = str(getattr(event, "event_id", ""))
            scheduled_event_index[event_id] = activity_id
            continue

        mapping = ACTIVITY_LIFECYCLE_EVENTS.get(event_type)
        if not mapping:
            continue

        attr_name, group_field = mapping
        attrs = getattr(event, attr_name, None)
        if attrs is None:
            continue
        scheduled_id = str(getattr(attrs, "scheduled_event_id", "") or "")
        activity_id = scheduled_event_index.get(scheduled_id)
        if activity_id and activity_id in groups:
            setattr(groups[activity_id], group_field, event)

    return groups
