from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from temporalio.client import Client, TLSConfig


@dataclass
class TemporalConfig:
    address: str = ""
    namespace: str = "default"
    tls_cert_path: str | None = None
    tls_key_path: str | None = None
    api_key: str | None = None


_connection_client: Client | None = None
_client_cache: dict[str, Client] = {}
_active_config: TemporalConfig | None = None


def _get_config() -> TemporalConfig:
    if _active_config:
        return _active_config
    return TemporalConfig(
        address=os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
        tls_cert_path=os.environ.get("TEMPORAL_TLS_CERT_PATH") or None,
        tls_key_path=os.environ.get("TEMPORAL_TLS_KEY_PATH") or None,
        api_key=os.environ.get("TEMPORAL_API_KEY") or None,
    )


def _build_tls_config(config: TemporalConfig) -> TLSConfig | None:
    if not config.tls_cert_path and not config.tls_key_path and not config.api_key:
        return None

    if config.api_key:
        # API key auth (Temporal Cloud) — TLS required but certs handled by cloud
        return TLSConfig()

    if config.tls_cert_path and config.tls_key_path:
        with open(config.tls_cert_path, "rb") as f:
            client_cert = f.read()
        with open(config.tls_key_path, "rb") as f:
            client_key = f.read()
        return TLSConfig(client_cert=client_cert, client_private_key=client_key)

    return None


async def _ensure_connection(config: TemporalConfig | None = None) -> Client:
    global _connection_client

    if _connection_client is not None:
        return _connection_client

    cfg = config or _get_config()
    tls = _build_tls_config(cfg)

    try:
        _connection_client = await Client.connect(
            cfg.address,
            namespace=cfg.namespace,
            tls=tls or False,
            api_key=cfg.api_key,
        )
        return _connection_client
    except Exception as e:
        raise RuntimeError(
            f"Cannot connect to Temporal server at {cfg.address}. "
            f"Verify TEMPORAL_ADDRESS is correct and the server is running. Details: {e}"
        ) from e


async def get_temporal_client(namespace: str | None = None) -> Client:
    """Get a Temporal client for the given namespace.

    If no namespace is provided, uses the configured default.
    Clients are cached per namespace.
    """
    config = _get_config()
    effective_namespace = namespace or config.namespace

    cached = _client_cache.get(effective_namespace)
    if cached is not None:
        return cached

    # For API key auth with a non-default namespace, create a separate client
    if config.api_key and effective_namespace != config.namespace and _connection_client is not None:
        tls = _build_tls_config(config)
        client = await Client.connect(
            config.address,
            namespace=effective_namespace,
            tls=tls or False,
            api_key=config.api_key,
        )
        _client_cache[effective_namespace] = client
        return client

    client = await _ensure_connection()

    # If requesting a different namespace, create a new client for it
    if effective_namespace != config.namespace:
        tls = _build_tls_config(config)
        client = await Client.connect(
            config.address,
            namespace=effective_namespace,
            tls=tls or False,
            api_key=config.api_key,
        )

    _client_cache[effective_namespace] = client
    return client


async def connect_to_server(
    config: TemporalConfig,
) -> dict[str, Any]:
    """Connect to a different Temporal server."""
    global _active_config
    await close_connection()
    _active_config = config
    await get_temporal_client()
    return get_connection_status()


def get_connection_status() -> dict[str, Any]:
    """Get the current connection status."""
    config = _get_config()
    if config.api_key:
        auth_type = "api_key"
    elif config.tls_cert_path:
        auth_type = "mtls"
    else:
        auth_type = "none"

    return {
        "address": config.address,
        "namespace": config.namespace,
        "authType": auth_type,
        "connected": _connection_client is not None,
    }


async def close_connection() -> None:
    """Close the connection and clear caches."""
    global _connection_client
    _client_cache.clear()
    if _connection_client is not None:
        await _connection_client.service_client.disconnect()
        _connection_client = None


# --- Payload Decoding ---


DecodedPayload = (
    dict[str, Any] | list[Any] | str | int | float | bool | None
)


def decode_payload(
    payload: Any | None,
    truncate_at: int | None = None,
) -> DecodedPayload:
    """Decode a Temporal payload into a usable value."""
    if payload is None or not hasattr(payload, "data") or payload.data is None:
        return None

    encoding = ""
    if hasattr(payload, "metadata") and payload.metadata:
        enc_bytes = payload.metadata.get("encoding")
        if enc_bytes:
            encoding = enc_bytes.decode("utf-8") if isinstance(enc_bytes, (bytes, bytearray)) else str(enc_bytes)

    # Encrypted payloads
    if encoding in ("binary/encrypted", "encoding/encrypted"):
        return {
            "_type": "encrypted",
            "note": "Payloads are encrypted. Configure a codec server endpoint for decryption.",
        }

    # Protobuf payloads
    if encoding in ("binary/protobuf",) or encoding.startswith("json/protobuf"):
        message_type = "unknown"
        if hasattr(payload, "metadata") and payload.metadata:
            mt_bytes = payload.metadata.get("messageType")
            if mt_bytes:
                message_type = mt_bytes.decode("utf-8") if isinstance(mt_bytes, (bytes, bytearray)) else str(mt_bytes)
        return {
            "_type": "protobuf",
            "messageType": message_type,
            "note": "Install the project's protobuf definitions for full deserialization",
        }

    # JSON payloads (default)
    try:
        data = payload.data
        if isinstance(data, (bytes, bytearray)):
            raw = data.decode("utf-8")
        else:
            raw = str(data)

        if truncate_at and len(data) > truncate_at:
            return {
                "_truncated": True,
                "preview": raw[:500],
                "fullSizeBytes": len(data),
            }

        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        if isinstance(data, (bytes, bytearray)):
            return data.decode("utf-8", errors="replace")
        return str(data)


def decode_payloads(
    payloads: Any | None,
    truncate_at: int | None = None,
) -> list[Any]:
    """Decode a list of Temporal payloads."""
    if not payloads:
        return []
    return [decode_payload(p, truncate_at) for p in payloads]


def decode_single_payload(
    payloads: Any | None,
    truncate_at: int | None = None,
) -> Any:
    """Unwrap a single-element payload array to a single value."""
    decoded = decode_payloads(payloads, truncate_at)
    if len(decoded) == 1:
        return decoded[0]
    if len(decoded) == 0:
        return None
    return decoded
