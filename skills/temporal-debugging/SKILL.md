---
name: temporal-debugging
description: >
  Temporal workflow debugging knowledge — investigation strategies for explicit
  failures (exceptions, timeouts), silent failures (wrong business outcomes
  despite successful completion), and stuck workflows. Provides patterns for
  interpreting event histories and common Temporal bug patterns.
user-invocable: false
---

# Temporal Workflow Investigation

## Investigation Strategy

When a developer reports a workflow issue, determine which category it falls
into and follow the appropriate path. Many issues start as one and reveal
the other.

### Path A: Developer reports an error or failure
1. If they have a workflow ID: `get_workflow_history` -> look at `failure` field
2. If they don't: `list_workflows` with status `failed` or `timed_out` filtered
   to the relevant workflow type and time range
3. Check `pending_activities` and retry counts — is it a transient or persistent failure?
4. Check `describe_task_queue` — are workers healthy and polling?
5. Cross-reference the failure with the source code to suggest a fix

### Path B: Developer reports wrong behavior (no error)
1. Get the workflow ID for the problematic execution
2. `get_workflow_history` at `standard` detail level
3. Trace the data flow: examine each activity's input and output sequentially
4. Look for: unexpected values, missing fields, wrong types, activities that
   should have run but didn't, activities that ran but shouldn't have
5. If the developer has a "known good" execution: `compare_executions` to
   find exactly where the data diverges
6. If this might be widespread: `search_workflow_data` to count affected executions

### Path C: Developer reports a stuck workflow
1. `get_workflow_stack_trace` to see where it's blocked
2. Check: waiting on signal that won't arrive? Activity in infinite retry loop?
   Timer set for wrong duration?
3. `describe_task_queue` to verify workers are polling
4. If stuck on a signal: trace back to what should have sent it

## Interpreting Event History

When reading a workflow timeline, pay attention to:

- **Data handoffs between activities:** Does the output of activity N correctly
  become the input of activity N+1? Type mismatches, missing fields, and
  incorrect mappings are the #1 source of silent failures.
- **Retry counts > 0:** Even if the activity eventually succeeded, retries
  indicate instability. Check if the retry produced different results.
- **Activity duration anomalies:** An activity that usually takes 200ms but
  took 15s might have returned stale or incorrect data.
- **Missing activities:** If the workflow completed but an expected activity
  never ran, a conditional branch likely evaluated incorrectly.
- **Signal timing:** Signals received before or after expected can cause
  race conditions in workflow logic.

## Common Temporal Bug Patterns

- **Payload serialization mismatch:** Activity returns an object but the
  workflow receives `undefined` or a mangled version. Check if custom data
  converters are involved.
- **Non-deterministic replay breakage:** Workflow code was changed while
  executions were running. Check if `versions_active` in task queue shows
  multiple versions.
- **Stale closure capture:** Activity input was captured before a previous
  activity's result was awaited, so it contains the initial value instead
  of the computed value.
- **Silent swallowed errors:** Activity catches an exception and returns a
  default value instead of propagating the failure. The workflow thinks
  everything is fine.
- **Race condition between signal and timer:** Signal arrives after the
  timeout branch was already taken, leading to unexpected behavior.
