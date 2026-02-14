"""Tests for temporal_xray.client — payload decoding, timestamps, connection status."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from temporal_xray.client import (
    TemporalConfig,
    decode_payload,
    decode_payloads,
    format_duration,
    format_timestamp,
    get_connection_status,
    timestamp_to_ms,
    to_workflow_summary,
)
from conftest import make_mock_workflow_info, make_payload


# ── decode_payload ──────────────────────────────────────────────


class TestDecodePayload:
    def test_none_payload(self):
        assert decode_payload(None) is None

    def test_no_data_attribute(self):
        assert decode_payload(SimpleNamespace(metadata={})) is None

    def test_null_data(self):
        assert decode_payload(SimpleNamespace(data=None, metadata={})) is None

    def test_json_payload(self):
        p = make_payload(b'{"key": "value"}')
        result = decode_payload(p)
        assert result == {"key": "value"}

    def test_json_number(self):
        p = make_payload(b"42")
        assert decode_payload(p) == 42

    def test_json_string(self):
        p = make_payload(b'"hello"')
        assert decode_payload(p) == "hello"

    def test_json_array(self):
        p = make_payload(b'[1, 2, 3]')
        assert decode_payload(p) == [1, 2, 3]

    def test_encrypted_payload(self):
        p = make_payload(b"ciphertext", encoding="binary/encrypted")
        result = decode_payload(p)
        assert result["_type"] == "encrypted"
        assert "codec server" in result["note"]

    def test_encoding_encrypted_variant(self):
        p = make_payload(b"ciphertext", encoding="encoding/encrypted")
        result = decode_payload(p)
        assert result["_type"] == "encrypted"

    def test_protobuf_payload(self):
        p = make_payload(
            b"\x08\x01",
            encoding="binary/protobuf",
            metadata={"messageType": "temporal.api.common.v1.Payload"},
        )
        result = decode_payload(p)
        assert result["_type"] == "protobuf"
        assert result["messageType"] == "temporal.api.common.v1.Payload"

    def test_json_protobuf_variant(self):
        p = make_payload(
            b'{"foo": 1}',
            encoding="json/protobuf",
            metadata={"messageType": "MyProto"},
        )
        result = decode_payload(p)
        assert result["_type"] == "protobuf"

    def test_truncation(self):
        big_data = json.dumps({"x": "a" * 20000}).encode()
        p = make_payload(big_data)
        result = decode_payload(p, truncate_at=100)
        assert result["_truncated"] is True
        assert "preview" in result
        assert result["fullSizeBytes"] == len(big_data)

    def test_no_truncation_when_small(self):
        p = make_payload(b'{"small": true}')
        result = decode_payload(p, truncate_at=10000)
        assert result == {"small": True}

    def test_non_json_fallback(self):
        p = make_payload(b"not json at all")
        result = decode_payload(p)
        assert result == "not json at all"

    def test_binary_non_utf8(self):
        p = make_payload(b"\xff\xfe\x00\x01", encoding="binary/plain")
        result = decode_payload(p)
        assert isinstance(result, str)

    def test_string_encoding_metadata(self):
        """Encoding metadata as str instead of bytes."""
        p = SimpleNamespace(
            data=b'{"a": 1}',
            metadata={"encoding": "json/plain"},  # str, not bytes
        )
        result = decode_payload(p)
        assert result == {"a": 1}


# ── decode_payloads ─────────────────────────────────────────────


class TestDecodePayloads:
    def test_none(self):
        assert decode_payloads(None) is None

    def test_empty(self):
        assert decode_payloads([]) is None

    def test_single_payload_unwrapped(self):
        result = decode_payloads([make_payload(b'{"x": 1}')])
        assert result == {"x": 1}

    def test_multiple_payloads_returned_as_list(self):
        result = decode_payloads([make_payload(b"1"), make_payload(b"2")])
        assert result == [1, 2]


# ── format_timestamp ────────────────────────────────────────────


class TestFormatTimestamp:
    def test_none(self):
        assert format_timestamp(None) is None

    def test_datetime(self):
        dt = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        assert format_timestamp(dt) == "2026-01-15T10:00:00+00:00"

    def test_proto_timestamp(self):
        proto = SimpleNamespace(seconds=1736935200, nanos=500_000_000)
        result = format_timestamp(proto)
        assert result is not None
        assert "2025" in result  # epoch 1736935200 is Jan 2025

    def test_proto_timestamp_no_nanos(self):
        proto = SimpleNamespace(seconds=1736935200)
        result = format_timestamp(proto)
        assert result is not None

    def test_object_with_isoformat(self):
        obj = SimpleNamespace(isoformat=lambda: "2026-01-01T00:00:00Z")
        assert format_timestamp(obj) == "2026-01-01T00:00:00Z"

    def test_unrecognized_type(self):
        assert format_timestamp("not a timestamp") is None


# ── timestamp_to_ms ─────────────────────────────────────────────


class TestTimestampToMs:
    def test_none(self):
        assert timestamp_to_ms(None) is None

    def test_datetime_with_timestamp(self):
        dt = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        ms = timestamp_to_ms(dt)
        assert ms is not None
        assert ms == dt.timestamp() * 1000

    def test_proto_seconds(self):
        proto = SimpleNamespace(seconds=100, nanos=500_000_000)
        ms = timestamp_to_ms(proto)
        assert ms == 100_500.0


# ── format_duration ─────────────────────────────────────────────


class TestFormatDuration:
    def test_none(self):
        assert format_duration(None) == "unknown"

    def test_seconds(self):
        assert format_duration(SimpleNamespace(seconds=45)) == "45s"

    def test_minutes(self):
        assert format_duration(SimpleNamespace(seconds=120)) == "2m"

    def test_hours(self):
        assert format_duration(SimpleNamespace(seconds=7200)) == "2h"

    def test_timedelta(self):
        assert format_duration(timedelta(seconds=90)) == "2m"

    def test_unrecognized(self):
        assert format_duration("wat") == "unknown"


# ── to_workflow_summary ─────────────────────────────────────────


class TestToWorkflowSummary:
    def test_basic_summary(self):
        wf = make_mock_workflow_info(
            workflow_id="order-123",
            run_id="run-abc",
            workflow_type="OrderWorkflow",
            status_name="COMPLETED",
        )
        result = to_workflow_summary(wf)
        assert result["workflow_id"] == "order-123"
        assert result["run_id"] == "run-abc"
        assert result["workflow_type"] == "OrderWorkflow"
        assert result["status"] == "COMPLETED"
        assert result["task_queue"] == "default-queue"
        assert result["duration_ms"] is not None
        assert result["duration_ms"] > 0

    def test_running_workflow_no_close_time(self):
        wf = make_mock_workflow_info()
        wf.close_time = None
        result = to_workflow_summary(wf)
        assert result["close_time"] is None
        assert result["duration_ms"] is None

    def test_search_attributes_single_value(self):
        wf = make_mock_workflow_info()
        wf.search_attributes = {"Region": ["us-east"]}
        result = to_workflow_summary(wf)
        assert result["search_attributes"]["Region"] == "us-east"

    def test_search_attributes_multi_value(self):
        wf = make_mock_workflow_info()
        wf.search_attributes = {"Tags": ["a", "b", "c"]}
        result = to_workflow_summary(wf)
        assert result["search_attributes"]["Tags"] == ["a", "b", "c"]

    def test_no_search_attributes(self):
        wf = make_mock_workflow_info()
        wf.search_attributes = None
        result = to_workflow_summary(wf)
        assert result["search_attributes"] == {}

    def test_status_as_string_fallback(self):
        wf = make_mock_workflow_info()
        wf.status = "RUNNING"  # str, not namespace with .name
        result = to_workflow_summary(wf)
        assert result["status"] == "RUNNING"


# ── get_connection_status ───────────────────────────────────────


class TestGetConnectionStatus:
    def test_default_config(self, monkeypatch):
        import temporal_xray.client as mod
        monkeypatch.setattr(mod, "_active_config", None)
        monkeypatch.setattr(mod, "_client_cache", {})
        monkeypatch.delenv("TEMPORAL_ADDRESS", raising=False)
        monkeypatch.delenv("TEMPORAL_NAMESPACE", raising=False)
        monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)
        monkeypatch.delenv("TEMPORAL_TLS_CERT_PATH", raising=False)

        status = get_connection_status()
        assert status["address"] == "localhost:7233"
        assert status["namespace"] == "default"
        assert status["authType"] == "none"
        assert status["connected"] is False

    def test_api_key_auth_type(self, monkeypatch):
        import temporal_xray.client as mod
        monkeypatch.setattr(mod, "_active_config", TemporalConfig(
            address="cloud:7233", namespace="prod", api_key="secret",
        ))
        monkeypatch.setattr(mod, "_client_cache", {"prod": "fake"})

        status = get_connection_status()
        assert status["authType"] == "api_key"
        assert status["connected"] is True

    def test_mtls_auth_type(self, monkeypatch):
        import temporal_xray.client as mod
        monkeypatch.setattr(mod, "_active_config", TemporalConfig(
            address="self-hosted:7233", tls_cert_path="/cert", tls_key_path="/key",
        ))
        monkeypatch.setattr(mod, "_client_cache", {})

        status = get_connection_status()
        assert status["authType"] == "mtls"
