import type { WorkflowSummary } from "../types.js";

/**
 * Convert a Temporal workflow listing entry to a WorkflowSummary.
 */
export function toWorkflowSummary(workflow: {
  workflowId: string;
  runId: string;
  type: string;
  status: { name: string };
  startTime?: Date | null;
  closeTime?: Date | null;
  taskQueue: string;
  searchAttributes?: Record<string, unknown>;
}): WorkflowSummary {
  const startTime = workflow.startTime?.toISOString() ?? "";
  const closeTime = workflow.closeTime?.toISOString() ?? null;
  const durationMs =
    workflow.startTime && workflow.closeTime
      ? workflow.closeTime.getTime() - workflow.startTime.getTime()
      : null;

  return {
    workflow_id: workflow.workflowId,
    run_id: workflow.runId,
    workflow_type: workflow.type,
    status: workflow.status.name,
    start_time: startTime,
    close_time: closeTime,
    duration_ms: durationMs,
    task_queue: workflow.taskQueue,
    search_attributes: { ...workflow.searchAttributes },
  };
}
