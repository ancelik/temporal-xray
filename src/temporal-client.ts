import { Connection, Client } from "@temporalio/client";
import type { DecodedPayload } from "./types.js";

const textDecoder = new TextDecoder();

let connectionInstance: Connection | null = null;
const clientCache = new Map<string, Client>();

export interface TemporalConfig {
  address: string;
  namespace: string;
  tlsCertPath?: string;
  tlsKeyPath?: string;
  apiKey?: string;
}

let activeConfig: TemporalConfig | null = null;

function getConfig(): TemporalConfig {
  if (activeConfig) return activeConfig;
  return {
    address: process.env.TEMPORAL_ADDRESS || "localhost:7233",
    namespace: process.env.TEMPORAL_NAMESPACE || "default",
    tlsCertPath: process.env.TEMPORAL_TLS_CERT_PATH || undefined,
    tlsKeyPath: process.env.TEMPORAL_TLS_KEY_PATH || undefined,
    apiKey: process.env.TEMPORAL_API_KEY || undefined,
  };
}

async function buildTlsConfig(
  config: TemporalConfig
): Promise<import("@temporalio/client").TLSConfig | undefined> {
  if (!config.tlsCertPath && !config.tlsKeyPath && !config.apiKey) {
    return undefined;
  }

  if (config.apiKey) {
    // API key auth (Temporal Cloud) — TLS is required but certs are handled by the cloud
    return {};
  }

  if (config.tlsCertPath && config.tlsKeyPath) {
    const fs = await import("fs");
    return {
      clientCertPair: {
        crt: fs.readFileSync(config.tlsCertPath),
        key: fs.readFileSync(config.tlsKeyPath),
      },
    };
  }

  return undefined;
}

async function ensureConnection(): Promise<Connection> {
  if (connectionInstance) return connectionInstance;

  const config = getConfig();
  const tls = await buildTlsConfig(config);

  const connectionOptions: import("@temporalio/client").ConnectionOptions = {
    address: config.address,
    tls,
  };

  // Add API key metadata if configured
  if (config.apiKey) {
    connectionOptions.metadata = {
      "temporal-namespace": config.namespace,
    };
    connectionOptions.apiKey = config.apiKey;
  }

  try {
    connectionInstance = await Connection.connect(connectionOptions);
    return connectionInstance;
  } catch (error) {
    const message =
      error instanceof Error ? error.message : String(error);
    throw new Error(
      `Cannot connect to Temporal server at ${config.address}. Verify TEMPORAL_ADDRESS is correct and the server is running. Details: ${message}`
    );
  }
}

/**
 * Get a Temporal client for the given namespace.
 * If no namespace is provided, uses the configured default.
 * Clients are cached per namespace and share the same connection.
 */
export async function getTemporalClient(
  namespace?: string
): Promise<Client> {
  const config = getConfig();
  const effectiveNamespace = namespace || config.namespace;

  const cached = clientCache.get(effectiveNamespace);
  if (cached) return cached;

  // For API key auth with a non-default namespace, we need a new connection
  // because the temporal-namespace header is set at the connection level
  if (
    config.apiKey &&
    effectiveNamespace !== config.namespace &&
    connectionInstance
  ) {
    const tls = await buildTlsConfig(config);
    const conn = await Connection.connect({
      address: config.address,
      tls,
      metadata: { "temporal-namespace": effectiveNamespace },
      apiKey: config.apiKey,
    });
    const client = new Client({ connection: conn, namespace: effectiveNamespace });
    clientCache.set(effectiveNamespace, client);
    return client;
  }

  const connection = await ensureConnection();
  const client = new Client({
    connection,
    namespace: effectiveNamespace,
  });
  clientCache.set(effectiveNamespace, client);
  return client;
}

/**
 * Connect to a different Temporal server. Closes the existing connection
 * and clears the client cache.
 */
export async function connectToServer(
  config: TemporalConfig
): Promise<{ address: string; namespace: string; authType: string }> {
  await closeConnection();
  activeConfig = config;

  // Verify the connection works
  await getTemporalClient();

  return getConnectionStatus();
}

/**
 * Get the current connection status.
 */
export function getConnectionStatus(): {
  address: string;
  namespace: string;
  authType: string;
  connected: boolean;
} {
  const config = getConfig();
  const authType = config.apiKey
    ? "api_key"
    : config.tlsCertPath
      ? "mtls"
      : "none";

  return {
    address: config.address,
    namespace: config.namespace,
    authType,
    connected: connectionInstance !== null,
  };
}

export async function closeConnection(): Promise<void> {
  clientCache.clear();
  if (connectionInstance) {
    await connectionInstance.close();
    connectionInstance = null;
  }
}

/**
 * Decode a Temporal payload into a usable value.
 * Handles JSON, protobuf, encrypted, and large payloads.
 */
export function decodePayload(
  payload: { data?: Uint8Array; metadata?: Record<string, Uint8Array> } | null | undefined,
  truncateAt?: number
): DecodedPayload {
  if (!payload || !payload.data) return null;

  const encoding = payload.metadata?.["encoding"]
    ? textDecoder.decode(payload.metadata["encoding"])
    : "";

  // Encrypted payloads
  if (encoding === "binary/encrypted" || encoding === "encoding/encrypted") {
    return {
      _type: "encrypted",
      note: "Payloads are encrypted. Configure a codec server endpoint for decryption.",
    };
  }

  // Protobuf payloads
  if (encoding === "binary/protobuf" || encoding.startsWith("json/protobuf")) {
    const messageType = payload.metadata?.["messageType"]
      ? textDecoder.decode(payload.metadata["messageType"])
      : "unknown";
    return {
      _type: "protobuf",
      messageType,
      note: "Install the project's protobuf definitions for full deserialization",
    };
  }

  // JSON payloads (default)
  try {
    const raw = textDecoder.decode(payload.data);

    // Large payload truncation
    if (truncateAt && payload.data.byteLength > truncateAt) {
      return {
        _truncated: true,
        preview: raw.slice(0, 500),
        fullSizeBytes: payload.data.byteLength,
      };
    }

    return JSON.parse(raw);
  } catch {
    // If not valid JSON, return as string
    return textDecoder.decode(payload.data);
  }
}

/**
 * Safely decode payloads from a Temporal Payload array.
 */
export function decodePayloads(
  payloads: Array<{ data?: Uint8Array; metadata?: Record<string, Uint8Array> }> | null | undefined,
  truncateAt?: number
): unknown[] {
  if (!payloads || payloads.length === 0) return [];
  return payloads.map((p) => decodePayload(p, truncateAt));
}

/**
 * Unwrap a single-element payload array to a single value.
 */
export function decodeSinglePayload(
  payloads: Array<{ data?: Uint8Array; metadata?: Record<string, Uint8Array> }> | null | undefined,
  truncateAt?: number
): unknown {
  const decoded = decodePayloads(payloads, truncateAt);
  return decoded.length === 1 ? decoded[0] : decoded.length === 0 ? null : decoded;
}
