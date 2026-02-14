# Changelog

## 1.1.0 (2026-02-14)

### Added
- `temporal_connection` tool — check or switch Temporal server connections at runtime
- `setup` skill (`/temporal-xray:setup`) — guided onboarding for local, cloud, and self-hosted Temporal servers
- Optional `namespace` parameter on all 6 debugging tools for per-call namespace targeting
- Multi-namespace client cache — query different namespaces without reconfiguring
- Dynamic server switching — connect to dev, staging, prod servers without restarting
- All 5 Temporal env vars now passed through `.mcp.json` (added TLS and API key)

### Changed
- `temporal-client.ts` refactored from singleton to multi-namespace client cache
- `inspect` skill now checks connection status before investigating
- `temporal-debugging` skill updated with namespace awareness guidance
- `temporal-investigator` agent updated with multi-environment capabilities

## 1.0.0 (2026-02-13)

### Added
- MCP server with 6 read-only Temporal debugging tools:
  - `list_workflows` — Search and filter workflow executions
  - `get_workflow_history` — Get execution timeline with inputs/outputs at 3 detail levels
  - `get_workflow_stack_trace` — See where a running workflow is blocked
  - `compare_executions` — Diff two executions to find data/structural divergences
  - `describe_task_queue` — Check worker health and version consistency
  - `search_workflow_data` — Pattern detection across many executions
- `temporal-debugging` skill with investigation strategies for explicit failures, silent failures, and stuck workflows
- `inspect` skill as developer-facing entry point
- `temporal-investigator` subagent with persistent memory for cross-session learning
- Support for JSON, Protobuf, encrypted, and large payload handling
- Temporal Cloud support via API key and mTLS authentication
