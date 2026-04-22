"""数据库连接和会话管理"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
from asyncpg import Pool

from aiop.settings import get_settings

log = logging.getLogger(__name__)

_pool: Pool | None = None


async def init_db_pool() -> Pool:
    """初始化数据库连接池"""
    global _pool
    if _pool is None:
        settings = get_settings()
        # 从 database_url 解析连接参数
        # 格式: postgresql+asyncpg://user:password@host:port/database
        import re
        match = re.match(
            r'postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)',
            settings.database_url
        )
        if not match:
            raise ValueError(f"Invalid database_url format: {settings.database_url}")

        user, password, host, port, database = match.groups()

        _pool = await asyncpg.create_pool(
            host=host,
            port=int(port),
            user=user,
            password=password,
            database=database,
            min_size=2,
            max_size=10,
        )
        log.info("database pool initialized")
    return _pool


async def close_db_pool() -> None:
    """关闭数据库连接池"""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("database pool closed")


async def get_db_pool() -> Pool:
    """获取数据库连接池"""
    if _pool is None:
        return await init_db_pool()
    return _pool


@asynccontextmanager
async def get_db_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """获取数据库连接（上下文管理器）"""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        yield conn
