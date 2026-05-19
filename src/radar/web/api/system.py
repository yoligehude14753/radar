"""系统状态 API"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from radar.config import settings

router = APIRouter()


class HealthResp(BaseModel):
    status: str
    version: str
    db_type: str     # sqlite / postgresql（不暴露路径和密码）
    llm_profile: str


@router.get("/health", response_model=HealthResp, summary="健康检查")
async def health() -> HealthResp:
    db_url = settings.db_async_url
    db_type = "sqlite" if "sqlite" in db_url else "postgresql"
    return HealthResp(
        status="ok",
        version="0.1.0",
        db_type=db_type,
        llm_profile=settings.llm_profile.value,
    )
