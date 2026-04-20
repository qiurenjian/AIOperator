from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Awaitable, Callable

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from activities.claude.capture_requirement import claude_capture_requirement
from activities.claude.generate_prd import claude_generate_prd
from activities.feishu.send_card import feishu_send_card
from activities.git.commit import git_commit
from activities.websocket.notify import notify_websocket
from aiop.settings import get_settings
from workflows.requirement import RequirementWorkflow

log = logging.getLogger("worker")


# Map task queue → (workflows, activities) registered on it.
QUEUE_REGISTRY: dict[str, dict] = {
    "lite": {
        "workflows": [RequirementWorkflow],
        "activities": [feishu_send_card, notify_websocket],
    },
    "llm-cloud": {
        "workflows": [],
        "activities": [claude_capture_requirement, claude_generate_prd],
    },
    "git-ops": {
        "workflows": [],
        "activities": [git_commit],
    },
    "feishu-callback": {
        "workflows": [],
        "activities": [feishu_send_card],
    },
}


async def _run_worker(client: Client, queue: str, max_concurrent: int) -> None:
    spec = QUEUE_REGISTRY[queue]
    worker = Worker(
        client,
        task_queue=queue,
        workflows=spec["workflows"],
        activities=spec["activities"],
        max_concurrent_activities=max_concurrent,
    )
    log.info("worker started on queue=%s wf=%d act=%d", queue, len(spec["workflows"]), len(spec["activities"]))
    await worker.run()


async def amain() -> None:
    s = get_settings()
    logging.basicConfig(level=s.aiop_log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    queues = [q.strip() for q in s.worker_task_queues.split(",") if q.strip()]
    if not queues:
        log.error("no task queues configured (WORKER_TASK_QUEUES)")
        sys.exit(2)

    # Filter out queues with no registered workflows/activities
    valid_queues = [q for q in queues if q in QUEUE_REGISTRY]
    skipped = [q for q in queues if q not in QUEUE_REGISTRY]
    if skipped:
        log.warning("skipping queues with no registered workflows/activities: %s", skipped)
    if not valid_queues:
        log.error("no valid task queues after filtering")
        sys.exit(2)

    client = await Client.connect(
        s.temporal_host,
        namespace=s.temporal_namespace,
        data_converter=pydantic_data_converter,
    )
    log.info("connected to temporal at %s ns=%s, queues=%s", s.temporal_host, s.temporal_namespace, valid_queues)

    tasks = [asyncio.create_task(_run_worker(client, q, s.worker_max_concurrent_activities)) for q in valid_queues]

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    done_task = asyncio.create_task(stop.wait())
    await asyncio.wait([done_task, *tasks], return_when=asyncio.FIRST_COMPLETED)
    for t in tasks:
        t.cancel()
    log.info("worker shutting down")


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
