import { getTemporalClient } from "../temporal-client.js";
import type { DescribeTaskQueueInput, TaskQueueInfo, Long } from "../types.js";

export async function describeTaskQueue(
  input: DescribeTaskQueueInput
): Promise<TaskQueueInfo> {
  const client = await getTemporalClient(input.namespace);

  try {
    const taskQueueType =
      input.task_queue_type === "activity" ? 2 : 1; // WORKFLOW = 1, ACTIVITY = 2

    // Use the raw gRPC workflowService since TaskQueueClient doesn't expose describeTaskQueue
    const response = await client.workflow.workflowService.describeTaskQueue({
      namespace: client.options.namespace,
      taskQueue: {
        name: input.task_queue,
        kind: 1, // NORMAL
      },
      taskQueueType,
    });

    const pollers = (response.pollers || []).map(
      (poller: {
        identity?: string | null;
        lastAccessTime?: { seconds?: number | Long | null; nanos?: number | null } | null;
        ratePerSecond?: number | null;
        workerVersionCapabilities?: { buildId?: string | null } | null;
      }) => {
        const lastAccessTime = poller.lastAccessTime
          ? new Date(
              Number(poller.lastAccessTime.seconds || 0) * 1000
            ).toISOString()
          : "";
        const identity = poller.identity || "unknown";
        const ratePerSecond = poller.ratePerSecond || 0;
        const workerVersion =
          poller.workerVersionCapabilities?.buildId || null;

        return {
          identity,
          last_access_time: lastAccessTime,
          rate_per_second: ratePerSecond,
          worker_version: workerVersion,
        };
      }
    );

    // Collect unique versions
    const versions = new Set<string>();
    for (const p of pollers) {
      if (p.worker_version) {
        versions.add(p.worker_version);
      }
    }

    return {
      task_queue: input.task_queue,
      pollers,
      backlog_count: 0, // Backlog count requires enhanced visibility
      versions_active: [...versions],
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);

    if (message.includes("UNAVAILABLE") || message.includes("connect")) {
      throw new Error(
        `Cannot connect to Temporal server. Verify TEMPORAL_ADDRESS is correct. Details: ${message}`
      );
    }

    throw new Error(`Failed to describe task queue: ${message}`);
  }
}
