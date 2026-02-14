# temporal-xray

A [Claude Code plugin](https://code.claude.com/docs/en/plugins-reference) that gives Claude read-only access to your Temporal workflow executions. Debug both obvious failures and silent business logic bugs without leaving your editor.

```
You: "Order 12345 was double-charged"

Claude: [uses list_workflows to find the execution]
        [uses get_workflow_history to trace the data flow]
        [reads your source code to correlate]

        "The CalculateTotal activity returned $161.99 but ChargePayment
         received $0.00. There's a bug on line 45 of orderWorkflow.ts
         where the total variable is captured before the await resolves."
```

## The Problem

Debugging Temporal workflows requires constant context-switching: open the Temporal UI, find the execution, scroll through event history, copy errors, paste into your editor, explain the context. This is slow even for obvious failures.

For silent failures — workflows that complete successfully but produce wrong business outcomes — it's worse. You have to manually trace data through every activity to find where things went wrong.

temporal-xray eliminates this by giving Claude direct access to your execution data.

## Tools

| Tool | What it does |
|---|---|
| `list_workflows` | Search executions by type, status, ID, time range, or raw visibility query |
| `get_workflow_history` | Get the execution timeline with activity inputs/outputs at three detail levels (summary, standard, full) |
| `get_workflow_stack_trace` | See where a running workflow is blocked and what it's waiting for |
| `compare_executions` | Diff two executions to find exactly where data or structure diverges |
| `describe_task_queue` | Check worker health, polling status, and version consistency |
| `search_workflow_data` | Count or sample executions matching a pattern across your namespace |
| `temporal_connection` | Check or switch Temporal server connections for multi-environment workflows |

All debugging tools accept an optional `namespace` parameter, so you can query different namespaces without reconfiguring.

All tools are strictly read-only. The plugin never calls any mutating Temporal API.

## Installation

### Prerequisites

- [Claude Code](https://claude.ai/download) CLI
- Node.js 18+
- A running Temporal server (local, self-hosted, or Temporal Cloud)

### Install the plugin

```bash
# Add the temporal-xray marketplace and install
claude plugin marketplace add ancelik/temporal-xray
claude plugin install temporal-xray@temporal-xray
```

Or for development, point directly at a local clone:

```bash
git clone https://github.com/ancelik/temporal-xray.git
claude --plugin-dir ./temporal-xray
```

### Configure your Temporal connection

Set environment variables before launching Claude Code:

```bash
# Local development (defaults)
export TEMPORAL_ADDRESS=localhost:7233
export TEMPORAL_NAMESPACE=default

# Temporal Cloud
export TEMPORAL_ADDRESS=your-namespace.tmprl.cloud:7233
export TEMPORAL_API_KEY=your-api-key

# Self-hosted with mTLS
export TEMPORAL_ADDRESS=temporal.internal:7233
export TEMPORAL_TLS_CERT_PATH=/path/to/client.pem
export TEMPORAL_TLS_KEY_PATH=/path/to/client.key
```

If no environment variables are set, the plugin defaults to `localhost:7233` with the `default` namespace.

### First-time setup

Run the setup skill to get guided through connecting to your Temporal server:

```
/temporal-xray:setup
```

## Usage

### Slash command

```
/temporal-xray:inspect order-12345
```

### Natural language

Just describe the problem. Claude will use the tools automatically:

```
"Why did the refund workflow for customer cust-789 fail?"

"This workflow completed but the notification was never sent"

"Compare order-11111 (working) with order-22222 (broken)"

"How many workflows completed with a zero-dollar total today?"

"Is anyone polling the order-workers task queue?"
```

### Multiple environments

You can work with multiple Temporal servers and namespaces without restarting:

```
"Check the payments namespace for failed workflows"

"Switch to the staging server at staging.tmprl.cloud:7233"

"Compare the production execution with the staging one"
```

All tools accept a `namespace` parameter for per-call namespace targeting. Use `temporal_connection` to switch servers entirely.

### Investigator subagent

The plugin includes a `temporal-investigator` subagent that Claude can delegate to for complex investigations. It has persistent memory, so it builds up knowledge about your codebase's Temporal patterns over time.

## Examples

### 1. Debugging a failed workflow

A developer reports that order processing is failing for some customers:

> "Orders are failing for customers in the EU region since this morning"

Claude uses `list_workflows` to find recent failed OrderWorkflow executions, then `get_workflow_history` to pull the timeline. It discovers that the ChargePayment activity is failing with a "currency conversion service unavailable" error after 3 retries. Claude cross-references the error with the source code and suggests adding a fallback currency provider, pointing to the exact file and line where the retry policy should be updated.

### 2. Tracing a silent business logic bug

A workflow completes successfully but the customer was charged the wrong amount:

> "Order order-55501 was charged $149.99 but the discount code should have brought it to $134.99. Order order-55490 from yesterday worked correctly with the same code."

Claude uses `compare_executions` to diff the two workflows. It finds that the "good" execution applied the discount but the "bad" one didn't — despite identical inputs. Claude reads the activity source and finds a cache expiration race condition. Then uses `search_workflow_data` to find 14 other affected orders.

### 3. Diagnosing a stuck workflow

A workflow has been running for 90 minutes when it normally completes in under 2:

> "Workflow refund-78432 has been stuck for over an hour"

Claude uses `get_workflow_stack_trace` and sees the workflow is blocked waiting for a signal that never arrived. It checks `describe_task_queue` and finds two worker versions active — the older version has a bug where the signal is skipped on the retry path. Claude identifies the exact code change between versions and suggests the fix.

## Architecture

```
Claude Code
  |
  |  /temporal-xray:inspect
  v
Skills & Agent          (investigation strategy + domain knowledge)
  |
  v
MCP Server (TypeScript) (7 tools via MCP protocol)
  |
  |  gRPC
  v
Temporal Server         (local, cloud, or self-hosted)
```

The plugin has three layers:

1. **MCP Server** — TypeScript process wrapping `@temporalio/client` that translates Temporal's gRPC API into MCP tool calls
2. **Skills** — `temporal-debugging` teaches Claude how to investigate workflows; `inspect` is the user-facing entry point
3. **Subagent** — `temporal-investigator` runs complex investigations with persistent memory

## Payload Handling

The plugin handles various payload encodings:

| Encoding | Behavior |
|---|---|
| **JSON** (default) | Deserialized and returned as structured data |
| **Protobuf** | Detected by metadata; returns type info with a note to install proto definitions |
| **Encrypted** | Detected by metadata; returns a note to configure a codec server |
| **Large (>10KB)** | Truncated at summary level with a preview; full data at standard/full levels |

## Security

- All operations are strictly read-only
- No workflow mutations (start, signal, terminate, cancel, reset)
- No data is cached, stored, or logged by the plugin
- Credentials should be scoped to read-only namespace permissions

## Project Structure

```
temporal-xray/
├── .claude-plugin/plugin.json     Plugin manifest
├── .mcp.json                      MCP server configuration
├── agents/
│   └── temporal-investigator.md   Investigator subagent
├── skills/
│   ├── inspect/SKILL.md           User-facing /inspect skill
│   ├── setup/SKILL.md             Connection setup guide
│   └── temporal-debugging/SKILL.md  Investigation knowledge base
├── src/
│   ├── index.ts                   MCP server entry point
│   ├── temporal-client.ts         Temporal connection management
│   ├── types.ts                   Zod schemas and TypeScript types
│   ├── tools/                     7 tool implementations
│   └── transformers/              History summarizer, diff engine, event filter
├── package.json
└── tsconfig.json
```

## Development

```bash
git clone https://github.com/ancelik/temporal-xray.git
cd temporal-xray
npm install
npm run build

# Test with Claude Code
claude --plugin-dir .
```

## License

MIT
