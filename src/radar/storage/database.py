"""数据库引擎与会话工厂（同时支持 PostgreSQL 和 SQLite）"""
from __future__ import annotations

import contextlib
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession,
    async_sessionmaker, create_async_engine,
)

from radar.config import settings
from radar.storage.models import Base

_async_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def _make_engine(url: str) -> AsyncEngine:
    is_sqlite = url.startswith("sqlite")
    kwargs: dict = {
        "echo": False,
        "future": True,
    }
    if not is_sqlite:
        kwargs.update({
            "pool_size": 10,
            "max_overflow": 20,
            "pool_pre_ping": True,
            "pool_recycle": 3600,
        })
    else:
        kwargs.update({"connect_args": {"check_same_thread": False}})
    return create_async_engine(url, **kwargs)


def get_engine() -> AsyncEngine:
    global _async_engine
    if _async_engine is None:
        _async_engine = _make_engine(settings.db_async_url)
    return _async_engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, autoflush=False
        )
    return _async_session_factory


@contextlib.asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """建表（idempotent，仅 dev/test 使用，生产走 Alembic）"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    global _async_engine, _async_session_factory
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _async_session_factory = None


def override_engine(url: str) -> None:
    """测试专用：替换引擎（支持 testcontainers 动态注入 URL）"""
    global _async_engine, _async_session_factory
    _async_engine = _make_engine(url)
    _async_session_factory = async_sessionmaker(
        _async_engine, expire_on_commit=False, autoflush=False
    )
