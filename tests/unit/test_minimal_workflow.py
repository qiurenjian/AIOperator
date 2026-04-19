"""Minimal smoke test: a no-activity workflow that just sets state and returns."""
from __future__ import annotations

import pytest
from temporalio import workflow
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


@workflow.defn(name="HelloWorkflow")
class HelloWorkflow:
    @workflow.run
    async def run(self, name: str) -> dict:
        return {"hello": name}


@pytest.mark.asyncio
async def test_hello() -> None:
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter,
    ) as env:
        client: Client = env.client
        async with Worker(client, task_queue="t", workflows=[HelloWorkflow], activities=[]):
            r = await client.execute_workflow(
                HelloWorkflow.run, "world", id="hello-1", task_queue="t"
            )
            assert r["hello"] == "world"
