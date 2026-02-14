import type { temporal } from "@temporalio/proto";
import { getTemporalClient } from "../temporal-client.js";
import { summarizeHistory } from "../transformers/history-summarizer.js";
import type { GetWorkflowHistoryInput, WorkflowHistory } from "../types.js";

export async function getWorkflowHistory(
  input: GetWorkflowHistoryInput
): Promise<WorkflowHistory> {
  const client = await getTemporalClient();

  try {
    const handle = client.workflow.getHandle(
      input.workflow_id,
      input.run_id
    );

    // Fetch the full event history
    const history = await handle.fetchHistory();
    const events: temporal.api.history.v1.IHistoryEvent[] = history.events || [];

    if (events.length === 0) {
      throw new Error(
        `No workflow found with ID '${input.workflow_id}'. The workflow may have been archived or the ID may be incorrect.`
      );
    }

    // Get the run ID from the describe response
    const description = await handle.describe();
    const runId = input.run_id || description.runId;

    return summarizeHistory(input.workflow_id, runId, events, {
      detailLevel: input.detail_level || "summary",
      eventTypes: input.event_types,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);

    if (message.includes("not found") || message.includes("NotFound")) {
      throw new Error(
        `No workflow found with ID '${input.workflow_id}'. The workflow may have been archived or the ID may be incorrect.`
      );
    }

    if (message.includes("permission") || message.includes("Unauthorized")) {
      throw new Error(
        `Permission denied. The configured credentials don't have read access to this namespace.`
      );
    }

    throw new Error(`Failed to get workflow history: ${message}`);
  }
}
