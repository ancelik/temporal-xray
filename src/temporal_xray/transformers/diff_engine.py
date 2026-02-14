from __future__ import annotations

import json
from typing import Any

from ..types import ExecutionDivergence, TimelineStep, WorkflowHistory


def diff_executions(
    history_a: WorkflowHistory,
    history_b: WorkflowHistory,
) -> dict[str, Any]:
    """Compare two workflow execution histories and identify divergences."""
    divergences = _find_data_divergences(history_a.timeline, history_b.timeline)
    structural = _find_structural_differences(history_a.timeline, history_b.timeline)
    signals = _find_signal_differences(history_a, history_b)
    return {
        "divergences": divergences,
        "structural_differences": structural,
        "signals": signals,
    }


def _find_data_divergences(
    timeline_a: list[TimelineStep],
    timeline_b: list[TimelineStep],
) -> list[ExecutionDivergence]:
    divergences: list[ExecutionDivergence] = []
    aligned = _align_timelines(timeline_a, timeline_b)

    for pair_a, pair_b in aligned:
        if pair_a is None or pair_b is None:
            continue

        input_a = pair_a.input if pair_a.input is not None else pair_a.input_summary
        input_b = pair_b.input if pair_b.input is not None else pair_b.input_summary
        for diff in _deep_diff(input_a, input_b, "input"):
            divergences.append(ExecutionDivergence(
                step=pair_a.step,
                activity=pair_a.activity,
                field=diff["path"],
                value_a=diff["value_a"],
                value_b=diff["value_b"],
                note=diff["note"],
            ))

        output_a = pair_a.output if pair_a.output is not None else pair_a.output_summary
        output_b = pair_b.output if pair_b.output is not None else pair_b.output_summary
        for diff in _deep_diff(output_a, output_b, "output"):
            divergences.append(ExecutionDivergence(
                step=pair_a.step,
                activity=pair_a.activity,
                field=diff["path"],
                value_a=diff["value_a"],
                value_b=diff["value_b"],
                note=diff["note"],
            ))

        if pair_a.status != pair_b.status:
            divergences.append(ExecutionDivergence(
                step=pair_a.step,
                activity=pair_a.activity,
                field="status",
                value_a=pair_a.status,
                value_b=pair_b.status,
                note=f"Activity {pair_a.activity} has different status in each execution",
            ))

        if (pair_a.retries or 0) != (pair_b.retries or 0):
            divergences.append(ExecutionDivergence(
                step=pair_a.step,
                activity=pair_a.activity,
                field="retries",
                value_a=pair_a.retries or 0,
                value_b=pair_b.retries or 0,
                note=f"Different retry counts for {pair_a.activity}",
            ))

    return divergences


def _find_structural_differences(
    timeline_a: list[TimelineStep],
    timeline_b: list[TimelineStep],
) -> dict[str, Any]:
    types_a = [s.activity for s in timeline_a]
    types_b = [s.activity for s in timeline_b]

    set_a = set(types_a)
    set_b = set(types_b)

    only_in_a = list({t for t in types_a if t not in set_b})
    only_in_b = list({t for t in types_b if t not in set_a})

    common_a = [t for t in types_a if t in set_b]
    common_b = [t for t in types_b if t in set_a]
    different_order = (
        len(common_a) > 0
        and len(common_b) > 0
        and common_a != common_b
    )

    return {
        "activities_only_in_a": only_in_a,
        "activities_only_in_b": only_in_b,
        "different_execution_order": different_order,
    }


def _find_signal_differences(
    history_a: WorkflowHistory,
    history_b: WorkflowHistory,
) -> dict[str, list[str]]:
    sig_names_a = {s["name"] for s in history_a.signals_received}
    sig_names_b = {s["name"] for s in history_b.signals_received}
    return {
        "signals_only_in_a": [s for s in sig_names_a if s not in sig_names_b],
        "signals_only_in_b": [s for s in sig_names_b if s not in sig_names_a],
    }


def _align_timelines(
    timeline_a: list[TimelineStep],
    timeline_b: list[TimelineStep],
) -> list[tuple[TimelineStep | None, TimelineStep | None]]:
    pairs: list[tuple[TimelineStep | None, TimelineStep | None]] = []
    used_b: set[int] = set()

    for step_a in timeline_a:
        matched = False
        for i, step_b in enumerate(timeline_b):
            if i in used_b:
                continue
            if step_b.activity == step_a.activity:
                pairs.append((step_a, step_b))
                used_b.add(i)
                matched = True
                break
        if not matched:
            pairs.append((step_a, None))

    for i, step_b in enumerate(timeline_b):
        if i not in used_b:
            pairs.append((None, step_b))

    return pairs


def _deep_diff(a: Any, b: Any, base_path: str) -> list[dict[str, Any]]:
    if a is b or a == b:
        return []

    if (
        isinstance(a, dict)
        and isinstance(b, dict)
    ):
        results: list[dict[str, Any]] = []
        all_keys = set(a.keys()) | set(b.keys())
        for key in all_keys:
            results.extend(_deep_diff(a.get(key), b.get(key), f"{base_path}.{key}"))
        return results

    if isinstance(a, list) and isinstance(b, list):
        results = []
        max_len = max(len(a), len(b))
        for i in range(max_len):
            val_a = a[i] if i < len(a) else None
            val_b = b[i] if i < len(b) else None
            results.extend(_deep_diff(val_a, val_b, f"{base_path}[{i}]"))
        return results

    return [{
        "path": base_path,
        "value_a": a,
        "value_b": b,
        "note": f"Different values at {base_path}",
    }]
