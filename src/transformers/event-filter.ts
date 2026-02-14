import type { temporal } from "@temporalio/proto";

type HistoryEvent = temporal.api.history.v1.IHistoryEvent;

/**
 * Event types that are typically noise for debugging purposes.
 * These are internal Temporal bookkeeping events.
 */
const INTERNAL_EVENT_TYPES = new Set([
  "WorkflowTaskScheduled",
  "WorkflowTaskStarted",
  "WorkflowTaskCompleted",
  "WorkflowTaskFailed",
  "WorkflowTaskTimedOut",
]);

/**
 * Filter events to only the types the user requested.
 */
export function filterByEventTypes(
  events: HistoryEvent[],
  eventTypes: string[]
): HistoryEvent[] {
  const typeSet = new Set(eventTypes.map((t) => t.toLowerCase()));
  return events.filter((event) => {
    const eventType = resolveEventType(event);
    return typeSet.has(eventType.toLowerCase());
  });
}

/**
 * Remove internal Temporal bookkeeping events that add noise.
 */
export function filterInternalEvents(events: HistoryEvent[]): HistoryEvent[] {
  return events.filter((event) => {
    const eventType = resolveEventType(event);
    return !INTERNAL_EVENT_TYPES.has(eventType);
  });
}

/**
 * Extract the event type string from a history event.
 * Temporal events use eventType as an enum string.
 */
export function resolveEventType(event: HistoryEvent): string {
  if (event.eventType != null) {
    // eventType is a numeric enum from protobuf
    return eventTypeNumberToName(event.eventType as number);
  }
  return "Unknown";
}

/**
 * Map Temporal event type numbers to readable names.
 */
function eventTypeNumberToName(num: number): string {
  const mapping: Record<number, string> = {
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
  };
  return mapping[num] || `UnknownEventType(${num})`;
}

/**
 * Group events by activity, pairing scheduled/started/completed/failed events.
 */
export interface ActivityEventGroup {
  activityType: string;
  activityId: string;
  scheduled?: HistoryEvent;
  started?: HistoryEvent;
  completed?: HistoryEvent;
  failed?: HistoryEvent;
  timedOut?: HistoryEvent;
  canceled?: HistoryEvent;
}

export function groupActivityEvents(
  events: HistoryEvent[]
): Map<string, ActivityEventGroup> {
  const groups = new Map<string, ActivityEventGroup>();

  for (const event of events) {
    const eventType = resolveEventType(event);
    let activityId: string | undefined;
    let attrs: Record<string, unknown> | undefined;

    if (eventType === "ActivityTaskScheduled") {
      attrs = event.activityTaskScheduledEventAttributes as Record<string, unknown> | undefined;
      activityId = attrs?.activityId as string | undefined;
      if (activityId) {
        const activityType =
          (attrs?.activityType as { name?: string })?.name || "Unknown";
        const group = groups.get(activityId) || {
          activityType,
          activityId,
        };
        group.scheduled = event;
        groups.set(activityId, group);
      }
    } else if (eventType === "ActivityTaskStarted") {
      attrs = event.activityTaskStartedEventAttributes as Record<string, unknown> | undefined;
      const scheduledId = String(attrs?.scheduledEventId || "");
      // Find the group by matching scheduledEventId
      for (const [id, group] of groups) {
        if (
          group.scheduled &&
          String(group.scheduled.eventId) === scheduledId
        ) {
          group.started = event;
          break;
        }
      }
    } else if (eventType === "ActivityTaskCompleted") {
      attrs = event.activityTaskCompletedEventAttributes as Record<string, unknown> | undefined;
      const scheduledId = String(attrs?.scheduledEventId || "");
      for (const [id, group] of groups) {
        if (
          group.scheduled &&
          String(group.scheduled.eventId) === scheduledId
        ) {
          group.completed = event;
          break;
        }
      }
    } else if (eventType === "ActivityTaskFailed") {
      attrs = event.activityTaskFailedEventAttributes as Record<string, unknown> | undefined;
      const scheduledId = String(attrs?.scheduledEventId || "");
      for (const [id, group] of groups) {
        if (
          group.scheduled &&
          String(group.scheduled.eventId) === scheduledId
        ) {
          group.failed = event;
          break;
        }
      }
    } else if (eventType === "ActivityTaskTimedOut") {
      attrs = event.activityTaskTimedOutEventAttributes as Record<string, unknown> | undefined;
      const scheduledId = String(attrs?.scheduledEventId || "");
      for (const [id, group] of groups) {
        if (
          group.scheduled &&
          String(group.scheduled.eventId) === scheduledId
        ) {
          group.timedOut = event;
          break;
        }
      }
    } else if (eventType === "ActivityTaskCanceled") {
      attrs = event.activityTaskCanceledEventAttributes as Record<string, unknown> | undefined;
      const scheduledId = String(attrs?.scheduledEventId || "");
      for (const [id, group] of groups) {
        if (
          group.scheduled &&
          String(group.scheduled.eventId) === scheduledId
        ) {
          group.canceled = event;
          break;
        }
      }
    }
  }

  return groups;
}
