---
name: setup
description: >
  Set up your Temporal connection. Guides you through connecting to local,
  cloud, or self-hosted Temporal servers.
argument-hint: "[local | cloud | self-hosted]"
---

Help the developer connect to their Temporal server.

## Step 1: Check current connection

Use the `temporal_connection` tool with action `status` to check if a
connection is already configured.

If connected, confirm the address and namespace and ask if this is correct.

## Step 2: Determine deployment type

If not connected or the developer wants to change, ask which Temporal
deployment they use:

### Local development server

The default configuration works out of the box:
- Address: `localhost:7233`
- Namespace: `default`

If the developer hasn't started their Temporal server yet, remind them:
```
temporal server start-dev
```

Use `temporal_connection` with action `connect` to verify the connection works.

### Temporal Cloud

The developer needs:
- **Address**: their namespace URL (e.g., `your-ns.tmprl.cloud:7233`)
- **Namespace**: their cloud namespace name
- **API Key**: a Temporal Cloud API key

Use `temporal_connection` with action `connect` and the provided credentials.

To make this persistent across sessions, they should set environment variables
before launching Claude Code:
```bash
export TEMPORAL_ADDRESS=your-ns.tmprl.cloud:7233
export TEMPORAL_NAMESPACE=your-namespace
export TEMPORAL_API_KEY=your-api-key
```

### Self-hosted with mTLS

The developer needs:
- **Address**: their Temporal server address
- **Namespace**: their namespace
- **TLS cert path**: path to client certificate
- **TLS key path**: path to client key

Use `temporal_connection` with action `connect` and the provided paths.

To make this persistent:
```bash
export TEMPORAL_ADDRESS=temporal.internal:7233
export TEMPORAL_NAMESPACE=production
export TEMPORAL_TLS_CERT_PATH=/path/to/client.pem
export TEMPORAL_TLS_KEY_PATH=/path/to/client.key
```

## Step 3: Verify

After connecting, run `list_workflows` with `limit: 1` to confirm the
connection is working and the namespace has data. Report the result to
the developer.

$ARGUMENTS
