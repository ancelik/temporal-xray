import { getTemporalClient } from "../temporal-client.js";
import type { GetWorkflowStackTraceInput, StackTraceOutput } from "../types.js";

export async function getWorkflowStackTrace(
  input: GetWorkflowStackTraceInput
): Promise<StackTraceOutput> {
  const client = await getTemporalClient(input.namespace);

  try {
    const handle = client.workflow.getHandle(
      input.workflow_id,
      input.run_id
    );

    // Get the workflow description for status and pending activities
    const description = await handle.describe();

    // Query for stack trace (built-in query type)
    let stackTrace = "";
    try {
      stackTrace = await handle.query<string>("__stack_trace");
    } catch {
      stackTrace = "Stack trace unavailable (workflow may not be running or query handler not registered)";
    }

    const startTime = description.startTime
      ? description.startTime.toISOString()
      : new Date().toISOString();

    const now = Date.now();
    const durationMs = description.startTime
      ? now - description.startTime.getTime()
      : 0;

    // Extract pending activities from the raw description
    const pendingActivities = extractPendingActivities(description);

    return {
      workflow_id: input.workflow_id,
      status: description.status.name,
      running_since: startTime,
      duration_so_far_ms: durationMs,
      stack_trace: stackTrace,
      pending_activities: pendingActivities,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);

    if (message.includes("not found") || message.includes("NotFound")) {
      throw new Error(
        `No workflow found with ID '${input.workflow_id}'. The workflow may have been archived or the ID may be incorrect.`
      );
    }

    throw new Error(`Failed to get workflow stack trace: ${message}`);
  }
}

function extractPendingActivities(
  description: Awaited<ReturnType<import("@temporalio/client").WorkflowHandle["describe"]>>
): StackTraceOutput["pending_activities"] {
  // The WorkflowExecutionDescription from the Temporal client may include
  // raw pendingActivities from the gRPC response
  const raw = description.raw;
  if (!raw?.pendingActivities) return [];

  return raw.pendingActivities.map((pa) => {
    const activityType = pa.activityType?.name || "Unknown";
    const state = pa.state != null
      ? pendingActivityStateToString(pa.state)
      : "unknown";
    const scheduledTime = pa.scheduledTime
      ? new Date(
          Number(pa.scheduledTime.seconds || 0) * 1000
        ).toISOString()
      : "";
    const attempt = pa.attempt || 1;
    const lastFailure = pa.lastFailure?.message || null;

    return {
      activity_type: activityType,
      state,
      scheduled_time: scheduledTime,
      attempt: typeof attempt === "number" ? attempt : Number(attempt),
      last_failure: lastFailure || null,
    };
  });
}

function pendingActivityStateToString(state: number | string): string {
  if (typeof state === "string") return state;

  const stateMap: Record<number, string> = {
    0: "UNSPECIFIED",
    1: "SCHEDULED",
    2: "STARTED",
    3: "CANCEL_REQUESTED",
  };

  return stateMap[state] || `UNKNOWN(${state})`;
}
