"""Tests for temporal_xray.server — MCP tool functions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temporal_xray.server import (
    STATUS_MAP,
    _escape,
    _json,
    _raise_friendly,
    compare_executions,
    describe_task_queue,
    get_workflow_history,
    get_workflow_stack_trace,
    list_workflows,
    search_workflow_data,
    temporal_connection,
)
from conftest import (
    MockAsyncIterator,
    _T0,
    make_failed_workflow_history,
    make_mock_client,
    make_mock_workflow_info,
    make_multi_activity_history,
    make_simple_completed_history,
)


# ── Helpers ─────────────────────────────────────────────────────


class TestEscape:
    def test_no_quotes(self):
        assert _escape("hello") == "hello"

    def test_single_quotes(self):
        assert _escape("it's") == "it''s"

    def test_multiple_quotes(self):
        assert _escape("a'b'c") == "a''b''c"


class TestJson:
    def test_dict(self):
        result = _json({"a": 1})
        assert json.loads(result) == {"a": 1}

    def test_datetime_serialized(self):
        result = _json({"t": datetime(2026, 1, 1)})
        parsed = json.loads(result)
        assert "2026" in parsed["t"]


class TestRaiseFriendly:
    def test_namespace_not_found(self):
        with pytest.raises(RuntimeError, match="Namespace not found"):
            _raise_friendly(Exception("namespace 'prod' not found"), "test")

    def test_unavailable(self):
        with pytest.raises(RuntimeError, match="Cannot connect"):
            _raise_friendly(Exception("UNAVAILABLE: server down"), "test")

    def test_connect_error(self):
        with pytest.raises(RuntimeError, match="Cannot connect"):
            _raise_friendly(Exception("failed to connect"), "test")

    def test_not_found(self):
        with pytest.raises(RuntimeError, match="Not found"):
            _raise_friendly(Exception("workflow not found"), "test")

    def test_permission(self):
        with pytest.raises(RuntimeError, match="Permission denied"):
            _raise_friendly(Exception("permission denied for namespace"), "test")

    def test_unauthorized(self):
        with pytest.raises(RuntimeError, match="Permission denied"):
            _raise_friendly(Exception("Unauthorized request"), "test")

    def test_generic_error(self):
        with pytest.raises(RuntimeError, match="Failed to do stuff"):
            _raise_friendly(Exception("weird error"), "do stuff")


class TestStatusMap:
    def test_all_statuses_present(self):
        expected = {"running", "completed", "failed", "timed_out", "cancelled", "terminated"}
        assert set(STATUS_MAP.keys()) == expected


# ── list_workflows ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestListWorkflows:
    @patch("temporal_xray.server.get_temporal_client")
    async def test_basic_list(self, mock_get_client):
        client = make_mock_client()
        mock_get_client.return_value = client

        result = await list_workflows()
        data = json.loads(result)

        assert "workflows" in data
        assert data["total_count"] == 1
        assert data["has_more"] is False
        assert data["workflows"][0]["workflow_id"] == "wf-1"

    @patch("temporal_xray.server.get_temporal_client")
    async def test_filter_by_type(self, mock_get_client):
        client = make_mock_client()
        mock_get_client.return_value = client

        await list_workflows(workflow_type="OrderWorkflow")
        call_args = client.list_workflows.call_args
        assert "WorkflowType = 'OrderWorkflow'" in (call_args.kwargs.get("query") or "")

    @patch("temporal_xray.server.get_temporal_client")
    async def test_filter_by_status(self, mock_get_client):
        client = make_mock_client()
        mock_get_client.return_value = client

        await list_workflows(status="failed")
        call_args = client.list_workflows.call_args
        assert "ExecutionStatus = 'Failed'" in (call_args.kwargs.get("query") or "")

    @patch("temporal_xray.server.get_temporal_client")
    async def test_raw_query(self, mock_get_client):
        client = make_mock_client()
        mock_get_client.return_value = client

        await list_workflows(query="CustomField = 'test'")
        call_args = client.list_workflows.call_args
        assert call_args.kwargs.get("query") == "CustomField = 'test'"

    @patch("temporal_xray.server.get_temporal_client")
    async def test_limit_respected(self, mock_get_client):
        workflows = [make_mock_workflow_info(workflow_id=f"wf-{i}") for i in range(10)]
        client = make_mock_client(workflows=workflows)
        mock_get_client.return_value = client

        result = await list_workflows(limit=3)
        data = json.loads(result)
        assert data["total_count"] == 3
        assert data["has_more"] is True

    @patch("temporal_xray.server.get_temporal_client")
    async def test_passes_namespace(self, mock_get_client):
        mock_get_client.return_value = make_mock_client()
        await list_workflows(namespace="production")
        mock_get_client.assert_called_with("production")

    @patch("temporal_xray.server.get_temporal_client")
    async def test_combined_filters(self, mock_get_client):
        client = make_mock_client()
        mock_get_client.return_value = client

        await list_workflows(
            workflow_type="Order",
            workflow_id="order-1",
            status="completed",
            start_time_from="2026-01-01T00:00:00Z",
        )
        q = client.list_workflows.call_args.kwargs.get("query") or ""
        assert "WorkflowType = 'Order'" in q
        assert "WorkflowId = 'order-1'" in q
        assert "ExecutionStatus = 'Completed'" in q
        assert "StartTime >= '2026-01-01T00:00:00Z'" in q

    @patch("temporal_xray.server.get_temporal_client")
    async def test_status_all_excluded(self, mock_get_client):
        client = make_mock_client()
        mock_get_client.return_value = client

        await list_workflows(status="all")
        q = client.list_workflows.call_args.kwargs.get("query")
        assert q is None  # empty string → passed as None


# ── get_workflow_history ────────────────────────────────────────


@pytest.mark.asyncio
class TestGetWorkflowHistory:
    @patch("temporal_xray.server.get_temporal_client")
    async def test_basic_history(self, mock_get_client):
        client = make_mock_client()
        mock_get_client.return_value = client

        result = await get_workflow_history(workflow_id="wf-1")
        data = json.loads(result)

        assert data["workflow_id"] == "wf-1"
        assert data["workflow_type"] == "OrderWorkflow"
        assert data["status"] == "COMPLETED"
        assert len(data["timeline"]) >= 1

    @patch("temporal_xray.server.get_temporal_client")
    async def test_empty_events_raises(self, mock_get_client):
        client = make_mock_client(events=[])
        mock_get_client.return_value = client

        with pytest.raises(RuntimeError, match="No workflow found"):
            await get_workflow_history(workflow_id="wf-missing")

    @patch("temporal_xray.server.get_temporal_client")
    async def test_passes_namespace(self, mock_get_client):
        mock_get_client.return_value = make_mock_client()
        await get_workflow_history(workflow_id="wf-1", namespace="staging")
        mock_get_client.assert_called_with("staging")

    @patch("temporal_xray.server.get_temporal_client")
    async def test_failed_workflow(self, mock_get_client):
        client = make_mock_client(events=make_failed_workflow_history())
        mock_get_client.return_value = client

        result = await get_workflow_history(workflow_id="wf-fail")
        data = json.loads(result)
        assert data["status"] == "FAILED"
        assert data["failure"] is not None


# ── get_workflow_stack_trace ────────────────────────────────────


@pytest.mark.asyncio
class TestGetWorkflowStackTrace:
    @patch("temporal_xray.server.get_temporal_client")
    async def test_basic_trace(self, mock_get_client):
        client = make_mock_client(status_name="RUNNING")
        mock_get_client.return_value = client

        result = await get_workflow_stack_trace(workflow_id="wf-1")
        data = json.loads(result)

        assert data["workflow_id"] == "wf-1"
        assert data["status"] == "RUNNING"
        assert "goroutine" in data["stack_trace"]
        assert data["duration_so_far_ms"] >= 0

    @patch("temporal_xray.server.get_temporal_client")
    async def test_query_failure_graceful(self, mock_get_client):
        client = make_mock_client()
        handle = client.get_workflow_handle()
        handle.query = AsyncMock(side_effect=Exception("query not supported"))
        mock_get_client.return_value = client

        result = await get_workflow_stack_trace(workflow_id="wf-1")
        data = json.loads(result)
        assert "unavailable" in data["stack_trace"].lower()

    @patch("temporal_xray.server.get_temporal_client")
    async def test_pending_activities(self, mock_get_client):
        client = make_mock_client()
        handle = client.get_workflow_handle()
        handle.describe = AsyncMock(return_value=SimpleNamespace(
            run_id="run-1",
            status=SimpleNamespace(name="RUNNING"),
            start_time=_T0,
            raw=SimpleNamespace(
                pending_activities=[
                    SimpleNamespace(
                        activity_type=SimpleNamespace(name="SendEmail"),
                        state=1,
                        scheduled_time=_T0,
                        attempt=2,
                        last_failure=SimpleNamespace(message="timeout"),
                    ),
                ],
            ),
            raw_description=None,
        ))
        mock_get_client.return_value = client

        result = await get_workflow_stack_trace(workflow_id="wf-1")
        data = json.loads(result)
        assert len(data["pending_activities"]) == 1
        pa = data["pending_activities"][0]
        assert pa["activity_type"] == "SendEmail"
        assert pa["state"] == "SCHEDULED"
        assert pa["attempt"] == 2
        assert pa["last_failure"] == "timeout"


# ── compare_executions ──────────────────────────────────────────


@pytest.mark.asyncio
class TestCompareExecutions:
    @patch("temporal_xray.server.get_temporal_client")
    async def test_identical_executions(self, mock_get_client):
        client = make_mock_client(events=make_multi_activity_history())
        mock_get_client.return_value = client

        result = await compare_executions(
            workflow_id_a="wf-a", workflow_id_b="wf-b",
        )
        data = json.loads(result)

        assert data["same_workflow_type"] is True
        assert data["divergences"] == []
        assert data["structural_differences"]["activities_only_in_a"] == []

    @patch("temporal_xray.server.get_temporal_client")
    async def test_passes_namespace(self, mock_get_client):
        mock_get_client.return_value = make_mock_client(events=make_simple_completed_history())
        await compare_executions(
            workflow_id_a="a", workflow_id_b="b", namespace="staging",
        )
        mock_get_client.assert_called_with("staging")


# ── describe_task_queue ─────────────────────────────────────────


@pytest.mark.asyncio
class TestDescribeTaskQueue:
    @patch("temporal_xray.server.get_temporal_client")
    async def test_basic_describe(self, mock_get_client):
        poller = SimpleNamespace(
            identity="worker-1@host",
            last_access_time=_T0,
            rate_per_second=10.0,
            worker_version_capabilities=SimpleNamespace(build_id="v1.2.0"),
        )
        client = make_mock_client()
        client.workflow_service.describe_task_queue = AsyncMock(
            return_value=SimpleNamespace(pollers=[poller]),
        )
        mock_get_client.return_value = client

        result = await describe_task_queue(task_queue="my-queue")
        data = json.loads(result)

        assert data["task_queue"] == "my-queue"
        assert len(data["pollers"]) == 1
        assert data["pollers"][0]["identity"] == "worker-1@host"
        assert data["pollers"][0]["rate_per_second"] == 10.0
        assert "v1.2.0" in data["versions_active"]

    @patch("temporal_xray.server.get_temporal_client")
    async def test_empty_pollers(self, mock_get_client):
        client = make_mock_client()
        client.workflow_service.describe_task_queue = AsyncMock(
            return_value=SimpleNamespace(pollers=[]),
        )
        mock_get_client.return_value = client

        result = await describe_task_queue(task_queue="dead-queue")
        data = json.loads(result)
        assert data["pollers"] == []
        assert data["versions_active"] == []


# ── search_workflow_data ────────────────────────────────────────


@pytest.mark.asyncio
class TestSearchWorkflowData:
    @patch("temporal_xray.server.get_temporal_client")
    async def test_list_mode(self, mock_get_client):
        workflows = [make_mock_workflow_info(workflow_id=f"wf-{i}") for i in range(5)]
        client = make_mock_client(workflows=workflows)
        mock_get_client.return_value = client

        result = await search_workflow_data(
            workflow_type="OrderWorkflow",
            query="ExecutionStatus = 'Failed'",
        )
        data = json.loads(result)
        assert "workflows" in data
        assert data["count"] == 5

    @patch("temporal_xray.server.get_temporal_client")
    async def test_count_mode(self, mock_get_client):
        workflows = [make_mock_workflow_info(workflow_id=f"wf-{i}") for i in range(10)]
        client = make_mock_client(workflows=workflows)
        mock_get_client.return_value = client

        result = await search_workflow_data(
            workflow_type="OrderWorkflow",
            query="ExecutionStatus = 'Failed'",
            aggregate="count",
        )
        data = json.loads(result)
        assert data["count"] == 10
        assert len(data["sample_workflow_ids"]) == 3
        assert "workflows" not in data

    @patch("temporal_xray.server.get_temporal_client")
    async def test_sample_mode(self, mock_get_client):
        workflows = [make_mock_workflow_info(workflow_id=f"wf-{i}") for i in range(10)]
        client = make_mock_client(workflows=workflows)
        mock_get_client.return_value = client

        result = await search_workflow_data(
            workflow_type="OrderWorkflow",
            query="ExecutionStatus = 'Failed'",
            aggregate="sample",
            limit=5,
        )
        data = json.loads(result)
        assert data["count"] <= 5
        assert "workflows" not in data

    @patch("temporal_xray.server.get_temporal_client")
    async def test_prepends_workflow_type(self, mock_get_client):
        client = make_mock_client(workflows=[])
        mock_get_client.return_value = client

        await search_workflow_data(
            workflow_type="Order",
            query="ExecutionStatus = 'Failed'",
        )
        q = client.list_workflows.call_args.kwargs.get("query") or ""
        assert q.startswith("WorkflowType = 'Order'")

    @patch("temporal_xray.server.get_temporal_client")
    async def test_skips_prepend_when_present(self, mock_get_client):
        client = make_mock_client(workflows=[])
        mock_get_client.return_value = client

        await search_workflow_data(
            workflow_type="Order",
            query="WorkflowType = 'Order' AND status = 'Failed'",
        )
        q = client.list_workflows.call_args.kwargs.get("query") or ""
        assert not q.startswith("WorkflowType = 'Order' AND WorkflowType")


# ── temporal_connection ─────────────────────────────────────────


@pytest.mark.asyncio
class TestTemporalConnection:
    @patch("temporal_xray.server.get_connection_status")
    async def test_status_action(self, mock_status):
        mock_status.return_value = {
            "address": "localhost:7233", "namespace": "default",
            "authType": "none", "connected": False,
        }
        result = await temporal_connection(action="status")
        data = json.loads(result)
        assert data["address"] == "localhost:7233"
        assert data["connected"] is False

    async def test_connect_requires_params(self):
        with pytest.raises(RuntimeError, match="Provide at least"):
            await temporal_connection(action="connect")

    @patch("temporal_xray.server.connect_to_server")
    @patch("temporal_xray.server.get_connection_status")
    async def test_connect_action(self, mock_status, mock_connect):
        mock_status.return_value = {
            "address": "old:7233", "namespace": "default",
            "authType": "none", "connected": False,
        }
        mock_connect.return_value = {
            "address": "new:7233", "namespace": "prod",
            "authType": "api_key", "connected": True,
        }
        result = await temporal_connection(
            action="connect", address="new:7233", namespace="prod", api_key="secret",
        )
        data = json.loads(result)
        assert data["address"] == "new:7233"
        assert data["connected"] is True
        mock_connect.assert_called_once()
