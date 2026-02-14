---
name: inspect
description: >
  Investigate a Temporal workflow execution. Provide a workflow ID,
  or describe the issue and let Claude find the relevant executions.
argument-hint: "[workflow-id or issue description]"
---

Use the temporal-debugging skill to investigate the workflow issue
described by the developer. Start by determining whether this is an
explicit failure or a behavioral issue, then follow the appropriate
investigation path.

$ARGUMENTS
