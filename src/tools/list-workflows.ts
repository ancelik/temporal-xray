import { getTemporalClient } from "../temporal-client.js";
import type { ListWorkflowsInput, ListWorkflowsOutput, WorkflowSummary } from "../types.js";

function escapeQueryValue(value: string): string {
  return value.replace(/'/g, "''");
}

const STATUS_MAP: Record<string, string> = {
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  timed_out: "TimedOut",
  cancelled: "Canceled",
  terminated: "Terminated",
};

/**
 * Build a Temporal visibility query from the structured input parameters.
 */
function buildQuery(input: ListWorkflowsInput): string {
  // If user provided a raw query, use it directly
  if (input.query) return input.query;

  const clauses: string[] = [];

  if (input.workflow_type) {
    clauses.push(`WorkflowType = '${escapeQueryValue(input.workflow_type)}'`);
  }

  if (input.workflow_id) {
    clauses.push(`WorkflowId = '${escapeQueryValue(input.workflow_id)}'`);
  }

  if (input.status && input.status !== "all") {
    clauses.push(`ExecutionStatus = '${STATUS_MAP[input.status] || input.status}'`);
  }

  if (input.start_time_from) {
    clauses.push(`StartTime >= '${input.start_time_from}'`);
  }

  if (input.start_time_to) {
    clauses.push(`StartTime <= '${input.start_time_to}'`);
  }

  return clauses.join(" AND ");
}

export async function listWorkflows(
  input: ListWorkflowsInput
): Promise<ListWorkflowsOutput> {
  const client = await getTemporalClient(input.namespace);
  const query = buildQuery(input);

  const workflows: WorkflowSummary[] = [];
  let totalCount = 0;
  let hasMore = false;

  try {
    const limit = input.limit || 10;
    let count = 0;

    for await (const workflow of client.workflow.list({
      query: query || undefined,
    })) {
      if (count >= limit) {
        hasMore = true;
        break;
      }

      const startTime = workflow.startTime
        ? workflow.startTime.toISOString()
        : "";
      const closeTime = workflow.closeTime
        ? workflow.closeTime.toISOString()
        : null;
      const durationMs =
        workflow.startTime && workflow.closeTime
          ? workflow.closeTime.getTime() - workflow.startTime.getTime()
          : null;

      // Extract search attributes
      const searchAttributes: Record<string, unknown> = {};
      if (workflow.searchAttributes) {
        for (const [key, value] of Object.entries(
          workflow.searchAttributes
        )) {
          searchAttributes[key] = value;
        }
      }

      workflows.push({
        workflow_id: workflow.workflowId,
        run_id: workflow.runId,
        workflow_type: workflow.type,
        status: workflow.status.name,
        start_time: startTime,
        close_time: closeTime,
        duration_ms: durationMs,
        task_queue: workflow.taskQueue,
        search_attributes: searchAttributes,
      });

      count++;
      totalCount++;
    }
  } catch (error) {
    return handleError(error);
  }

  return {
    workflows,
    total_count: totalCount,
    has_more: hasMore,
  };
}

function handleError(error: unknown): never {
  const message = error instanceof Error ? error.message : String(error);

  if (message.includes("namespace") && message.includes("not found")) {
    throw new Error(
      `Namespace not found. Verify TEMPORAL_NAMESPACE is correct. Details: ${message}`
    );
  }

  if (message.includes("UNAVAILABLE") || message.includes("connect")) {
    throw new Error(
      `Cannot connect to Temporal server. Verify TEMPORAL_ADDRESS is correct and the server is running. Details: ${message}`
    );
  }

  throw new Error(`Failed to list workflows: ${message}`);
}
