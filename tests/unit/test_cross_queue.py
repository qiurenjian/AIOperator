from __future__ import annotations

from datetime import timedelta

import pytest
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


@activity.defn(name="ping")
async def ping(name: str) -> str:
    return f"pong:{name}"


@workflow.defn(name="CrossQueueWorkflow")
class CrossQueueWorkflow:
    @workflow.run
    async def run(self, name: str) -> str:
        return await workflow.execute_activity(
            ping, name, task_queue="other-q",
            start_to_close_timeout=timedelta(seconds=5),
        )


@pytest.mark.asyncio
async def test_cross_queue() -> None:
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter,
    ) as env:
        client: Client = env.client
        async with (
            Worker(client, task_queue="main", workflows=[CrossQueueWorkflow], activities=[]),
            Worker(client, task_queue="other-q", activities=[ping]),
        ):
            r = await client.execute_workflow(
                CrossQueueWorkflow.run, "x", id="cq-1", task_queue="main"
            )
            assert r == "pong:x"
