import type { TimelineStep, ExecutionDivergence, WorkflowHistory } from "../types.js";

/**
 * Compare two workflow execution histories and identify divergences.
 */
export function diffExecutions(
  historyA: WorkflowHistory,
  historyB: WorkflowHistory
): {
  divergences: ExecutionDivergence[];
  structural_differences: {
    activities_only_in_a: string[];
    activities_only_in_b: string[];
    different_execution_order: boolean;
  };
  signals: {
    signals_only_in_a: string[];
    signals_only_in_b: string[];
  };
} {
  const divergences = findDataDivergences(historyA.timeline, historyB.timeline);
  const structural = findStructuralDifferences(historyA.timeline, historyB.timeline);
  const signals = findSignalDifferences(historyA, historyB);

  return { divergences, structural_differences: structural, signals };
}

/**
 * Find data divergences: same activity at same step, different inputs/outputs.
 */
function findDataDivergences(
  timelineA: TimelineStep[],
  timelineB: TimelineStep[]
): ExecutionDivergence[] {
  const divergences: ExecutionDivergence[] = [];

  // Align activities by matching type and sequence
  const aligned = alignTimelines(timelineA, timelineB);

  for (const pair of aligned) {
    if (!pair.a || !pair.b) continue;

    // Compare inputs
    const inputA = pair.a.input ?? pair.a.input_summary;
    const inputB = pair.b.input ?? pair.b.input_summary;
    const inputDiffs = deepDiff(inputA, inputB, `input`);

    for (const diff of inputDiffs) {
      divergences.push({
        step: pair.a.step,
        activity: pair.a.activity,
        field: diff.path,
        value_a: diff.valueA,
        value_b: diff.valueB,
        note: diff.note,
      });
    }

    // Compare outputs
    const outputA = pair.a.output ?? pair.a.output_summary;
    const outputB = pair.b.output ?? pair.b.output_summary;
    const outputDiffs = deepDiff(outputA, outputB, `output`);

    for (const diff of outputDiffs) {
      divergences.push({
        step: pair.a.step,
        activity: pair.a.activity,
        field: diff.path,
        value_a: diff.valueA,
        value_b: diff.valueB,
        note: diff.note,
      });
    }

    // Compare status
    if (pair.a.status !== pair.b.status) {
      divergences.push({
        step: pair.a.step,
        activity: pair.a.activity,
        field: "status",
        value_a: pair.a.status,
        value_b: pair.b.status,
        note: `Activity ${pair.a.activity} has different status in each execution`,
      });
    }

    // Compare retries
    if ((pair.a.retries || 0) !== (pair.b.retries || 0)) {
      divergences.push({
        step: pair.a.step,
        activity: pair.a.activity,
        field: "retries",
        value_a: pair.a.retries || 0,
        value_b: pair.b.retries || 0,
        note: `Different retry counts for ${pair.a.activity}`,
      });
    }
  }

  return divergences;
}

/**
 * Find structural differences: activities that exist in one execution but not the other.
 */
function findStructuralDifferences(
  timelineA: TimelineStep[],
  timelineB: TimelineStep[]
): {
  activities_only_in_a: string[];
  activities_only_in_b: string[];
  different_execution_order: boolean;
} {
  const typesA = timelineA.map((s) => s.activity);
  const typesB = timelineB.map((s) => s.activity);

  const setA = new Set(typesA);
  const setB = new Set(typesB);

  const onlyInA = typesA.filter((t) => !setB.has(t));
  const onlyInB = typesB.filter((t) => !setA.has(t));

  // Check if activities common to both were executed in the same order
  const commonA = typesA.filter((t) => setB.has(t));
  const commonB = typesB.filter((t) => setA.has(t));
  const differentOrder =
    commonA.length > 0 &&
    commonB.length > 0 &&
    JSON.stringify(commonA) !== JSON.stringify(commonB);

  return {
    activities_only_in_a: [...new Set(onlyInA)],
    activities_only_in_b: [...new Set(onlyInB)],
    different_execution_order: differentOrder,
  };
}

/**
 * Find signal differences between two executions.
 */
function findSignalDifferences(
  historyA: WorkflowHistory,
  historyB: WorkflowHistory
): {
  signals_only_in_a: string[];
  signals_only_in_b: string[];
} {
  const sigNamesA = new Set(historyA.signals_received.map((s) => s.name));
  const sigNamesB = new Set(historyB.signals_received.map((s) => s.name));

  return {
    signals_only_in_a: [...sigNamesA].filter((s) => !sigNamesB.has(s)),
    signals_only_in_b: [...sigNamesB].filter((s) => !sigNamesA.has(s)),
  };
}

// --- Alignment and Diff Utilities ---

interface AlignedPair {
  a: TimelineStep | null;
  b: TimelineStep | null;
}

/**
 * Align two timelines by activity type and sequence.
 * Uses a simple greedy matching: for each step in A, find the first unmatched
 * step in B with the same activity type.
 */
function alignTimelines(
  timelineA: TimelineStep[],
  timelineB: TimelineStep[]
): AlignedPair[] {
  const pairs: AlignedPair[] = [];
  const usedB = new Set<number>();

  for (const stepA of timelineA) {
    let matched = false;
    for (let i = 0; i < timelineB.length; i++) {
      if (usedB.has(i)) continue;
      if (timelineB[i].activity === stepA.activity) {
        pairs.push({ a: stepA, b: timelineB[i] });
        usedB.add(i);
        matched = true;
        break;
      }
    }
    if (!matched) {
      pairs.push({ a: stepA, b: null });
    }
  }

  // Add unmatched B steps
  for (let i = 0; i < timelineB.length; i++) {
    if (!usedB.has(i)) {
      pairs.push({ a: null, b: timelineB[i] });
    }
  }

  return pairs;
}

interface DiffResult {
  path: string;
  valueA: unknown;
  valueB: unknown;
  note: string;
}

/**
 * Deep diff two values and return a list of field-level differences.
 */
function deepDiff(a: unknown, b: unknown, basePath: string): DiffResult[] {
  if (a === b) return [];
  if (a === undefined && b === undefined) return [];
  if (a === null && b === null) return [];

  // If both are strings (summaries), compare directly
  if (typeof a === "string" && typeof b === "string") {
    if (a !== b) {
      return [
        {
          path: basePath,
          valueA: a,
          valueB: b,
          note: `Different values at ${basePath}`,
        },
      ];
    }
    return [];
  }

  // If both are objects, compare field by field
  if (
    a !== null &&
    b !== null &&
    typeof a === "object" &&
    typeof b === "object" &&
    !Array.isArray(a) &&
    !Array.isArray(b)
  ) {
    const results: DiffResult[] = [];
    const allKeys = new Set([
      ...Object.keys(a as Record<string, unknown>),
      ...Object.keys(b as Record<string, unknown>),
    ]);

    for (const key of allKeys) {
      const valA = (a as Record<string, unknown>)[key];
      const valB = (b as Record<string, unknown>)[key];
      const childPath = `${basePath}.${key}`;
      results.push(...deepDiff(valA, valB, childPath));
    }

    return results;
  }

  // If both are arrays, compare element by element
  if (Array.isArray(a) && Array.isArray(b)) {
    const results: DiffResult[] = [];
    const maxLen = Math.max(a.length, b.length);

    for (let i = 0; i < maxLen; i++) {
      results.push(...deepDiff(a[i], b[i], `${basePath}[${i}]`));
    }

    return results;
  }

  // Different types or primitive values
  if (a !== b) {
    return [
      {
        path: basePath,
        valueA: a,
        valueB: b,
        note: `Different values at ${basePath}`,
      },
    ];
  }

  return [];
}
