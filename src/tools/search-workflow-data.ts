import { getTemporalClient } from "../temporal-client.js";
import { toWorkflowSummary } from "./shared.js";
import type { SearchWorkflowDataInput, SearchWorkflowDataOutput } from "../types.js";

export async function searchWorkflowData(
  input: SearchWorkflowDataInput
): Promise<SearchWorkflowDataOutput> {
  const client = await getTemporalClient(input.namespace);

  const escapedType = input.workflow_type.replace(/'/g, "''");
  const fullQuery = input.query.includes("WorkflowType")
    ? input.query
    : `WorkflowType = '${escapedType}' AND ${input.query}`;

  try {
    if (input.aggregate === "count") {
      return await countWorkflows(client, fullQuery);
    }

    const limit =
      input.aggregate === "sample"
        ? Math.min(input.limit || 3, 5)
        : input.limit || 20;

    const workflows = [];
    const sampleIds: string[] = [];
    let count = 0;

    for await (const workflow of client.workflow.list({ query: fullQuery })) {
      if (count >= limit) break;

      sampleIds.push(workflow.workflowId);

      if (input.aggregate !== "sample" || count < 3) {
        workflows.push(toWorkflowSummary(workflow));
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
  query: string
): Promise<SearchWorkflowDataOutput> {
  const sampleIds: string[] = [];
  let count = 0;

  for await (const workflow of client.workflow.list({ query })) {
    count++;
    if (sampleIds.length < 3) {
      sampleIds.push(workflow.workflowId);
    }
    if (count >= 10000) break;
  }

  return {
    query,
    count,
    time_range: "query-defined",
    sample_workflow_ids: sampleIds,
  };
}
