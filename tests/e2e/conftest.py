"""E2E 测试公共 fixtures

测试策略：
- 用 SQLite in-memory 替代 PG（schema 兼容），不依赖 testcontainers，CI 零外部依赖
- LLM 调用全部用 respx mock，返回固定 JSON
- HTTP 源（GitHub API / Reddit API）用 respx mock
- 每个测试函数独立 DB（function scope），互不干扰
- 测试验证的是"用户可观察结果"：文件落盘、API 返回、报告可访问，而非内部实现
"""
from __future__ import annotations

import os
import pytest
import pytest_asyncio
from pathlib import Path
from httpx import AsyncClient
from fastapi import FastAPI

# 强制使用测试 LLM profile 和 SQLite
os.environ.setdefault("LLM_PROFILE", "ollama")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")  # 会被 mock
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest_asyncio.fixture(scope="function")
async def db_url(tmp_path: Path) -> str:
    """每次测试独立 SQLite DB"""
    return f"sqlite+aiosqlite:///{tmp_path}/test.db"


@pytest_asyncio.fixture(scope="function")
async def app_with_db(db_url: str, tmp_path: Path) -> FastAPI:
    """带测试 DB 的 FastAPI 实例"""
    from radar.storage.database import override_engine, init_db, close_db
    from radar.config import settings

    override_engine(db_url)

    # 重定向输出目录到 tmp_path
    settings.__dict__["_output_dir_override"] = tmp_path / "outputs"
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)

    await init_db()
    from radar.app import create_app

    _app = create_app()
    yield _app

    await close_db()


@pytest_asyncio.fixture(scope="function")
async def client(app_with_db: FastAPI) -> AsyncClient:
    """针对 FastAPI 的异步 HTTP 客户端（httpx 0.28+ 用 ASGITransport）"""
    import httpx
    transport = httpx.ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
