import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListWorkflowsInputSchema,
  GetWorkflowHistoryInputSchema,
  GetWorkflowStackTraceInputSchema,
  CompareExecutionsInputSchema,
  DescribeTaskQueueInputSchema,
  SearchWorkflowDataInputSchema,
} from "./types.js";
import { listWorkflows } from "./tools/list-workflows.js";
import { getWorkflowHistory } from "./tools/get-workflow-history.js";
import { getWorkflowStackTrace } from "./tools/get-workflow-stack-trace.js";
import { compareExecutions } from "./tools/compare-executions.js";
import { describeTaskQueue } from "./tools/describe-task-queue.js";
import { searchWorkflowData } from "./tools/search-workflow-data.js";
import { closeConnection } from "./temporal-client.js";

const server = new McpServer({
  name: "temporal-xray",
  version: "1.0.0",
});

// Tool 1: list_workflows
server.tool(
  "list_workflows",
  "List and search Temporal workflow executions. Filter by workflow type, ID, status, time range, or raw visibility query. Use this to find specific executions for investigation.",
  ListWorkflowsInputSchema.shape,
  async (input) => {
    try {
      const parsed = ListWorkflowsInputSchema.parse(input);
      const result = await listWorkflows(parsed);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return errorResponse(error);
    }
  }
);

// Tool 2: get_workflow_history
server.tool(
  "get_workflow_history",
  "Get the execution history of a Temporal workflow. Returns a timeline of activities with their inputs, outputs, durations, and any failures. Use detail_level 'summary' for overview, 'standard' for full payloads, 'full' for raw events.",
  GetWorkflowHistoryInputSchema.shape,
  async (input) => {
    try {
      const parsed = GetWorkflowHistoryInputSchema.parse(input);
      const result = await getWorkflowHistory(parsed);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return errorResponse(error);
    }
  }
);

// Tool 3: get_workflow_stack_trace
server.tool(
  "get_workflow_stack_trace",
  "Get the current stack trace and pending activities of a running Temporal workflow. Shows where the workflow is blocked and what it's waiting for.",
  GetWorkflowStackTraceInputSchema.shape,
  async (input) => {
    try {
      const parsed = GetWorkflowStackTraceInputSchema.parse(input);
      const result = await getWorkflowStackTrace(parsed);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return errorResponse(error);
    }
  }
);

// Tool 4: compare_executions
server.tool(
  "compare_executions",
  "Compare two Temporal workflow executions to find where they diverge. Identifies data differences in activity inputs/outputs, structural differences (different activities executed), and signal differences. Ideal for investigating why one execution succeeded and another failed.",
  CompareExecutionsInputSchema.shape,
  async (input) => {
    try {
      const parsed = CompareExecutionsInputSchema.parse(input);
      const result = await compareExecutions(parsed);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return errorResponse(error);
    }
  }
);

// Tool 5: describe_task_queue
server.tool(
  "describe_task_queue",
  "Describe a Temporal task queue to check worker health. Shows active pollers, their versions, last access times, and processing rates. Useful for diagnosing infrastructure issues and version mismatches.",
  DescribeTaskQueueInputSchema.shape,
  async (input) => {
    try {
      const parsed = DescribeTaskQueueInputSchema.parse(input);
      const result = await describeTaskQueue(parsed);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return errorResponse(error);
    }
  }
);

// Tool 6: search_workflow_data
server.tool(
  "search_workflow_data",
  "Search and aggregate Temporal workflow data using visibility queries. Find patterns across many executions — count affected workflows, list them, or get a sample. Useful for detecting widespread silent failures.",
  SearchWorkflowDataInputSchema.shape,
  async (input) => {
    try {
      const parsed = SearchWorkflowDataInputSchema.parse(input);
      const result = await searchWorkflowData(parsed);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return errorResponse(error);
    }
  }
);

function errorResponse(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return {
    content: [{ type: "text" as const, text: JSON.stringify({ error: message }, null, 2) }],
    isError: true,
  };
}

// Start the server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);

  // Clean up on exit
  process.on("SIGINT", async () => {
    await closeConnection();
    process.exit(0);
  });

  process.on("SIGTERM", async () => {
    await closeConnection();
    process.exit(0);
  });
}

main().catch((error) => {
  console.error("Failed to start MCP server:", error);
  process.exit(1);
});
