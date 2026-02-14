import {
  getConnectionStatus,
  connectToServer,
  type TemporalConfig,
} from "../temporal-client.js";
import type { TemporalConnectionInput } from "../types.js";

export async function temporalConnection(
  input: TemporalConnectionInput
): Promise<{
  address: string;
  namespace: string;
  authType: string;
  connected: boolean;
}> {
  if (input.action === "connect") {
    if (!input.address && !input.namespace) {
      throw new Error(
        "Provide at least an address or namespace to connect. Example: { action: 'connect', address: 'localhost:7233', namespace: 'default' }"
      );
    }

    const current = getConnectionStatus();
    const config: TemporalConfig = {
      address: input.address || current.address,
      namespace: input.namespace || current.namespace,
      tlsCertPath: input.tls_cert_path,
      tlsKeyPath: input.tls_key_path,
      apiKey: input.api_key,
    };

    const status = await connectToServer(config);
    return { ...status, connected: true };
  }

  // Default: status
  return getConnectionStatus();
}
