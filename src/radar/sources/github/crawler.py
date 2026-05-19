"""GitHub 数据源爬取器

整合自：
- openall/agent-radar/src/contexts/crawler/infrastructure/github_client.py
- aha/projects/aha/src/adapters/github_radar_monitor.py

功能：
- 增量抓取（基于 created_at 游标，不重复抓历史）
- 去重（url_hash 唯一约束）
- SourceRun 记录（供监控引擎检测停滞）
- 原始 payload 写入 RawBlob（供评分重跑）
- 支持 dry_run 模式（只打印不写库）
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from radar.config import settings
from radar.storage.database import get_session
from radar.storage.models import Item, RawBlob, SourceRun
from radar.sources.github.client import GitHubClient

logger = structlog.get_logger(__name__)

_SOURCE = "github"
# AI 相关关键词（来自 agent-radar 的经验积累）
_AI_KEYWORDS = [
    "llm", "agent", "mcp", "openai", "claude", "gemini",
    "rag", "embedding", "chatbot", "copilot", "gpt", "langchain",
]


async def crawl_github(dry_run: bool = False) -> dict:
    """
    执行一次 GitHub 增量抓取。
    返回 {"status": "done", "items_in": N, "items_new": M}
    """
    token = settings.github_token
    if not token:
        logger.warning("github_token 未配置，使用匿名模式（速率限制 60 次/小时）")

    # 确定增量游标
    since_date = await _get_cursor()
    log = logger.bind(since_date=since_date, dry_run=dry_run, has_token=bool(token))
    log.info("开始 GitHub 抓取")

    # 创建 SourceRun 记录
    run_id: Optional[str] = None
    if not dry_run:
        run_id = await _create_run(since_date)

    # 执行抓取
    items_raw: list[dict] = []
    try:
        async with GitHubClient(token=token) as client:
            items_raw = await client.get_trending_repos(
                since_date=since_date,
                max_results=settings.max_items_per_run,
            )
        log.info("GitHub 抓取完成", raw_count=len(items_raw))
    except Exception as exc:
        log.exception("GitHub 抓取失败", error=str(exc))
        if run_id:
            await _fail_run(run_id, str(exc))
        return {"status": "error", "error": str(exc)}

    if dry_run:
        log.info("dry_run 模式，跳过写库", items=len(items_raw))
        return {"status": "dry_run", "items_in": len(items_raw)}

    # 写入数据库
    items_new = await _save_items(items_raw, run_id)

    # 更新游标（用本次最新 item 的 created_at）
    new_cursor = _compute_new_cursor(items_raw, since_date)
    await _finish_run(run_id, items_in=len(items_raw), items_new=items_new, cursor=new_cursor)

    log.info("GitHub 抓取写入完成", items_in=len(items_raw), items_new=items_new, new_cursor=new_cursor)
    return {"status": "done", "items_in": len(items_raw), "items_new": items_new}


# ── 游标管理 ──────────────────────────────────────────────────────────────


async def _get_cursor() -> str:
    """
    从最近一次成功运行记录中取游标。
    若无历史记录，默认取 30 天前（保证首次有数据）。
    """
    async with get_session() as session:
        result = await session.execute(
            select(SourceRun)
            .where(SourceRun.source == _SOURCE, SourceRun.status == "done")
            .order_by(SourceRun.created_at.desc())
            .limit(1)
        )
        last_run = result.scalar_one_or_none()

    if last_run and last_run.cursor:
        return last_run.cursor

    # 首次运行：30 天前
    since = datetime.now(timezone.utc) - timedelta(days=30)
    return since.strftime("%Y-%m-%d")


def _compute_new_cursor(items: list[dict], fallback: str) -> str:
    """计算新游标：取本次最新 created_at"""
    dates = [
        item["created_at"][:10]
        for item in items
        if item.get("created_at")
    ]
    if not dates:
        return fallback
    # 取最新日期（不能超过今天，避免漏掉当天其他项目）
    latest = max(dates)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # 往前退 1 天作为游标（避免边界漏掉）
    if latest >= today:
        d = datetime.now(timezone.utc) - timedelta(days=1)
        return d.strftime("%Y-%m-%d")
    return latest


# ── SourceRun CRUD ────────────────────────────────────────────────────────


async def _create_run(cursor: str) -> str:
    async with get_session() as session:
        run = SourceRun(
            source=_SOURCE,
            cursor=cursor,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.flush()
        return run.id


async def _finish_run(run_id: str, items_in: int, items_new: int, cursor: str) -> None:
    async with get_session() as session:
        result = await session.execute(select(SourceRun).where(SourceRun.id == run_id))
        run = result.scalar_one_or_none()
        if run:
            run.status = "done"
            run.items_in = items_in
            run.items_new = items_new
            run.cursor = cursor
            run.finished_at = datetime.now(timezone.utc)


async def _fail_run(run_id: str, error: str) -> None:
    async with get_session() as session:
        result = await session.execute(select(SourceRun).where(SourceRun.id == run_id))
        run = result.scalar_one_or_none()
        if run:
            run.status = "failed"
            run.error = error[:1000]
            run.finished_at = datetime.now(timezone.utc)


# ── 数据写入 ──────────────────────────────────────────────────────────────


async def _save_items(items_raw: list[dict], run_id: Optional[str]) -> int:
    """批量写入 Item + RawBlob，返回实际新增数量"""
    new_count = 0
    async with get_session() as session:
        for raw in items_raw:
            full_name = raw.get("full_name", "")
            url = raw.get("html_url") or f"https://github.com/{full_name}"
            url_hash = hashlib.sha256(url.encode()).hexdigest()

            # 检查是否已存在
            existing = await session.execute(
                select(Item.id).where(Item.url_hash == url_hash)
            )
            if existing.scalar_one_or_none():
                continue  # 已存在，跳过（增量去重）

            # 解析 item_at
            item_at: Optional[datetime] = None
            if raw.get("created_at"):
                try:
                    item_at = datetime.fromisoformat(raw["created_at"].replace("Z", "+00:00"))
                except ValueError:
                    pass

            item = Item(
                source=_SOURCE,
                external_id=full_name,
                url=url,
                url_hash=url_hash,
                title=full_name,
                content=raw.get("description", ""),
                platform_data={
                    "stars": raw.get("stars", 0),
                    "forks": raw.get("forks", 0),
                    "language": raw.get("language", ""),
                    "topics": raw.get("topics", []),
                    "open_issues": raw.get("open_issues", 0),
                    "license": raw.get("license", ""),
                    "owner_login": raw.get("owner_login", ""),
                    "owner_type": raw.get("owner_type", ""),
                    "is_fork": raw.get("is_fork", False),
                    "is_archived": raw.get("is_archived", False),
                    "pushed_at": raw.get("pushed_at", ""),
                    "updated_at": raw.get("updated_at", ""),
                    "watchers": raw.get("watchers", 0),
                },
                source_run_id=run_id,
                item_at=item_at,
            )
            session.add(item)
            await session.flush()

            # 保存原始 payload（供评分重跑）
            blob = RawBlob(
                item_id=item.id,
                payload=json.dumps(raw, ensure_ascii=False),
                content_type="application/json",
            )
            session.add(blob)
            new_count += 1

    return new_count
