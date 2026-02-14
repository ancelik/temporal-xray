from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest

from ..temporal_client import get_temporal_client
from ..types import DescribeTaskQueueInput, TaskQueueInfo


async def describe_task_queue(input: DescribeTaskQueueInput) -> TaskQueueInfo:
    client = await get_temporal_client(input.namespace)

    try:
        tq_type = (
            TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY
            if input.task_queue_type == "activity"
            else TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW
        )

        response = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace=client.namespace,
                task_queue=TaskQueue(name=input.task_queue, kind=1),  # NORMAL = 1
                task_queue_type=tq_type,
            )
        )

        pollers = []
        for poller in response.pollers or []:
            last_access = ""
            if poller.last_access_time:
                if hasattr(poller.last_access_time, "isoformat"):
                    last_access = poller.last_access_time.isoformat()
                elif hasattr(poller.last_access_time, "ToDatetime"):
                    last_access = poller.last_access_time.ToDatetime().isoformat()
                elif hasattr(poller.last_access_time, "seconds"):
                    last_access = datetime.fromtimestamp(
                        int(poller.last_access_time.seconds or 0), tz=timezone.utc
                    ).isoformat()

            worker_version = None
            if hasattr(poller, "worker_version_capabilities") and poller.worker_version_capabilities:
                worker_version = poller.worker_version_capabilities.build_id or None

            pollers.append({
                "identity": poller.identity or "unknown",
                "last_access_time": last_access,
                "rate_per_second": poller.rate_per_second or 0,
                "worker_version": worker_version,
            })

        versions = list({p["worker_version"] for p in pollers if p["worker_version"]})

        return TaskQueueInfo(
            task_queue=input.task_queue,
            pollers=pollers,
            backlog_count=0,
            versions_active=versions,
        )
    except Exception as e:
        message = str(e)
        if "UNAVAILABLE" in message or "connect" in message:
            raise RuntimeError(
                f"Cannot connect to Temporal server. Verify TEMPORAL_ADDRESS is correct. Details: {message}"
            ) from e
        raise RuntimeError(f"Failed to describe task queue: {message}") from e
