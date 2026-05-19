"""报告查看 API"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from radar.storage.database import get_session
from radar.storage.models import Report

router = APIRouter()


class ReportInfo(BaseModel):
    id: str
    template: str
    period_key: str
    item_count: int
    status: str
    file_path: Optional[str]
    generated_at: str


def _to_info(r: Report) -> ReportInfo:
    return ReportInfo(
        id=r.id,
        template=r.template,
        period_key=r.period_key,
        item_count=r.item_count,
        status=r.status,
        file_path=r.file_path,
        generated_at=r.generated_at.isoformat(),
    )


@router.get("", response_model=list[ReportInfo], summary="历史报告列表")
async def list_reports(template: Optional[str] = None, limit: int = 30) -> list[ReportInfo]:
    async with get_session() as session:
        q = select(Report).order_by(Report.generated_at.desc()).limit(limit)
        if template:
            q = q.where(Report.template == template)
        result = await session.execute(q)
        return [_to_info(r) for r in result.scalars()]


@router.get("/latest/{template}", response_model=ReportInfo, summary="最新报告信息")
async def latest_report(template: str) -> ReportInfo:
    async with get_session() as session:
        result = await session.execute(
            select(Report)
            .where(Report.template == template, Report.status == "ok")
            .order_by(Report.generated_at.desc())
            .limit(1)
        )
        report = result.scalar_one_or_none()
        if not report:
            raise HTTPException(404, f"没有可用的 {template} 报告，请等待下次 cron 渲染")
        return _to_info(report)


@router.get("/{report_id}/file", summary="下载报告 HTML 文件")
async def download_report(report_id: str) -> FileResponse:
    async with get_session() as session:
        result = await session.execute(select(Report).where(Report.id == report_id))
        report = result.scalar_one_or_none()
        if not report or not report.file_path:
            raise HTTPException(404, "报告文件不存在")
        import pathlib
        p = pathlib.Path(report.file_path)
        if not p.exists():
            raise HTTPException(404, f"文件已被清理: {report.file_path}")
        return FileResponse(str(p), media_type="text/html", filename=p.name)
