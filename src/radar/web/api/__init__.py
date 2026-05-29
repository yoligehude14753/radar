"""API 路由聚合"""
from fastapi import APIRouter

from radar.web.api import (
    eval as eval_api,
    incidents,
    items,
    reports,
    sources,
    system,
    tokens,
    settings_api,
)
from radar.config import settings
from pydantic import BaseModel


class HealthResp(BaseModel):
    status: str
    version: str
    db_url: str
    llm_profile: str


router = APIRouter()
router.include_router(system.router, prefix="/system", tags=["系统"])
router.include_router(sources.router, prefix="/sources", tags=["数据源"])
router.include_router(items.router, prefix="/items", tags=["条目"])
router.include_router(eval_api.router, prefix="/eval", tags=["实测结果"])
router.include_router(reports.router, prefix="/reports", tags=["报告"])
router.include_router(incidents.router, prefix="/incidents", tags=["事件"])
router.include_router(tokens.router, prefix="/tokens", tags=["凭证管理"])
router.include_router(settings_api.router, prefix="/settings", tags=["系统设置"])


@router.get("/health", response_model=HealthResp, tags=["系统"], summary="健康检查（简短路径）")
async def health_shortcut() -> HealthResp:
    return HealthResp(
        status="ok",
        version="0.1.0",
        db_url=settings.db_async_url.split("@")[-1],
        llm_profile=settings.llm_profile.value,
    )
