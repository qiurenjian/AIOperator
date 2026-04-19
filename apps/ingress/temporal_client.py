from __future__ import annotations

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from aiop.settings import get_settings


_client: Client | None = None


async def get_temporal_client() -> Client:
    global _client
    if _client is None:
        s = get_settings()
        _client = await Client.connect(
            s.temporal_host,
            namespace=s.temporal_namespace,
            data_converter=pydantic_data_converter,
        )
    return _client
