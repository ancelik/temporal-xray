import { getTemporalClient } from "../temporal-client.js";
import { toWorkflowSummary } from "./shared.js";
import type { ListWorkflowsInput, ListWorkflowsOutput } from "../types.js";

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

function buildQuery(input: ListWorkflowsInput): string {
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

  try {
    const limit = input.limit || 10;
    const workflows = [];
    let hasMore = false;
    let count = 0;

    for await (const workflow of client.workflow.list({
      query: query || undefined,
    })) {
      if (count >= limit) {
        hasMore = true;
        break;
      }

      workflows.push(toWorkflowSummary(workflow));
      count++;
    }

    return { workflows, total_count: count, has_more: hasMore };
  } catch (error) {
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
}
