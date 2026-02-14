"""Shared fixtures for temporal-xray tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# --- Payload Mocks ---


def make_payload(data: bytes | str, encoding: str = "json/plain", metadata: dict | None = None) -> SimpleNamespace:
    """Create a mock Temporal payload."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    meta = {"encoding": encoding.encode("utf-8")}
    if metadata:
        meta.update({k: v.encode("utf-8") if isinstance(v, str) else v for k, v in metadata.items()})
    return SimpleNamespace(data=data, metadata=meta)


def make_payloads(*payloads: SimpleNamespace) -> list[SimpleNamespace]:
    """Wrap payloads in a list (mimics Temporal Payloads)."""
    return list(payloads)


# --- Event Mocks ---


_T0 = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def make_event(
    event_type: int,
    event_id: int = 1,
    event_time: datetime | None = None,
    **attr_kwargs: Any,
) -> SimpleNamespace:
    """Create a mock Temporal history event.

    Extra kwargs are set as attributes on the event. For activity events, use
    the correct attribute name (e.g. activity_task_scheduled_event_attributes=...).
    """
    ev = SimpleNamespace(
        event_type=event_type,
        event_id=event_id,
        event_time=event_time or _T0,
    )
    for k, v in attr_kwargs.items():
        setattr(ev, k, v)
    return ev


def make_workflow_started_event(
    workflow_type: str = "OrderWorkflow",
    input_data: bytes = b'{"orderId": "123"}',
    event_time: datetime | None = None,
) -> SimpleNamespace:
    """Create a WorkflowExecutionStarted event (type=1)."""
    return make_event(
        event_type=1,
        event_id=1,
        event_time=event_time or _T0,
        workflow_execution_started_event_attributes=SimpleNamespace(
            workflow_type=SimpleNamespace(name=workflow_type),
            input=SimpleNamespace(payloads=[make_payload(input_data)]),
            task_queue=SimpleNamespace(name="default-queue"),
        ),
    )


def make_workflow_completed_event(
    result_data: bytes = b'{"status": "done"}',
    event_time: datetime | None = None,
) -> SimpleNamespace:
    """Create a WorkflowExecutionCompleted event (type=2)."""
    return make_event(
        event_type=2,
        event_id=100,
        event_time=event_time or _T0 + timedelta(seconds=30),
        workflow_execution_completed_event_attributes=SimpleNamespace(
            result=SimpleNamespace(payloads=[make_payload(result_data)]),
        ),
    )


def make_workflow_failed_event(
    message: str = "Something went wrong",
    event_time: datetime | None = None,
) -> SimpleNamespace:
    """Create a WorkflowExecutionFailed event (type=3)."""
    return make_event(
        event_type=3,
        event_id=100,
        event_time=event_time or _T0 + timedelta(seconds=30),
        workflow_execution_failed_event_attributes=SimpleNamespace(
            failure=SimpleNamespace(
                message=message,
                type="ApplicationError",
                stack_trace="at line 42",
                source=None,
                cause=None,
            ),
        ),
    )


def make_activity_scheduled_event(
    activity_id: str,
    activity_type: str = "ProcessPayment",
    event_id: int = 10,
    event_time: datetime | None = None,
    input_data: bytes = b'{"amount": 100}',
) -> SimpleNamespace:
    return make_event(
        event_type=10,
        event_id=event_id,
        event_time=event_time or _T0 + timedelta(seconds=1),
        activity_task_scheduled_event_attributes=SimpleNamespace(
            activity_id=activity_id,
            activity_type=SimpleNamespace(name=activity_type),
            input=SimpleNamespace(payloads=[make_payload(input_data)]),
        ),
    )


def make_activity_started_event(
    scheduled_event_id: int = 10,
    event_id: int = 11,
    event_time: datetime | None = None,
    attempt: int = 1,
) -> SimpleNamespace:
    return make_event(
        event_type=11,
        event_id=event_id,
        event_time=event_time or _T0 + timedelta(seconds=2),
        activity_task_started_event_attributes=SimpleNamespace(
            scheduled_event_id=scheduled_event_id,
            attempt=attempt,
        ),
    )


def make_activity_completed_event(
    scheduled_event_id: int = 10,
    event_id: int = 12,
    event_time: datetime | None = None,
    result_data: bytes = b'{"success": true}',
) -> SimpleNamespace:
    return make_event(
        event_type=12,
        event_id=event_id,
        event_time=event_time or _T0 + timedelta(seconds=5),
        activity_task_completed_event_attributes=SimpleNamespace(
            scheduled_event_id=scheduled_event_id,
            result=SimpleNamespace(payloads=[make_payload(result_data)]),
        ),
    )


def make_activity_failed_event(
    scheduled_event_id: int = 10,
    event_id: int = 12,
    event_time: datetime | None = None,
    message: str = "Activity failed",
) -> SimpleNamespace:
    return make_event(
        event_type=13,
        event_id=event_id,
        event_time=event_time or _T0 + timedelta(seconds=5),
        activity_task_failed_event_attributes=SimpleNamespace(
            scheduled_event_id=scheduled_event_id,
            failure=SimpleNamespace(message=message),
        ),
    )


def make_signal_event(
    signal_name: str = "approve",
    event_time: datetime | None = None,
    input_data: bytes = b'{"approved": true}',
) -> SimpleNamespace:
    return make_event(
        event_type=26,
        event_id=50,
        event_time=event_time or _T0 + timedelta(seconds=10),
        workflow_execution_signaled_event_attributes=SimpleNamespace(
            signal_name=signal_name,
            input=SimpleNamespace(payloads=[make_payload(input_data)]),
        ),
    )


def make_timer_started_event(
    timer_id: str = "timer-1",
    event_id: int = 60,
    event_time: datetime | None = None,
    duration_seconds: int = 300,
) -> SimpleNamespace:
    return make_event(
        event_type=17,
        event_id=event_id,
        event_time=event_time or _T0 + timedelta(seconds=15),
        timer_started_event_attributes=SimpleNamespace(
            timer_id=timer_id,
            start_to_fire_timeout=SimpleNamespace(seconds=duration_seconds),
        ),
    )


def make_timer_fired_event(
    timer_id: str = "timer-1",
    event_id: int = 61,
    event_time: datetime | None = None,
) -> SimpleNamespace:
    return make_event(
        event_type=18,
        event_id=event_id,
        event_time=event_time or _T0 + timedelta(seconds=315),
        timer_fired_event_attributes=SimpleNamespace(timer_id=timer_id),
    )


def make_child_initiated_event(
    workflow_id: str = "child-wf-1",
    workflow_type: str = "ChildWorkflow",
    event_id: int = 70,
) -> SimpleNamespace:
    return make_event(
        event_type=29,
        event_id=event_id,
        start_child_workflow_execution_initiated_event_attributes=SimpleNamespace(
            workflow_id=workflow_id,
            workflow_type=SimpleNamespace(name=workflow_type),
        ),
    )


def make_child_completed_event(
    workflow_id: str = "child-wf-1",
    event_id: int = 72,
) -> SimpleNamespace:
    return make_event(
        event_type=32,
        event_id=event_id,
        child_workflow_execution_completed_event_attributes=SimpleNamespace(
            workflow_execution=SimpleNamespace(workflow_id=workflow_id, run_id="child-run-1"),
        ),
    )


def make_workflow_task_event(event_type: int, event_id: int = 5) -> SimpleNamespace:
    """Create a workflow task event (5=Scheduled, 6=Started, 7=Completed)."""
    return make_event(event_type=event_type, event_id=event_id)


# --- Complete Workflow Event Histories ---


def make_simple_completed_history() -> list[SimpleNamespace]:
    """A simple workflow: start -> 1 activity -> complete."""
    return [
        make_workflow_started_event(),
        make_workflow_task_event(5, event_id=2),
        make_workflow_task_event(6, event_id=3),
        make_workflow_task_event(7, event_id=4),
        make_activity_scheduled_event("1", "ProcessPayment", event_id=10),
        make_activity_started_event(scheduled_event_id=10, event_id=11),
        make_activity_completed_event(scheduled_event_id=10, event_id=12),
        make_workflow_completed_event(),
    ]


def make_failed_workflow_history() -> list[SimpleNamespace]:
    """A workflow that fails after an activity failure."""
    return [
        make_workflow_started_event(),
        make_workflow_task_event(5, event_id=2),
        make_workflow_task_event(7, event_id=4),
        make_activity_scheduled_event("1", "ValidateOrder", event_id=10),
        make_activity_started_event(scheduled_event_id=10, event_id=11),
        make_activity_failed_event(scheduled_event_id=10, event_id=12, message="Validation error"),
        make_workflow_failed_event(message="Workflow failed due to activity failure"),
    ]


def make_multi_activity_history() -> list[SimpleNamespace]:
    """A workflow with two activities."""
    return [
        make_workflow_started_event(),
        make_workflow_task_event(5, event_id=2),
        make_workflow_task_event(7, event_id=4),
        make_activity_scheduled_event("1", "ValidateOrder", event_id=10,
                                       input_data=b'{"orderId": "A"}'),
        make_activity_started_event(scheduled_event_id=10, event_id=11),
        make_activity_completed_event(scheduled_event_id=10, event_id=12,
                                       result_data=b'{"valid": true}'),
        make_activity_scheduled_event("2", "ChargePayment", event_id=20,
                                       input_data=b'{"amount": 50}'),
        make_activity_started_event(scheduled_event_id=20, event_id=21),
        make_activity_completed_event(scheduled_event_id=20, event_id=22,
                                       result_data=b'{"charged": true}'),
        make_workflow_completed_event(),
    ]


# --- Mock Temporal Client ---


def make_mock_workflow_info(
    workflow_id: str = "wf-1",
    run_id: str = "run-1",
    workflow_type: str = "OrderWorkflow",
    status_name: str = "COMPLETED",
    start_time: datetime | None = None,
    close_time: datetime | None = None,
) -> SimpleNamespace:
    """Create a mock workflow listing entry."""
    st = start_time or _T0
    ct = close_time or (st + timedelta(minutes=2))
    return SimpleNamespace(
        id=workflow_id,
        run_id=run_id,
        workflow_type=workflow_type,
        status=SimpleNamespace(name=status_name),
        start_time=st,
        close_time=ct,
        task_queue="default-queue",
        search_attributes={"CustomField": ["value1"]},
    )


class MockAsyncIterator:
    """Async iterator for mocking client.list_workflows()."""

    def __init__(self, items: list):
        self._items = items
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


def make_mock_client(
    workflows: list | None = None,
    events: list | None = None,
    run_id: str = "run-abc",
    status_name: str = "COMPLETED",
    start_time: datetime | None = None,
) -> MagicMock:
    """Create a fully mocked Temporal Client with common behaviors."""
    client = MagicMock()
    client.namespace = "default"

    # list_workflows
    wf_list = workflows or [make_mock_workflow_info()]
    client.list_workflows = MagicMock(return_value=MockAsyncIterator(wf_list))

    # get_workflow_handle -> handle with fetch_history, describe, query
    handle = AsyncMock()
    history_events = events if events is not None else make_simple_completed_history()
    handle.fetch_history = AsyncMock(return_value=SimpleNamespace(events=history_events))
    handle.describe = AsyncMock(return_value=SimpleNamespace(
        run_id=run_id,
        status=SimpleNamespace(name=status_name),
        start_time=start_time or _T0,
        raw=None,
        raw_description=None,
    ))
    handle.query = AsyncMock(return_value="goroutine 1:\n  main.go:42")
    client.get_workflow_handle = MagicMock(return_value=handle)

    # workflow_service for describe_task_queue
    client.workflow_service = AsyncMock()

    return client
