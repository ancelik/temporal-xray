import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import type { z } from "zod";
import {
  ListWorkflowsInputSchema,
  GetWorkflowHistoryInputSchema,
  GetWorkflowStackTraceInputSchema,
  CompareExecutionsInputSchema,
  DescribeTaskQueueInputSchema,
  SearchWorkflowDataInputSchema,
  TemporalConnectionInputSchema,
} from "./types.js";
import { listWorkflows } from "./tools/list-workflows.js";
import { getWorkflowHistory } from "./tools/get-workflow-history.js";
import { getWorkflowStackTrace } from "./tools/get-workflow-stack-trace.js";
import { compareExecutions } from "./tools/compare-executions.js";
import { describeTaskQueue } from "./tools/describe-task-queue.js";
import { searchWorkflowData } from "./tools/search-workflow-data.js";
import { temporalConnection } from "./tools/temporal-connection.js";
import { closeConnection } from "./temporal-client.js";

const server = new McpServer({
  name: "temporal-xray",
  version: "1.1.0",
});

function registerTool<S extends z.ZodObject<z.ZodRawShape>>(
  name: string,
  description: string,
  schema: S,
  handler: (input: z.infer<S>) => Promise<unknown>
) {
  server.tool(name, description, schema.shape, async (input) => {
    try {
      const parsed = schema.parse(input);
      const result = await handler(parsed);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        content: [{ type: "text" as const, text: JSON.stringify({ error: message }, null, 2) }],
        isError: true,
      };
    }
  });
}

registerTool(
  "list_workflows",
  "List and search Temporal workflow executions. Filter by workflow type, ID, status, time range, or raw visibility query. Use this to find specific executions for investigation.",
  ListWorkflowsInputSchema,
  listWorkflows
);

registerTool(
  "get_workflow_history",
  "Get the execution history of a Temporal workflow. Returns a timeline of activities with their inputs, outputs, durations, and any failures. Use detail_level 'summary' for overview, 'standard' for full payloads, 'full' for raw events.",
  GetWorkflowHistoryInputSchema,
  getWorkflowHistory
);

registerTool(
  "get_workflow_stack_trace",
  "Get the current stack trace and pending activities of a running Temporal workflow. Shows where the workflow is blocked and what it's waiting for.",
  GetWorkflowStackTraceInputSchema,
  getWorkflowStackTrace
);

registerTool(
  "compare_executions",
  "Compare two Temporal workflow executions to find where they diverge. Identifies data differences in activity inputs/outputs, structural differences (different activities executed), and signal differences. Ideal for investigating why one execution succeeded and another failed.",
  CompareExecutionsInputSchema,
  compareExecutions
);

registerTool(
  "describe_task_queue",
  "Describe a Temporal task queue to check worker health. Shows active pollers, their versions, last access times, and processing rates. Useful for diagnosing infrastructure issues and version mismatches.",
  DescribeTaskQueueInputSchema,
  describeTaskQueue
);

registerTool(
  "search_workflow_data",
  "Search and aggregate Temporal workflow data using visibility queries. Find patterns across many executions — count affected workflows, list them, or get a sample. Useful for detecting widespread silent failures.",
  SearchWorkflowDataInputSchema,
  searchWorkflowData
);

registerTool(
  "temporal_connection",
  "Check or change the Temporal server connection. Use action 'status' to see current connection info, or 'connect' to switch to a different server or namespace. Useful for working with multiple environments (dev, staging, prod).",
  TemporalConnectionInputSchema,
  temporalConnection
);

// Start the server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);

  // Clean up on exit
  const shutdown = async () => {
    await closeConnection();
    process.exit(0);
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

main().catch((error) => {
  console.error("Failed to start MCP server:", error);
  process.exit(1);
});
