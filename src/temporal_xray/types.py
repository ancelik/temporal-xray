from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# --- Input Models ---


class ListWorkflowsInput(BaseModel):
    namespace: str | None = Field(
        default=None,
        description="Temporal namespace to query. Defaults to the configured namespace (TEMPORAL_NAMESPACE env var or 'default').",
    )
    workflow_type: str | None = Field(default=None, description="Filter by workflow type name")
    workflow_id: str | None = Field(default=None, description="Filter by exact workflow ID")
    status: str | None = Field(
        default=None,
        description="Filter by execution status",
        json_schema_extra={"enum": ["running", "completed", "failed", "timed_out", "cancelled", "terminated", "all"]},
    )
    query: str | None = Field(default=None, description="Raw Temporal visibility query for advanced filtering")
    start_time_from: str | None = Field(default=None, description="Only executions started after this ISO time")
    start_time_to: str | None = Field(default=None, description="Only executions started before this ISO time")
    limit: int = Field(default=10, ge=1, le=50, description="Number of results (max 50)")


class GetWorkflowHistoryInput(BaseModel):
    namespace: str | None = Field(default=None, description="Temporal namespace to query.")
    workflow_id: str = Field(description="Workflow execution ID")
    run_id: str | None = Field(default=None, description="Run ID (defaults to latest run)")
    detail_level: str = Field(
        default="summary",
        description="Level of detail in the response",
        json_schema_extra={"enum": ["summary", "standard", "full"]},
    )
    event_types: list[str] | None = Field(default=None, description="Filter to specific event types")


class GetWorkflowStackTraceInput(BaseModel):
    namespace: str | None = Field(default=None, description="Temporal namespace to query.")
    workflow_id: str = Field(description="Workflow execution ID")
    run_id: str | None = Field(default=None, description="Run ID (defaults to latest run)")


class CompareExecutionsInput(BaseModel):
    namespace: str | None = Field(default=None, description="Temporal namespace to query.")
    workflow_id_a: str = Field(description='Workflow ID of the "good" execution')
    workflow_id_b: str = Field(description='Workflow ID of the "bad" execution')
    run_id_a: str | None = Field(default=None, description="Run ID for execution A")
    run_id_b: str | None = Field(default=None, description="Run ID for execution B")


class DescribeTaskQueueInput(BaseModel):
    namespace: str | None = Field(default=None, description="Temporal namespace to query.")
    task_queue: str = Field(description="Task queue name")
    task_queue_type: str = Field(
        default="workflow",
        description="Type of task queue",
        json_schema_extra={"enum": ["workflow", "activity"]},
    )


class SearchWorkflowDataInput(BaseModel):
    namespace: str | None = Field(default=None, description="Temporal namespace to query.")
    workflow_type: str = Field(description="Workflow type to search")
    query: str = Field(description="Temporal visibility query")
    aggregate: str = Field(
        default="list",
        description="Aggregation mode",
        json_schema_extra={"enum": ["count", "list", "sample"]},
    )
    limit: int = Field(default=20, ge=1, le=50, description="Max results")


class TemporalConnectionInput(BaseModel):
    action: str = Field(
        default="status",
        description="'status' to check current connection, 'connect' to establish a new one",
        json_schema_extra={"enum": ["status", "connect"]},
    )
    address: str | None = Field(
        default=None,
        description="Temporal server address (e.g., localhost:7233 or your-ns.tmprl.cloud:7233)",
    )
    namespace: str | None = Field(default=None, description="Default namespace for this connection")
    api_key: str | None = Field(default=None, description="API key for Temporal Cloud authentication")
    tls_cert_path: str | None = Field(
        default=None, description="Path to TLS client certificate for mTLS authentication"
    )
    tls_key_path: str | None = Field(default=None, description="Path to TLS client key for mTLS authentication")


# --- Output Types ---


class WorkflowSummary(BaseModel):
    workflow_id: str
    run_id: str
    workflow_type: str
    status: str
    start_time: str
    close_time: str | None
    duration_ms: int | None
    task_queue: str
    search_attributes: dict[str, Any]


class ListWorkflowsOutput(BaseModel):
    workflows: list[WorkflowSummary]
    total_count: int
    has_more: bool


class TimelineStep(BaseModel):
    step: int
    activity: str
    status: str
    duration_ms: int | None
    retries: int | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    input: Any | None = None
    output: Any | None = None
    failure: str | None = None
    last_failure: str | None = None


class WorkflowHistory(BaseModel):
    workflow_id: str
    run_id: str
    workflow_type: str
    status: str
    start_time: str
    close_time: str | None
    input: Any
    result: Any
    timeline: list[TimelineStep]
    signals_received: list[dict[str, Any]]
    timers_fired: list[dict[str, Any]]
    child_workflows: list[dict[str, Any]]
    failure: Any | None
    warning: str | None = None


class StackTraceOutput(BaseModel):
    workflow_id: str
    status: str
    running_since: str
    duration_so_far_ms: int
    stack_trace: str
    pending_activities: list[dict[str, Any]]


class ExecutionDivergence(BaseModel):
    step: int
    activity: str
    field: str
    value_a: Any
    value_b: Any
    note: str


class CompareExecutionsOutput(BaseModel):
    execution_a: dict[str, str]
    execution_b: dict[str, str]
    same_workflow_type: bool
    divergences: list[ExecutionDivergence]
    structural_differences: dict[str, Any]
    signals: dict[str, list[str]]


class TaskQueueInfo(BaseModel):
    task_queue: str
    pollers: list[dict[str, Any]]
    backlog_count: int
    versions_active: list[str]


class SearchWorkflowDataOutput(BaseModel):
    query: str
    count: int
    time_range: str
    sample_workflow_ids: list[str]
    workflows: list[WorkflowSummary] | None = None
