import { z } from "zod";

// --- Input Schemas ---

const namespaceField = z
  .string()
  .optional()
  .describe(
    "Temporal namespace to query. Defaults to the configured namespace (TEMPORAL_NAMESPACE env var or 'default')."
  );

export const ListWorkflowsInputSchema = z.object({
  namespace: namespaceField,
  workflow_type: z.string().optional().describe("Filter by workflow type name"),
  workflow_id: z.string().optional().describe("Filter by exact workflow ID"),
  status: z
    .enum([
      "running",
      "completed",
      "failed",
      "timed_out",
      "cancelled",
      "terminated",
      "all",
    ])
    .optional()
    .describe("Filter by execution status"),
  query: z
    .string()
    .optional()
    .describe("Raw Temporal visibility query for advanced filtering"),
  start_time_from: z
    .string()
    .optional()
    .describe("Only executions started after this ISO time"),
  start_time_to: z
    .string()
    .optional()
    .describe("Only executions started before this ISO time"),
  limit: z
    .number()
    .int()
    .min(1)
    .max(50)
    .default(10)
    .describe("Number of results (max 50)"),
});

export const GetWorkflowHistoryInputSchema = z.object({
  namespace: namespaceField,
  workflow_id: z.string().describe("Workflow execution ID"),
  run_id: z.string().optional().describe("Run ID (defaults to latest run)"),
  detail_level: z
    .enum(["summary", "standard", "full"])
    .default("summary")
    .describe("Level of detail in the response"),
  event_types: z
    .array(z.string())
    .optional()
    .describe("Filter to specific event types"),
});

export const GetWorkflowStackTraceInputSchema = z.object({
  namespace: namespaceField,
  workflow_id: z.string().describe("Workflow execution ID"),
  run_id: z.string().optional().describe("Run ID (defaults to latest run)"),
});

export const CompareExecutionsInputSchema = z.object({
  namespace: namespaceField,
  workflow_id_a: z.string().describe('Workflow ID of the "good" execution'),
  workflow_id_b: z.string().describe('Workflow ID of the "bad" execution'),
  run_id_a: z.string().optional().describe("Run ID for execution A"),
  run_id_b: z.string().optional().describe("Run ID for execution B"),
});

export const DescribeTaskQueueInputSchema = z.object({
  namespace: namespaceField,
  task_queue: z.string().describe("Task queue name"),
  task_queue_type: z
    .enum(["workflow", "activity"])
    .default("workflow")
    .describe("Type of task queue"),
});

export const SearchWorkflowDataInputSchema = z.object({
  namespace: namespaceField,
  workflow_type: z.string().describe("Workflow type to search"),
  query: z.string().describe("Temporal visibility query"),
  aggregate: z
    .enum(["count", "list", "sample"])
    .default("list")
    .describe("Aggregation mode"),
  limit: z
    .number()
    .int()
    .min(1)
    .max(50)
    .default(20)
    .describe("Max results"),
});

export const TemporalConnectionInputSchema = z.object({
  action: z
    .enum(["status", "connect"])
    .default("status")
    .describe(
      "'status' to check current connection, 'connect' to establish a new one"
    ),
  address: z
    .string()
    .optional()
    .describe(
      "Temporal server address (e.g., localhost:7233 or your-ns.tmprl.cloud:7233)"
    ),
  namespace: z
    .string()
    .optional()
    .describe("Default namespace for this connection"),
  api_key: z
    .string()
    .optional()
    .describe("API key for Temporal Cloud authentication"),
  tls_cert_path: z
    .string()
    .optional()
    .describe("Path to TLS client certificate for mTLS authentication"),
  tls_key_path: z
    .string()
    .optional()
    .describe("Path to TLS client key for mTLS authentication"),
});

// --- Input Types ---

export type ListWorkflowsInput = z.infer<typeof ListWorkflowsInputSchema>;
export type GetWorkflowHistoryInput = z.infer<typeof GetWorkflowHistoryInputSchema>;
export type GetWorkflowStackTraceInput = z.infer<typeof GetWorkflowStackTraceInputSchema>;
export type CompareExecutionsInput = z.infer<typeof CompareExecutionsInputSchema>;
export type DescribeTaskQueueInput = z.infer<typeof DescribeTaskQueueInputSchema>;
export type SearchWorkflowDataInput = z.infer<typeof SearchWorkflowDataInputSchema>;
export type TemporalConnectionInput = z.infer<typeof TemporalConnectionInputSchema>;

// --- Output Types ---

export interface WorkflowSummary {
  workflow_id: string;
  run_id: string;
  workflow_type: string;
  status: string;
  start_time: string;
  close_time: string | null;
  duration_ms: number | null;
  task_queue: string;
  search_attributes: Record<string, unknown>;
}

export interface ListWorkflowsOutput {
  workflows: WorkflowSummary[];
  total_count: number;
  has_more: boolean;
}

export interface TimelineStep {
  step: number;
  activity: string;
  status: string;
  duration_ms: number | null;
  retries?: number;
  input_summary?: string;
  output_summary?: string;
  input?: unknown;
  output?: unknown;
  failure?: string;
  last_failure?: string;
}

export interface WorkflowHistory {
  workflow_id: string;
  run_id: string;
  workflow_type: string;
  status: string;
  start_time: string;
  close_time: string | null;
  input: unknown;
  result: unknown;
  timeline: TimelineStep[];
  signals_received: Array<{ name: string; time: string; input?: unknown }>;
  timers_fired: Array<{ timer_id: string; duration: string; fired_time: string }>;
  child_workflows: Array<{
    workflow_id: string;
    workflow_type: string;
    status: string;
  }>;
  failure: unknown | null;
  warning?: string;
}

export interface StackTraceOutput {
  workflow_id: string;
  status: string;
  running_since: string;
  duration_so_far_ms: number;
  stack_trace: string;
  pending_activities: Array<{
    activity_type: string;
    state: string;
    scheduled_time: string;
    attempt: number;
    last_failure: string | null;
  }>;
}

export interface ExecutionDivergence {
  step: number;
  activity: string;
  field: string;
  value_a: unknown;
  value_b: unknown;
  note: string;
}

export interface CompareExecutionsOutput {
  execution_a: { workflow_id: string; status: string; workflow_type: string };
  execution_b: { workflow_id: string; status: string; workflow_type: string };
  same_workflow_type: boolean;
  divergences: ExecutionDivergence[];
  structural_differences: {
    activities_only_in_a: string[];
    activities_only_in_b: string[];
    different_execution_order: boolean;
  };
  signals: {
    signals_only_in_a: string[];
    signals_only_in_b: string[];
  };
}

export interface TaskQueueInfo {
  task_queue: string;
  pollers: Array<{
    identity: string;
    last_access_time: string;
    rate_per_second: number;
    worker_version: string | null;
  }>;
  backlog_count: number;
  versions_active: string[];
}

export interface SearchWorkflowDataOutput {
  query: string;
  count: number;
  time_range: string;
  sample_workflow_ids: string[];
  workflows?: WorkflowSummary[];
}

// --- Payload Types ---

export interface TruncatedPayload {
  _truncated: true;
  preview: string;
  fullSizeBytes: number;
}

export interface ProtobufPayload {
  _type: "protobuf";
  messageType: string;
  note: string;
}

export interface EncryptedPayload {
  _type: "encrypted";
  note: string;
}

export type DecodedPayload =
  | TruncatedPayload
  | ProtobufPayload
  | EncryptedPayload
  | string
  | number
  | boolean
  | null
  | Record<string, unknown>
  | unknown[];

// --- Shared Utility Types ---

/** Protobuf Long value type */
export type Long = {
  toNumber(): number;
  toString(): string;
};
