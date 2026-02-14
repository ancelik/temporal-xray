import { getWorkflowHistory } from "./get-workflow-history.js";
import { diffExecutions } from "../transformers/diff-engine.js";
import type { CompareExecutionsInput, CompareExecutionsOutput } from "../types.js";

export async function compareExecutions(
  input: CompareExecutionsInput
): Promise<CompareExecutionsOutput> {
  // Fetch both histories at standard detail level for full data comparison
  const [historyA, historyB] = await Promise.all([
    getWorkflowHistory({
      workflow_id: input.workflow_id_a,
      run_id: input.run_id_a,
      detail_level: "standard",
    }),
    getWorkflowHistory({
      workflow_id: input.workflow_id_b,
      run_id: input.run_id_b,
      detail_level: "standard",
    }),
  ]);

  const diff = diffExecutions(historyA, historyB);

  return {
    execution_a: {
      workflow_id: historyA.workflow_id,
      status: historyA.status,
      workflow_type: historyA.workflow_type,
    },
    execution_b: {
      workflow_id: historyB.workflow_id,
      status: historyB.status,
      workflow_type: historyB.workflow_type,
    },
    same_workflow_type: historyA.workflow_type === historyB.workflow_type,
    ...diff,
  };
}
