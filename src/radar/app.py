"""FastAPI 应用工厂"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from radar.config import settings
from radar.storage.database import close_db, init_db


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Radar",
        description="AI 需求抓取 · 趋势分析平台",
        version="0.1.0",
        lifespan=_lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else [f"http://localhost:{settings.web_port}"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册 API 路由（后续按模块添加）
    from radar.web.api import router as api_router
    app.include_router(api_router, prefix="/api")

    # 静态文件（outputs 报告）
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/outputs", StaticFiles(directory=str(settings.output_dir)), name="outputs")

    # 前端 SPA（build 后才存在）
    _frontend = settings.base_dir / "web" / "dist"
    if _frontend.exists():
        app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")

    return app
