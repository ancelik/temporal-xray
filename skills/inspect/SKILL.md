---
name: inspect
description: >
  Investigate a Temporal workflow execution. Provide a workflow ID,
  or describe the issue and let Claude find the relevant executions.
argument-hint: "[workflow-id or issue description]"
---

Before investigating, use `temporal_connection` with action `status` to verify
the connection is working. If not connected, guide the user through setup using
the `temporal_connection` tool with action `connect`, or recommend
`/temporal-xray:setup`.

If the developer mentions a specific namespace or environment (e.g., "check
staging", "look at production"), pass the appropriate `namespace` parameter to
each tool call.

Use the temporal-debugging skill to investigate the workflow issue
described by the developer. Start by determining whether this is an
explicit failure or a behavioral issue, then follow the appropriate
investigation path.

$ARGUMENTS
