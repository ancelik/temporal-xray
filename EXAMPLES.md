# temporal-xray — Use Case Examples

## 1. Debugging a failed payment workflow

A developer reports that order processing is failing for some customers. They don't know which workflow or why.

```
Developer: "Orders are failing for customers in the EU region since this morning"
```

Claude uses `list_workflows` to find recent failed OrderWorkflow executions, then `get_workflow_history` to pull the timeline. It discovers that the ChargePayment activity is failing with a "currency conversion service unavailable" error after 3 retries. Claude cross-references the error with the source code and suggests adding a fallback currency provider, pointing to the exact file and line where the retry policy should be updated.

## 2. Tracing a silent business logic bug

A workflow completes successfully — no errors, status COMPLETED — but the customer was charged the wrong amount. The developer has a "good" order and a "bad" order.

```
Developer: "Order order-55501 was charged $149.99 but the discount code should have brought it to $134.99. Order order-55490 from yesterday worked correctly with the same discount code."
```

Claude uses `compare_executions` to diff the two workflows side by side. It finds that at step 2 (CalculateTotal), the "good" execution has `output.discountApplied: true` while the "bad" one has `output.discountApplied: false` — despite both having the same discount code in their inputs. Claude reads the CalculateTotal activity source and finds a race condition: the discount validation cache expires every 24 hours, and the bad execution hit a cold cache that defaulted to "no discount." Then uses `search_workflow_data` to find 14 other affected orders in the past 24 hours.

## 3. Diagnosing a stuck workflow

A workflow has been running for 90 minutes when it normally completes in under 2 minutes.

```
Developer: "Workflow refund-78432 has been stuck for over an hour"
```

Claude uses `get_workflow_stack_trace` and sees the workflow is blocked waiting for a `payment_confirmed` signal that never arrived. It checks `describe_task_queue` and finds two worker versions active (v2.3.0 and v2.3.1) — the signal should have been sent by another workflow running on v2.3.0 workers, but that version has a bug where the signal is only sent on the success path, not after a retry. The refund upstream activity succeeded on retry attempt 2, which took a different code path that skipped the signal. Claude identifies the exact code change between versions and suggests the fix.
