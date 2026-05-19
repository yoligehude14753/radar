"""API 路由聚合"""
from fastapi import APIRouter

from radar.web.api import incidents, reports, sources, system

router = APIRouter()
router.include_router(system.router, prefix="/system", tags=["系统"])
router.include_router(sources.router, prefix="/sources", tags=["数据源"])
router.include_router(reports.router, prefix="/reports", tags=["报告"])
router.include_router(incidents.router, prefix="/incidents", tags=["事件"])
