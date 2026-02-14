import type { temporal } from "@temporalio/proto";
import { decodeSinglePayload, decodePayloads } from "../temporal-client.js";
import {
  resolveEventType,
  groupActivityEvents,
  filterInternalEvents,
  filterByEventTypes,
} from "./event-filter.js";
import type { TimelineStep, WorkflowHistory, Long } from "../types.js";

type HistoryEvent = temporal.api.history.v1.IHistoryEvent;

const SUMMARY_TRUNCATE_BYTES = 10240; // 10KB

interface SummarizeOptions {
  detailLevel: "summary" | "standard" | "full";
  eventTypes?: string[];
}

/**
 * Transform raw Temporal event history into a structured WorkflowHistory.
 */
export function summarizeHistory(
  workflowId: string,
  runId: string,
  events: HistoryEvent[],
  options: SummarizeOptions
): WorkflowHistory {
  const { detailLevel, eventTypes: filterTypes } = options;

  // If full detail, return a minimal transformation with all events
  if (detailLevel === "full") {
    return buildFullHistory(workflowId, runId, events);
  }

  // Apply event type filter if specified
  let filteredEvents = filterTypes
    ? filterByEventTypes(events, filterTypes)
    : events;

  // Extract workflow-level metadata from the start event
  const startEvent = events.find(
    (e) => resolveEventType(e) === "WorkflowExecutionStarted"
  );
  const completedEvent = events.find(
    (e) => resolveEventType(e) === "WorkflowExecutionCompleted"
  );
  const failedEvent = events.find(
    (e) => resolveEventType(e) === "WorkflowExecutionFailed"
  );
  const timedOutEvent = events.find(
    (e) => resolveEventType(e) === "WorkflowExecutionTimedOut"
  );
  const canceledEvent = events.find(
    (e) => resolveEventType(e) === "WorkflowExecutionCanceled"
  );
  const terminatedEvent = events.find(
    (e) => resolveEventType(e) === "WorkflowExecutionTerminated"
  );

  const startAttrs = startEvent?.workflowExecutionStartedEventAttributes as Record<string, unknown> | undefined;
  const workflowType =
    (startAttrs?.workflowType as { name?: string })?.name || "Unknown";
  const taskQueue =
    (startAttrs?.taskQueue as { name?: string })?.name || "unknown";

  const truncateAt = detailLevel === "summary" ? SUMMARY_TRUNCATE_BYTES : undefined;
  const workflowInput = decodeSinglePayload(
    startAttrs?.input as Parameters<typeof decodePayloads>[0],
    truncateAt
  );

  // Determine status and result
  let status = "RUNNING";
  let result: unknown = null;
  let failure: unknown = null;
  let closeTime: string | null = null;

  if (completedEvent) {
    status = "COMPLETED";
    const attrs = completedEvent.workflowExecutionCompletedEventAttributes as Record<string, unknown> | undefined;
    result = decodeSinglePayload(
      attrs?.result as Parameters<typeof decodePayloads>[0],
      truncateAt
    );
    closeTime = formatTimestamp(completedEvent.eventTime);
  } else if (failedEvent) {
    status = "FAILED";
    const attrs = failedEvent.workflowExecutionFailedEventAttributes as Record<string, unknown> | undefined;
    failure = extractFailure(attrs?.failure as Record<string, unknown> | undefined);
    closeTime = formatTimestamp(failedEvent.eventTime);
  } else if (timedOutEvent) {
    status = "TIMED_OUT";
    closeTime = formatTimestamp(timedOutEvent.eventTime);
  } else if (canceledEvent) {
    status = "CANCELED";
    closeTime = formatTimestamp(canceledEvent.eventTime);
  } else if (terminatedEvent) {
    status = "TERMINATED";
    closeTime = formatTimestamp(terminatedEvent.eventTime);
  }

  const startTime = formatTimestamp(startEvent?.eventTime) || "";

  // Build timeline from activity events
  const activityGroups = groupActivityEvents(filteredEvents);
  const timeline = buildTimeline(activityGroups, detailLevel, truncateAt);

  // Extract signals
  const signals = extractSignals(events, truncateAt);

  // Extract timers
  const timers = extractTimers(events);

  // Extract child workflows
  const childWorkflows = extractChildWorkflows(events);

  const history: WorkflowHistory = {
    workflow_id: workflowId,
    run_id: runId,
    workflow_type: workflowType,
    status,
    start_time: startTime,
    close_time: closeTime,
    input: workflowInput,
    result,
    timeline,
    signals_received: signals,
    timers_fired: timers,
    child_workflows: childWorkflows,
    failure,
  };

  if (events.length > 10000) {
    history.warning = `This workflow has ${events.length} events. The summary may take a moment to generate.`;
  }

  return history;
}

function buildTimeline(
  groups: Map<string, ReturnType<typeof groupActivityEvents> extends Map<string, infer V> ? V : never>,
  detailLevel: "summary" | "standard" | "full",
  truncateAt: number | undefined
): TimelineStep[] {
  const timeline: TimelineStep[] = [];
  let step = 0;

  for (const [, group] of groups) {
    step++;
    const scheduledAttrs = group.scheduled
      ?.activityTaskScheduledEventAttributes as Record<string, unknown> | undefined;

    const scheduledTime = group.scheduled?.eventTime;
    let endTime = group.completed?.eventTime ||
      group.failed?.eventTime ||
      group.timedOut?.eventTime ||
      group.canceled?.eventTime;

    const durationMs =
      scheduledTime && endTime
        ? computeDurationMs(scheduledTime, endTime)
        : null;

    const input = decodeSinglePayload(
      scheduledAttrs?.input as Parameters<typeof decodePayloads>[0],
      truncateAt
    );

    let activityStatus = "scheduled";
    let output: unknown = null;
    let failureMsg: string | undefined;
    let retries: number | undefined;

    if (group.completed) {
      activityStatus = "completed";
      const attrs = group.completed.activityTaskCompletedEventAttributes as Record<string, unknown> | undefined;
      output = decodeSinglePayload(
        attrs?.result as Parameters<typeof decodePayloads>[0],
        truncateAt
      );
    } else if (group.failed) {
      activityStatus = "failed";
      const attrs = group.failed.activityTaskFailedEventAttributes as Record<string, unknown> | undefined;
      failureMsg = extractFailureMessage(attrs?.failure as Record<string, unknown> | undefined);
    } else if (group.timedOut) {
      activityStatus = "timed_out";
    } else if (group.canceled) {
      activityStatus = "canceled";
    } else if (group.started) {
      activityStatus = "started";
    }

    // Retry count from the started event
    const startedAttrs = group.started
      ?.activityTaskStartedEventAttributes as Record<string, unknown> | undefined;
    const attempt = (startedAttrs?.attempt as number) || 1;
    if (attempt > 1) {
      retries = attempt - 1;
    }

    const entry: TimelineStep = {
      step,
      activity: group.activityType,
      status: activityStatus,
      duration_ms: durationMs,
    };

    if (retries) entry.retries = retries;

    if (detailLevel === "summary") {
      entry.input_summary = summarizeValue(input);
      entry.output_summary = summarizeValue(output);
    } else {
      entry.input = input;
      entry.output = output;
    }

    if (failureMsg) entry.failure = failureMsg;

    timeline.push(entry);
  }

  return timeline;
}

function buildFullHistory(
  workflowId: string,
  runId: string,
  events: HistoryEvent[]
): WorkflowHistory {
  // For full detail, include all events as the timeline with raw data
  const filtered = filterInternalEvents(events);

  const startEvent = events.find(
    (e) => resolveEventType(e) === "WorkflowExecutionStarted"
  );
  const startAttrs = startEvent?.workflowExecutionStartedEventAttributes as Record<string, unknown> | undefined;
  const workflowType =
    (startAttrs?.workflowType as { name?: string })?.name || "Unknown";

  const timeline: TimelineStep[] = filtered.map((event, i) => ({
    step: i + 1,
    activity: resolveEventType(event),
    status: "event",
    duration_ms: null,
    input: event,
  }));

  return {
    workflow_id: workflowId,
    run_id: runId,
    workflow_type: workflowType,
    status: "FULL_HISTORY",
    start_time: formatTimestamp(startEvent?.eventTime) || "",
    close_time: null,
    input: decodeSinglePayload(startAttrs?.input as Parameters<typeof decodePayloads>[0]),
    result: null,
    timeline,
    signals_received: [],
    timers_fired: [],
    child_workflows: [],
    failure: null,
    warning: `Full history with ${events.length} events (${filtered.length} after filtering internal events).`,
  };
}

function extractSignals(
  events: HistoryEvent[],
  truncateAt: number | undefined
): Array<{ name: string; time: string; input?: unknown }> {
  return events
    .filter((e) => resolveEventType(e) === "WorkflowExecutionSignaled")
    .map((e) => {
      const attrs = e.workflowExecutionSignaledEventAttributes as Record<string, unknown> | undefined;
      return {
        name: (attrs?.signalName as string) || "unknown",
        time: formatTimestamp(e.eventTime) || "",
        input: decodeSinglePayload(
          attrs?.input as Parameters<typeof decodePayloads>[0],
          truncateAt
        ),
      };
    });
}

function extractTimers(
  events: HistoryEvent[]
): Array<{ timer_id: string; duration: string; fired_time: string }> {
  const timerStarts = new Map<string, HistoryEvent>();

  for (const e of events) {
    if (resolveEventType(e) === "TimerStarted") {
      const attrs = e.timerStartedEventAttributes as Record<string, unknown> | undefined;
      const timerId = (attrs?.timerId as string) || "";
      timerStarts.set(timerId, e);
    }
  }

  return events
    .filter((e) => resolveEventType(e) === "TimerFired")
    .map((e) => {
      const attrs = e.timerFiredEventAttributes as Record<string, unknown> | undefined;
      const timerId = (attrs?.timerId as string) || "unknown";
      const startEvent = timerStarts.get(timerId);
      const startAttrs = startEvent?.timerStartedEventAttributes as Record<string, unknown> | undefined;
      const duration = formatDuration(startAttrs?.startToFireTimeout as { seconds?: number; nanos?: number } | undefined);

      return {
        timer_id: timerId,
        duration,
        fired_time: formatTimestamp(e.eventTime) || "",
      };
    });
}

function extractChildWorkflows(
  events: HistoryEvent[]
): Array<{ workflow_id: string; workflow_type: string; status: string }> {
  const children = new Map<
    string,
    { workflow_id: string; workflow_type: string; status: string }
  >();

  for (const e of events) {
    const eventType = resolveEventType(e);

    if (eventType === "StartChildWorkflowExecutionInitiated") {
      const attrs = e.startChildWorkflowExecutionInitiatedEventAttributes as Record<string, unknown> | undefined;
      const wfId = (attrs?.workflowId as string) || "";
      const wfType =
        (attrs?.workflowType as { name?: string })?.name || "Unknown";
      children.set(wfId, {
        workflow_id: wfId,
        workflow_type: wfType,
        status: "initiated",
      });
    } else if (eventType === "ChildWorkflowExecutionStarted") {
      const attrs = e.childWorkflowExecutionStartedEventAttributes as Record<string, unknown> | undefined;
      const wfId =
        (attrs?.workflowExecution as { workflowId?: string })?.workflowId || "";
      if (children.has(wfId)) {
        children.get(wfId)!.status = "started";
      }
    } else if (eventType === "ChildWorkflowExecutionCompleted") {
      const attrs = e.childWorkflowExecutionCompletedEventAttributes as Record<string, unknown> | undefined;
      const wfId =
        (attrs?.workflowExecution as { workflowId?: string })?.workflowId || "";
      if (children.has(wfId)) {
        children.get(wfId)!.status = "completed";
      }
    } else if (eventType === "ChildWorkflowExecutionFailed") {
      const attrs = e.childWorkflowExecutionFailedEventAttributes as Record<string, unknown> | undefined;
      const wfId =
        (attrs?.workflowExecution as { workflowId?: string })?.workflowId || "";
      if (children.has(wfId)) {
        children.get(wfId)!.status = "failed";
      }
    }
  }

  return Array.from(children.values());
}

// --- Utility Functions ---

function formatTimestamp(
  ts: { seconds?: number | Long | null; nanos?: number | null } | null | undefined
): string | null {
  if (!ts) return null;
  const seconds = typeof ts.seconds === "number" ? ts.seconds : Number(ts.seconds || 0);
  const date = new Date(seconds * 1000 + (ts.nanos || 0) / 1_000_000);
  return date.toISOString();
}

function timestampToMs(
  ts: { seconds?: number | Long | null; nanos?: number | null } | null | undefined
): number | null {
  if (!ts) return null;
  const seconds = typeof ts.seconds === "number" ? ts.seconds : Number(ts.seconds || 0);
  return seconds * 1000 + (ts.nanos || 0) / 1_000_000;
}

function computeDurationMs(
  start: { seconds?: number | Long | null; nanos?: number | null } | null | undefined,
  end: { seconds?: number | Long | null; nanos?: number | null } | null | undefined
): number | null {
  const startMs = timestampToMs(start);
  const endMs = timestampToMs(end);
  if (startMs === null || endMs === null) return null;
  return endMs - startMs;
}

function formatDuration(
  duration: { seconds?: number | Long | null; nanos?: number | null } | null | undefined
): string {
  if (!duration) return "unknown";
  const seconds = typeof duration.seconds === "number"
    ? duration.seconds
    : Number(duration.seconds || 0);
  if (seconds >= 3600) return `${Math.round(seconds / 3600)}h`;
  if (seconds >= 60) return `${Math.round(seconds / 60)}m`;
  return `${seconds}s`;
}

function extractFailure(
  failure: Record<string, unknown> | null | undefined
): unknown {
  if (!failure) return null;
  return {
    message: failure.message || "Unknown error",
    type: failure.type || (failure.source as string) || "unknown",
    stackTrace: failure.stackTrace || undefined,
    cause: failure.cause ? extractFailure(failure.cause as Record<string, unknown>) : undefined,
  };
}

function extractFailureMessage(
  failure: Record<string, unknown> | null | undefined
): string {
  if (!failure) return "Unknown error";
  return (failure.message as string) || "Unknown error";
}

/**
 * Create a short summary string from a value for the summary detail level.
 */
function summarizeValue(value: unknown): string {
  if (value === null || value === undefined) return "null";
  const json = JSON.stringify(value);
  if (json.length <= 200) return json;
  return json.slice(0, 197) + "...";
}
