"""数据源状态 API"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from radar.storage.database import get_session
from radar.storage.models import Item, SourceRun

router = APIRouter()


class SourceStat(BaseModel):
    source: str
    total_items: int
    last_run_at: Optional[datetime]
    last_run_status: Optional[str]
    last_run_items_in: Optional[int]
    last_run_items_new: Optional[int]


@router.get("", response_model=list[SourceStat], summary="所有数据源状态")
async def list_sources() -> list[SourceStat]:
    async with get_session() as session:
        # 各源条目总数
        counts = await session.execute(
            select(Item.source, func.count(Item.id).label("cnt"))
            .group_by(Item.source)
        )
        count_map = {row.source: row.cnt for row in counts}

        # 各源最新一次运行记录
        subq = (
            select(SourceRun.source, func.max(SourceRun.created_at).label("max_at"))
            .group_by(SourceRun.source)
            .subquery()
        )
        runs = await session.execute(
            select(SourceRun).join(
                subq,
                (SourceRun.source == subq.c.source) &
                (SourceRun.created_at == subq.c.max_at)
            )
        )
        run_map = {r.SourceRun.source: r.SourceRun for r in runs}

        sources = set(list(count_map.keys()) + list(run_map.keys()))
        result = []
        for src in sorted(sources):
            run = run_map.get(src)
            result.append(SourceStat(
                source=src,
                total_items=count_map.get(src, 0),
                last_run_at=run.created_at if run else None,
                last_run_status=run.status if run else None,
                last_run_items_in=run.items_in if run else None,
                last_run_items_new=run.items_new if run else None,
            ))
        return result


@router.post("/{source}/crawl", summary="手动触发抓取")
async def trigger_crawl(source: str) -> dict:
    supported = {"github", "reddit"}
    if source not in supported:
        raise HTTPException(status_code=404, detail=f"不支持的数据源: {source}")

    if source == "github":
        from radar.sources.github.crawler import crawl_github
        asyncio.create_task(crawl_github())
    elif source == "reddit":
        from radar.sources.reddit.crawler import crawl_reddit
        asyncio.create_task(crawl_reddit())

    return {"status": "started", "source": source}
