import { Connection, Client } from "@temporalio/client";
import type { DecodedPayload } from "./types.js";

let clientInstance: Client | null = null;
let connectionInstance: Connection | null = null;

export interface TemporalConfig {
  address: string;
  namespace: string;
  tlsCertPath?: string;
  tlsKeyPath?: string;
  apiKey?: string;
}

function getConfig(): TemporalConfig {
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

export async function getTemporalClient(): Promise<Client> {
  if (clientInstance) return clientInstance;

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
    clientInstance = new Client({
      connection: connectionInstance,
      namespace: config.namespace,
    });
    return clientInstance;
  } catch (error) {
    const message =
      error instanceof Error ? error.message : String(error);
    throw new Error(
      `Cannot connect to Temporal server at ${config.address}. Verify TEMPORAL_ADDRESS is correct and the server is running. Details: ${message}`
    );
  }
}

export async function closeConnection(): Promise<void> {
  if (connectionInstance) {
    await connectionInstance.close();
    connectionInstance = null;
    clientInstance = null;
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
    ? new TextDecoder().decode(payload.metadata["encoding"])
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
      ? new TextDecoder().decode(payload.metadata["messageType"])
      : "unknown";
    return {
      _type: "protobuf",
      messageType,
      note: "Install the project's protobuf definitions for full deserialization",
    };
  }

  // JSON payloads (default)
  try {
    const raw = new TextDecoder().decode(payload.data);

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
    return new TextDecoder().decode(payload.data);
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
