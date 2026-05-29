"""已发现条目（带 QAG 评分）API。

供下游评测流水线（heyi-eval）消费：拉取已打分的热点条目，按
QAG 综合分排序，作为 project_lane / 评测队列的候选来源。

这是 radar→heyi-eval 合并的「发现」侧集成面：heyi-eval 的
``discover/radar_local_ingest.py`` 调用 ``GET /api/items`` 取 top-N
热点，映射成 ProjectCandidate 入队。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from radar.storage.database import get_session
from radar.storage.models import Item, Score

router = APIRouter()

# Cap how many rows we scan from the DB before post-filtering, so a
# pathological request can't pull the whole table into memory. The
# scan is ordered newest-first, so the freshest hotspots are always
# considered even when the table is larger than this.
_MAX_SCAN = 2000


class ScoredItem(BaseModel):
    id: str
    source: str
    external_id: str
    url: str
    title: Optional[str]
    content: Optional[str]
    platform_data: dict
    score: Optional[float]
    dimensions: dict
    domain: Optional[str]
    fetched_at: Optional[datetime]


def _latest_qag(item: Item) -> Optional[Score]:
    """Most recent QAG score for an item (items may carry historical
    re-scores; we want the newest)."""
    qag = [s for s in item.scores if s.evaluator == "qag"]
    if not qag:
        return None
    return max(qag, key=lambda s: s.scored_at or datetime.min)


def _domain(item: Item) -> Optional[str]:
    for t in item.tags:
        if t.namespace == "domain":
            return t.value
    return None


@router.get("", response_model=list[ScoredItem], summary="已发现并评分的条目")
async def list_items(
    source: Optional[str] = Query(None, description="github / reddit"),
    domain: Optional[str] = Query(None, description="领域 id, 如 coding"),
    min_score: float = Query(0.0, ge=0.0, le=1.0, description="QAG 综合分下限"),
    scored_only: bool = Query(True, description="仅返回已 QAG 评分的条目"),
    limit: int = Query(100, ge=1, le=500),
) -> list[ScoredItem]:
    """已评分条目，按 QAG 综合分降序。

    过滤：``source`` / ``domain`` / ``min_score`` / ``scored_only``。
    未评分条目在 ``scored_only=false`` 时排在已评分之后（score=None）。
    """
    async with get_session() as session:
        stmt = (
            select(Item)
            .options(selectinload(Item.scores), selectinload(Item.tags))
            .order_by(Item.fetched_at.desc())
            .limit(_MAX_SCAN)
        )
        if source:
            stmt = stmt.where(Item.source == source)
        rows = (await session.execute(stmt)).scalars().all()

    ranked: list[tuple[float, ScoredItem]] = []
    for it in rows:
        qag = _latest_qag(it)
        if scored_only and qag is None:
            continue
        score_val = qag.score if qag else None
        if score_val is not None and score_val < min_score:
            continue
        dom = _domain(it)
        if domain and dom != domain:
            continue
        ranked.append((
            score_val if score_val is not None else -1.0,
            ScoredItem(
                id=it.id,
                source=it.source,
                external_id=it.external_id,
                url=it.url,
                title=it.title,
                content=((it.content or "")[:2000] or None),
                platform_data=it.platform_data or {},
                score=score_val,
                dimensions=(qag.dimensions or {}) if qag else {},
                domain=dom,
                fetched_at=it.fetched_at,
            ),
        ))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [si for _score, si in ranked[:limit]]
