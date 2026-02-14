"""Temporal client connection management and payload utilities."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from temporalio.client import Client, TLSConfig


@dataclass
class TemporalConfig:
    address: str = ""
    namespace: str = "default"
    tls_cert_path: str | None = None
    tls_key_path: str | None = None
    api_key: str | None = None


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


def _build_tls(config: TemporalConfig) -> TLSConfig | bool:
    """Build TLS config. Returns False for plaintext, TLSConfig for secure."""
    if config.api_key:
        return TLSConfig()  # Temporal Cloud: TLS required, certs managed by cloud
    if config.tls_cert_path and config.tls_key_path:
        with open(config.tls_cert_path, "rb") as f:
            cert = f.read()
        with open(config.tls_key_path, "rb") as f:
            key = f.read()
        return TLSConfig(client_cert=cert, client_private_key=key)
    return False


async def get_temporal_client(namespace: str | None = None) -> Client:
    """Get a cached Temporal client for the given namespace."""
    config = _get_config()
    ns = namespace or config.namespace

    if ns in _client_cache:
        return _client_cache[ns]

    try:
        client = await Client.connect(
            config.address,
            namespace=ns,
            tls=_build_tls(config),
            api_key=config.api_key,
        )
    except Exception as e:
        raise RuntimeError(
            f"Cannot connect to Temporal at {config.address}: {e}"
        ) from e

    _client_cache[ns] = client
    return client


async def connect_to_server(config: TemporalConfig) -> dict[str, Any]:
    """Switch to a different Temporal server. Clears all cached clients."""
    global _active_config
    await close_connection()
    _active_config = config
    await get_temporal_client()
    return get_connection_status()


def get_connection_status() -> dict[str, Any]:
    config = _get_config()
    auth = "api_key" if config.api_key else "mtls" if config.tls_cert_path else "none"
    return {
        "address": config.address,
        "namespace": config.namespace,
        "authType": auth,
        "connected": len(_client_cache) > 0,
    }


async def close_connection() -> None:
    for client in _client_cache.values():
        await client.service_client.disconnect()
    _client_cache.clear()


# --- Payload Utilities ---


def decode_payload(payload: Any, truncate_at: int | None = None) -> Any:
    """Decode a single Temporal payload (handles JSON, protobuf, encrypted, large)."""
    if payload is None or not hasattr(payload, "data") or payload.data is None:
        return None

    encoding = ""
    if hasattr(payload, "metadata") and payload.metadata:
        enc = payload.metadata.get("encoding")
        if enc:
            encoding = enc.decode("utf-8") if isinstance(enc, (bytes, bytearray)) else str(enc)

    if encoding in ("binary/encrypted", "encoding/encrypted"):
        return {"_type": "encrypted", "note": "Payloads are encrypted. Configure a codec server for decryption."}

    if encoding == "binary/protobuf" or encoding.startswith("json/protobuf"):
        mt = payload.metadata.get("messageType", b"") if payload.metadata else b""
        msg_type = mt.decode("utf-8") if isinstance(mt, (bytes, bytearray)) else str(mt) if mt else "unknown"
        return {"_type": "protobuf", "messageType": msg_type, "note": "Install protobuf definitions for full deserialization"}

    try:
        raw = payload.data if isinstance(payload.data, (bytes, bytearray)) else payload.data
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        if truncate_at and len(raw) > truncate_at:
            return {"_truncated": True, "preview": text[:500], "fullSizeBytes": len(raw)}
        return json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return payload.data.decode("utf-8", errors="replace") if isinstance(payload.data, (bytes, bytearray)) else str(payload.data)


def decode_payloads(payloads: Any, truncate_at: int | None = None) -> Any:
    """Decode a Temporal Payloads wrapper. Returns single value if one element, list otherwise."""
    if not payloads:
        return None
    items = [decode_payload(p, truncate_at) for p in payloads]
    if len(items) == 1:
        return items[0]
    return items if items else None


# --- Timestamp Utilities ---


def format_timestamp(ts: Any) -> str | None:
    """Convert a Temporal timestamp (datetime or protobuf) to ISO string."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.isoformat()
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    if hasattr(ts, "seconds"):
        secs = int(ts.seconds or 0)
        nanos = int(ts.nanos) if hasattr(ts, "nanos") and ts.nanos else 0
        return datetime.fromtimestamp(secs + nanos / 1e9, tz=timezone.utc).isoformat()
    return None


def timestamp_to_ms(ts: Any) -> float | None:
    """Convert timestamp to milliseconds since epoch."""
    if ts is None:
        return None
    if hasattr(ts, "timestamp"):
        return ts.timestamp() * 1000
    if hasattr(ts, "seconds"):
        secs = int(ts.seconds or 0)
        nanos = int(ts.nanos) if hasattr(ts, "nanos") and ts.nanos else 0
        return secs * 1000 + nanos / 1_000_000
    return None


def format_duration(duration: Any) -> str:
    """Format a protobuf Duration to human-readable string."""
    if duration is None:
        return "unknown"
    if hasattr(duration, "total_seconds"):
        secs = int(duration.total_seconds())
    elif hasattr(duration, "seconds"):
        secs = int(duration.seconds or 0)
    else:
        return "unknown"
    if secs >= 3600:
        return f"{round(secs / 3600)}h"
    if secs >= 60:
        return f"{round(secs / 60)}m"
    return f"{secs}s"


# --- Workflow Summary ---


def to_workflow_summary(workflow: Any) -> dict[str, Any]:
    """Convert a Temporal workflow listing entry to a summary dict."""
    start = workflow.start_time
    close = workflow.close_time
    duration_ms = None
    if start and close:
        duration_ms = int((close - start).total_seconds() * 1000)

    search_attrs: dict[str, Any] = {}
    if workflow.search_attributes:
        for key, values in workflow.search_attributes.items():
            search_attrs[str(key)] = values[0] if len(values) == 1 else list(values)

    return {
        "workflow_id": workflow.id,
        "run_id": workflow.run_id,
        "workflow_type": workflow.workflow_type,
        "status": workflow.status.name if hasattr(workflow.status, "name") else str(workflow.status),
        "start_time": start.isoformat() if start else "",
        "close_time": close.isoformat() if close else None,
        "duration_ms": duration_ms,
        "task_queue": workflow.task_queue,
        "search_attributes": search_attrs,
    }
