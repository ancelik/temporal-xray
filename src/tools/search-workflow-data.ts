import { getTemporalClient } from "../temporal-client.js";
import type {
  SearchWorkflowDataInput,
  SearchWorkflowDataOutput,
  WorkflowSummary,
} from "../types.js";

export async function searchWorkflowData(
  input: SearchWorkflowDataInput
): Promise<SearchWorkflowDataOutput> {
  const client = await getTemporalClient(input.namespace);

  // Build query with workflow type prefix
  const escapedType = input.workflow_type.replace(/'/g, "''");
  const fullQuery = input.query.includes("WorkflowType")
    ? input.query
    : `WorkflowType = '${escapedType}' AND ${input.query}`;

  try {
    if (input.aggregate === "count") {
      return await countWorkflows(client, fullQuery, input);
    }

    // For "list" and "sample" modes
    const limit =
      input.aggregate === "sample"
        ? Math.min(input.limit || 3, 5) // Sample returns fewer results
        : input.limit || 20;

    const workflows: WorkflowSummary[] = [];
    const sampleIds: string[] = [];
    let count = 0;

    for await (const workflow of client.workflow.list({
      query: fullQuery,
    })) {
      if (count >= limit) break;

      sampleIds.push(workflow.workflowId);

      if (input.aggregate !== "sample" || count < 3) {
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
          start_time: workflow.startTime
            ? workflow.startTime.toISOString()
            : "",
          close_time: workflow.closeTime
            ? workflow.closeTime.toISOString()
            : null,
          duration_ms:
            workflow.startTime && workflow.closeTime
              ? workflow.closeTime.getTime() - workflow.startTime.getTime()
              : null,
          task_queue: workflow.taskQueue,
          search_attributes: searchAttributes,
        });
      }

      count++;
    }

    return {
      query: fullQuery,
      count,
      time_range: "query-defined",
      sample_workflow_ids: sampleIds.slice(0, 5),
      workflows: input.aggregate === "list" ? workflows : undefined,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Failed to search workflow data: ${message}`);
  }
}

async function countWorkflows(
  client: import("@temporalio/client").Client,
  query: string,
  input: SearchWorkflowDataInput
): Promise<SearchWorkflowDataOutput> {
  // Use list to count and get sample IDs (count API may not be available in all setups)
  const sampleIds: string[] = [];
  let count = 0;

  for await (const workflow of client.workflow.list({ query })) {
    count++;
    if (sampleIds.length < 3) {
      sampleIds.push(workflow.workflowId);
    }
    // Cap counting at a reasonable limit to avoid scanning too many
    if (count >= 10000) break;
  }

  return {
    query,
    count,
    time_range: "query-defined",
    sample_workflow_ids: sampleIds,
  };
}
