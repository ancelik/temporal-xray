"""Tests for temporal_xray.transformers — event processing, summarization, diffing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from temporal_xray.transformers import (
    EVENT_TYPE_MAP,
    INTERNAL_EVENT_TYPES,
    _attr,
    _deep_diff,
    _event_type,
    _extract_failure,
    _find,
    _group_activities,
    _summarize,
    diff_executions,
    summarize_history,
)
from conftest import (
    _T0,
    make_activity_completed_event,
    make_activity_failed_event,
    make_activity_scheduled_event,
    make_activity_started_event,
    make_child_completed_event,
    make_child_initiated_event,
    make_failed_workflow_history,
    make_multi_activity_history,
    make_signal_event,
    make_simple_completed_history,
    make_timer_fired_event,
    make_timer_started_event,
    make_workflow_completed_event,
    make_workflow_started_event,
    make_workflow_task_event,
)


# ── _event_type ─────────────────────────────────────────────────


class TestEventType:
    def test_known_type(self):
        from types import SimpleNamespace
        ev = SimpleNamespace(event_type=1)
        assert _event_type(ev) == "WorkflowExecutionStarted"

    def test_activity_scheduled(self):
        from types import SimpleNamespace
        ev = SimpleNamespace(event_type=10)
        assert _event_type(ev) == "ActivityTaskScheduled"

    def test_unknown_type(self):
        from types import SimpleNamespace
        ev = SimpleNamespace(event_type=999)
        assert "UnknownEventType" in _event_type(ev)

    def test_no_event_type(self):
        from types import SimpleNamespace
        ev = SimpleNamespace()
        assert _event_type(ev) == "Unknown"

    def test_all_map_entries_are_strings(self):
        for k, v in EVENT_TYPE_MAP.items():
            assert isinstance(k, int)
            assert isinstance(v, str)


# ── _find ───────────────────────────────────────────────────────


class TestFind:
    def test_finds_existing(self):
        events = make_simple_completed_history()
        result = _find(events, "WorkflowExecutionStarted")
        assert result is not None
        assert result.event_type == 1

    def test_returns_none_for_missing(self):
        events = make_simple_completed_history()
        assert _find(events, "WorkflowExecutionCanceled") is None


# ── _attr ───────────────────────────────────────────────────────


class TestAttr:
    def test_single_level(self):
        from types import SimpleNamespace
        obj = SimpleNamespace(name="test")
        assert _attr(obj, "name") == "test"

    def test_multi_level(self):
        from types import SimpleNamespace
        obj = SimpleNamespace(a=SimpleNamespace(b=SimpleNamespace(c=42)))
        assert _attr(obj, "a", "b", "c") == 42

    def test_none_input(self):
        assert _attr(None, "anything") is None

    def test_missing_intermediate(self):
        from types import SimpleNamespace
        obj = SimpleNamespace(a=None)
        assert _attr(obj, "a", "b", "c") is None

    def test_missing_attribute(self):
        from types import SimpleNamespace
        obj = SimpleNamespace(x=1)
        assert _attr(obj, "y") is None


# ── _summarize ──────────────────────────────────────────────────


class TestSummarize:
    def test_none(self):
        assert _summarize(None) == "null"

    def test_short_value(self):
        assert _summarize({"key": "val"}) == '{"key": "val"}'

    def test_long_value_truncated(self):
        result = _summarize({"data": "x" * 300})
        assert len(result) <= 200
        assert result.endswith("...")


# ── _extract_failure ────────────────────────────────────────────


class TestExtractFailure:
    def test_none(self):
        assert _extract_failure(None) is None

    def test_basic_failure(self):
        from types import SimpleNamespace
        f = SimpleNamespace(
            message="connection reset",
            type="TransportError",
            stack_trace="at line 10",
            cause=None,
        )
        result = _extract_failure(f)
        assert result["message"] == "connection reset"
        assert result["type"] == "TransportError"
        assert result["stackTrace"] == "at line 10"
        assert result["cause"] is None

    def test_nested_cause(self):
        from types import SimpleNamespace
        inner = SimpleNamespace(message="root cause", type="IOError", stack_trace=None, cause=None)
        outer = SimpleNamespace(message="wrapper", type="AppError", stack_trace=None, cause=inner)
        result = _extract_failure(outer)
        assert result["cause"]["message"] == "root cause"

    def test_missing_attrs_fallback(self):
        from types import SimpleNamespace
        f = SimpleNamespace()
        result = _extract_failure(f)
        assert result["message"] == "Unknown error"
        assert result["type"] == "unknown"


# ── _group_activities ───────────────────────────────────────────


class TestGroupActivities:
    def test_single_activity_lifecycle(self):
        events = [
            make_activity_scheduled_event("1", "DoWork", event_id=10),
            make_activity_started_event(scheduled_event_id=10, event_id=11),
            make_activity_completed_event(scheduled_event_id=10, event_id=12),
        ]
        groups = _group_activities(events)
        assert len(groups) == 1
        assert groups[0]["activity_type"] == "DoWork"
        assert groups[0]["activity_id"] == "1"
        assert "scheduled" in groups[0]
        assert "started" in groups[0]
        assert "completed" in groups[0]

    def test_multiple_activities(self):
        events = [
            make_activity_scheduled_event("1", "Step1", event_id=10),
            make_activity_started_event(scheduled_event_id=10, event_id=11),
            make_activity_completed_event(scheduled_event_id=10, event_id=12),
            make_activity_scheduled_event("2", "Step2", event_id=20),
            make_activity_started_event(scheduled_event_id=20, event_id=21),
            make_activity_completed_event(scheduled_event_id=20, event_id=22),
        ]
        groups = _group_activities(events)
        assert len(groups) == 2
        types = [g["activity_type"] for g in groups]
        assert "Step1" in types
        assert "Step2" in types

    def test_failed_activity(self):
        events = [
            make_activity_scheduled_event("1", "Risky", event_id=10),
            make_activity_started_event(scheduled_event_id=10, event_id=11),
            make_activity_failed_event(scheduled_event_id=10, event_id=12),
        ]
        groups = _group_activities(events)
        assert len(groups) == 1
        assert "failed" in groups[0]
        assert "completed" not in groups[0]

    def test_non_activity_events_ignored(self):
        events = [
            make_workflow_started_event(),
            make_workflow_task_event(5),
            make_workflow_task_event(7),
            make_signal_event(),
        ]
        groups = _group_activities(events)
        assert len(groups) == 0


# ── summarize_history ───────────────────────────────────────────


class TestSummarizeHistory:
    def test_completed_workflow_summary(self):
        events = make_simple_completed_history()
        result = summarize_history("wf-1", "run-1", events, detail_level="summary")

        assert result["workflow_id"] == "wf-1"
        assert result["run_id"] == "run-1"
        assert result["workflow_type"] == "OrderWorkflow"
        assert result["status"] == "COMPLETED"
        assert result["start_time"] != ""
        assert result["close_time"] is not None
        assert result["input"] == {"orderId": "123"}
        assert result["result"] == {"status": "done"}
        assert len(result["timeline"]) == 1
        assert result["timeline"][0]["activity"] == "ProcessPayment"
        assert result["timeline"][0]["status"] == "completed"
        assert result["failure"] is None

    def test_failed_workflow_summary(self):
        events = make_failed_workflow_history()
        result = summarize_history("wf-2", "run-2", events, detail_level="summary")

        assert result["status"] == "FAILED"
        assert result["failure"] is not None
        assert "activity failure" in result["failure"]["message"]
        assert len(result["timeline"]) == 1
        assert result["timeline"][0]["status"] == "failed"
        assert "Validation error" in result["timeline"][0]["failure"]

    def test_multi_activity_timeline(self):
        events = make_multi_activity_history()
        result = summarize_history("wf-3", "run-3", events, detail_level="standard")

        assert len(result["timeline"]) == 2
        assert result["timeline"][0]["step"] == 1
        assert result["timeline"][1]["step"] == 2
        assert result["timeline"][0]["activity"] == "ValidateOrder"
        assert result["timeline"][1]["activity"] == "ChargePayment"
        # standard detail level includes full input/output, not summaries
        assert "input" in result["timeline"][0]
        assert "input_summary" not in result["timeline"][0]

    def test_summary_has_summaries(self):
        events = make_multi_activity_history()
        result = summarize_history("wf-3", "run-3", events, detail_level="summary")

        assert "input_summary" in result["timeline"][0]
        assert "output_summary" in result["timeline"][0]
        assert "input" not in result["timeline"][0]

    def test_full_detail_returns_all_events(self):
        events = make_simple_completed_history()
        result = summarize_history("wf-1", "run-1", events, detail_level="full")

        assert result["status"] == "FULL_HISTORY"
        assert "warning" in result
        # full mode filters internal events (WorkflowTask*)
        for step in result["timeline"]:
            assert "WorkflowTask" not in step["activity"]

    def test_event_type_filter(self):
        events = make_simple_completed_history()
        result = summarize_history(
            "wf-1", "run-1", events,
            detail_level="summary",
            event_types=["ActivityTaskScheduled"],
        )
        # Filter only affects which events are processed for timeline
        # The start/complete events are still found in unfiltered events
        assert result["workflow_type"] == "OrderWorkflow"

    def test_running_workflow(self):
        events = [make_workflow_started_event()]
        result = summarize_history("wf-run", "run-x", events, detail_level="summary")

        assert result["status"] == "RUNNING"
        assert result["close_time"] is None
        assert result["result"] is None
        assert result["failure"] is None

    def test_signals_extracted(self):
        events = [
            make_workflow_started_event(),
            make_signal_event("payment_confirmed"),
            make_signal_event("user_approved"),
        ]
        result = summarize_history("wf-s", "run-s", events)

        assert len(result["signals_received"]) == 2
        names = {s["name"] for s in result["signals_received"]}
        assert names == {"payment_confirmed", "user_approved"}

    def test_timers_extracted(self):
        events = [
            make_workflow_started_event(),
            make_timer_started_event("t1", event_id=60, duration_seconds=300),
            make_timer_fired_event("t1", event_id=61),
        ]
        result = summarize_history("wf-t", "run-t", events)

        assert len(result["timers_fired"]) == 1
        assert result["timers_fired"][0]["timer_id"] == "t1"
        assert result["timers_fired"][0]["duration"] == "5m"

    def test_child_workflows_extracted(self):
        events = [
            make_workflow_started_event(),
            make_child_initiated_event("child-1", "ChildWF"),
            make_child_completed_event("child-1"),
        ]
        result = summarize_history("wf-c", "run-c", events)

        assert len(result["child_workflows"]) == 1
        assert result["child_workflows"][0]["workflow_id"] == "child-1"
        assert result["child_workflows"][0]["status"] == "completed"

    def test_large_history_warning(self):
        events = [make_workflow_started_event()] + [
            make_workflow_task_event(5, event_id=i) for i in range(10001)
        ]
        result = summarize_history("wf-big", "run-big", events)
        assert "warning" in result

    def test_retries_shown(self):
        events = [
            make_workflow_started_event(),
            make_activity_scheduled_event("1", "Flaky", event_id=10),
            make_activity_started_event(scheduled_event_id=10, event_id=11, attempt=3),
            make_activity_completed_event(scheduled_event_id=10, event_id=12),
        ]
        result = summarize_history("wf-r", "run-r", events)
        assert result["timeline"][0]["retries"] == 2


# ── diff_executions ─────────────────────────────────────────────


class TestDiffExecutions:
    def _make_history(self, timeline, signals=None):
        return {
            "workflow_id": "wf",
            "workflow_type": "Test",
            "status": "COMPLETED",
            "timeline": timeline,
            "signals_received": signals or [],
        }

    def test_identical_histories(self):
        tl = [{"step": 1, "activity": "DoWork", "status": "completed",
               "input": {"x": 1}, "output": {"y": 2}}]
        result = diff_executions(self._make_history(tl), self._make_history(tl))

        assert result["divergences"] == []
        assert result["structural_differences"]["activities_only_in_a"] == []
        assert result["structural_differences"]["activities_only_in_b"] == []
        assert result["structural_differences"]["different_execution_order"] is False

    def test_data_divergence(self):
        tl_a = [{"step": 1, "activity": "Calc", "status": "completed",
                 "input": {"amount": 100}, "output": {"total": 100}}]
        tl_b = [{"step": 1, "activity": "Calc", "status": "completed",
                 "input": {"amount": 100}, "output": {"total": 200}}]
        result = diff_executions(self._make_history(tl_a), self._make_history(tl_b))

        assert len(result["divergences"]) >= 1
        output_divs = [d for d in result["divergences"] if "output" in d["field"]]
        assert len(output_divs) >= 1

    def test_status_divergence(self):
        tl_a = [{"step": 1, "activity": "Risky", "status": "completed"}]
        tl_b = [{"step": 1, "activity": "Risky", "status": "failed"}]
        result = diff_executions(self._make_history(tl_a), self._make_history(tl_b))

        status_divs = [d for d in result["divergences"] if d["field"] == "status"]
        assert len(status_divs) == 1
        assert status_divs[0]["value_a"] == "completed"
        assert status_divs[0]["value_b"] == "failed"

    def test_retry_divergence(self):
        tl_a = [{"step": 1, "activity": "Flaky", "status": "completed", "retries": 0}]
        tl_b = [{"step": 1, "activity": "Flaky", "status": "completed", "retries": 3}]
        result = diff_executions(self._make_history(tl_a), self._make_history(tl_b))

        retry_divs = [d for d in result["divergences"] if d["field"] == "retries"]
        assert len(retry_divs) == 1

    def test_structural_difference(self):
        tl_a = [{"step": 1, "activity": "A", "status": "completed"},
                {"step": 2, "activity": "B", "status": "completed"}]
        tl_b = [{"step": 1, "activity": "A", "status": "completed"},
                {"step": 2, "activity": "C", "status": "completed"}]
        result = diff_executions(self._make_history(tl_a), self._make_history(tl_b))

        sd = result["structural_differences"]
        assert "B" in sd["activities_only_in_a"]
        assert "C" in sd["activities_only_in_b"]

    def test_different_execution_order(self):
        tl_a = [{"step": 1, "activity": "A", "status": "completed"},
                {"step": 2, "activity": "B", "status": "completed"}]
        tl_b = [{"step": 1, "activity": "B", "status": "completed"},
                {"step": 2, "activity": "A", "status": "completed"}]
        result = diff_executions(self._make_history(tl_a), self._make_history(tl_b))

        assert result["structural_differences"]["different_execution_order"] is True

    def test_signal_differences(self):
        ha = self._make_history([], signals=[{"name": "approve"}, {"name": "notify"}])
        hb = self._make_history([], signals=[{"name": "approve"}, {"name": "cancel"}])
        result = diff_executions(ha, hb)

        assert "notify" in result["signals"]["signals_only_in_a"]
        assert "cancel" in result["signals"]["signals_only_in_b"]


# ── _deep_diff ──────────────────────────────────────────────────


class TestDeepDiff:
    def test_equal_values(self):
        assert _deep_diff(42, 42, "x") == []

    def test_scalar_difference(self):
        result = _deep_diff(1, 2, "value")
        assert len(result) == 1
        assert result[0]["value_a"] == 1
        assert result[0]["value_b"] == 2

    def test_dict_difference(self):
        a = {"x": 1, "y": 2}
        b = {"x": 1, "y": 3}
        result = _deep_diff(a, b, "root")
        assert len(result) == 1
        assert result[0]["field"] == "root.y"

    def test_nested_dict(self):
        a = {"outer": {"inner": 1}}
        b = {"outer": {"inner": 2}}
        result = _deep_diff(a, b, "root")
        assert len(result) == 1
        assert "inner" in result[0]["field"]

    def test_list_difference(self):
        result = _deep_diff([1, 2, 3], [1, 9, 3], "arr")
        assert len(result) == 1
        assert result[0]["field"] == "arr[1]"

    def test_list_length_mismatch(self):
        result = _deep_diff([1, 2], [1, 2, 3], "arr")
        assert len(result) == 1
        assert result[0]["field"] == "arr[2]"
        assert result[0]["value_a"] is None
        assert result[0]["value_b"] == 3

    def test_dict_missing_key(self):
        a = {"x": 1}
        b = {"x": 1, "y": 2}
        result = _deep_diff(a, b, "root")
        assert len(result) == 1
        assert result[0]["field"] == "root.y"

    def test_none_vs_value(self):
        result = _deep_diff(None, 42, "f")
        assert len(result) == 1
