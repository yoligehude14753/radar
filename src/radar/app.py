"""FastAPI 应用工厂"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from radar.config import settings
from radar.storage.database import close_db, init_db
from radar.runtime.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    await start_scheduler()
    yield
    await stop_scheduler()
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
        allow_origins=["*"] if settings.debug else [
            f"http://localhost:{settings.web_port}",
            f"http://127.0.0.1:{settings.web_port}",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── API 路由（必须在静态文件 / catch-all 之前注册）─────────────────────
    from radar.web.api import router as api_router
    app.include_router(api_router, prefix="/api")

    # ── 静态文件：outputs 报告 ──────────────────────────────────────────────
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/outputs", StaticFiles(directory=str(settings.output_dir)), name="outputs")

    # ── 前端 SPA：编译产物 ──────────────────────────────────────────────────
    _frontend = settings.base_dir / "web" / "dist"

    if _frontend.exists():
        # JS / CSS 等 hash 资源直接 mount（避免 catch-all 扫描）
        _assets = _frontend / "assets"
        if _assets.exists():
            app.mount("/assets", StaticFiles(directory=str(_assets)), name="spa-assets")

        # SPA catch-all：API / outputs / assets 都已在上方拦截，
        # 剩余所有路径（包括 /settings /tokens 等客户端路由）均返回 index.html
        @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
        async def _spa(full_path: str) -> FileResponse | JSONResponse:
            # 尝试直接命中 dist 目录下的文件（如 favicon.svg）
            candidate: Path = _frontend / full_path
            if candidate.exists() and candidate.is_file():
                return FileResponse(str(candidate))
            # 客户端路由 → 返回 index.html，由 React Router 接管
            index: Path = _frontend / "index.html"
            if index.exists():
                return FileResponse(str(index), media_type="text/html")
            return JSONResponse({"error": "frontend not built, run: cd web && npm run build"}, status_code=503)

    return app
