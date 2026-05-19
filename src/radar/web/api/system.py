"""系统状态 API"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from radar.config import settings

router = APIRouter()


class HealthResp(BaseModel):
    status: str
    version: str
    db_url: str
    llm_profile: str


@router.get("/health", response_model=HealthResp, summary="健康检查")
async def health() -> HealthResp:
    return HealthResp(
        status="ok",
        version="0.1.0",
        db_url=settings.db_async_url.split("@")[-1],   # 隐藏密码
        llm_profile=settings.llm_profile.value,
    )
