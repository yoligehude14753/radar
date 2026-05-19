"""Reddit 数据源爬取器（迁移自 aha/adapters/reddit.py）

专注 AI 相关 subreddit，使用公开 JSON API（零配置可用）。
增量游标：记录每个 subreddit 最近抓取的时间戳，避免重复。
"""
from __future__ import annotations

import asyncio
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
from radar.sources.reddit.client import AI_SUBREDDITS, RedditClient

logger = structlog.get_logger(__name__)

_SOURCE = "reddit"
# AI 相关搜索词，从 aha/reddit.py 的经验提炼
_AI_KEYWORDS = [
    "AI agent", "LLM", "ChatGPT", "Claude", "prompt engineering",
    "machine learning", "open source AI", "MCP", "RAG", "embedding",
]


async def crawl_reddit(dry_run: bool = False) -> dict:
    """
    执行一次 Reddit 增量抓取。
    策略：热门帖子（hot）+ 最新帖子（new），覆盖 AI_SUBREDDITS
    """
    client_id = settings.reddit_client_id
    client_secret = settings.reddit_client_secret
    user_agent = settings.reddit_user_agent

    if not client_id:
        logger.info("Reddit OAuth 未配置，使用公开 API 模式")

    since_dt = await _get_cursor()
    log = logger.bind(since=since_dt.isoformat(), dry_run=dry_run, has_oauth=bool(client_id))
    log.info("开始 Reddit 抓取")

    run_id: Optional[str] = None
    if not dry_run:
        run_id = await _create_run(since_dt.isoformat())

    items_raw: list[dict] = []
    try:
        async with RedditClient(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        ) as client:
            items_raw, success_count = await _fetch_all_subreddits(client, since_dt)
        log.info("Reddit 抓取完成", raw_count=len(items_raw), success_subreddits=success_count)

        # 全部 subreddit 失败 = 系统性错误（网络/认证问题）
        if success_count == 0 and len(AI_SUBREDDITS) > 0:
            error_msg = "所有 subreddit 均抓取失败，可能是网络或认证问题"
            if run_id:
                await _fail_run(run_id, error_msg)
            return {"status": "error", "error": error_msg}

    except Exception as exc:
        log.exception("Reddit 抓取失败", error=str(exc))
        if run_id:
            await _fail_run(run_id, str(exc))
        return {"status": "error", "error": str(exc)}

    if dry_run:
        return {"status": "dry_run", "items_in": len(items_raw)}

    items_new = await _save_items(items_raw, run_id)
    new_cursor = datetime.now(timezone.utc).isoformat()
    await _finish_run(run_id, items_in=len(items_raw), items_new=items_new, cursor=new_cursor)

    log.info("Reddit 抓取写入完成", items_in=len(items_raw), items_new=items_new)
    return {"status": "done", "items_in": len(items_raw), "items_new": items_new}


# ── 抓取逻辑 ──────────────────────────────────────────────────────────────


async def _fetch_all_subreddits(client: RedditClient, since_dt: datetime) -> tuple[list[dict], int]:
    """
    遍历 AI_SUBREDDITS，每个获取热门 + 最新帖子。
    过滤掉 since_dt 之前的内容。
    返回 (posts, success_count)
    """
    all_posts: list[dict] = []
    seen_ids: set[str] = set()
    success_count = 0

    for subreddit in AI_SUBREDDITS:
        try:
            # 热门帖子（周维度）
            hot_posts = await client.get_subreddit_hot(subreddit, limit=25)
            for post in hot_posts:
                _dedup_add(post, since_dt, seen_ids, all_posts)

            # 等待避免限速（公开 API ~30 req/10min）
            await asyncio.sleep(2.0)

            # 最新帖子
            new_posts, _ = await client.get_subreddit_new(subreddit, limit=25)
            for post in new_posts:
                _dedup_add(post, since_dt, seen_ids, all_posts)

            await asyncio.sleep(1.5)
            success_count += 1

        except Exception as exc:
            logger.warning("Reddit 抓取 subreddit 失败", subreddit=subreddit, error=str(exc))
            await asyncio.sleep(5.0)
            continue

    return all_posts, success_count


def _dedup_add(
    post: dict,
    since_dt: datetime,
    seen_ids: set[str],
    results: list[dict],
) -> None:
    """本次抓取内去重，并过滤过旧的帖子"""
    post_id = post.get("post_id", "")
    if not post_id or post_id in seen_ids:
        return

    # 时间过滤：只保留 since_dt 之后的帖子
    created_at_str = post.get("created_at", "")
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if created_at < since_dt:
                return  # 太旧，跳过
        except ValueError:
            pass  # 解析失败时不过滤

    seen_ids.add(post_id)
    results.append(post)


# ── 游标管理 ──────────────────────────────────────────────────────────────


async def _get_cursor() -> datetime:
    """取上次成功运行的游标，默认 7 天前"""
    async with get_session() as session:
        result = await session.execute(
            select(SourceRun)
            .where(SourceRun.source == _SOURCE, SourceRun.status == "done")
            .order_by(SourceRun.created_at.desc())
            .limit(1)
        )
        last_run = result.scalar_one_or_none()

    if last_run and last_run.cursor:
        try:
            dt = datetime.fromisoformat(last_run.cursor)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass

    return datetime.now(timezone.utc) - timedelta(days=7)


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
    new_count = 0
    async with get_session() as session:
        for raw in items_raw:
            url = raw.get("url", "")
            if not url:
                continue
            url_hash = hashlib.sha256(url.encode()).hexdigest()

            existing = await session.execute(
                select(Item.id).where(Item.url_hash == url_hash)
            )
            if existing.scalar_one_or_none():
                continue

            item_at: Optional[datetime] = None
            if raw.get("created_at"):
                try:
                    item_at = datetime.fromisoformat(raw["created_at"])
                    if item_at.tzinfo is None:
                        item_at = item_at.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

            title = raw.get("title", "")
            content = raw.get("selftext", "")

            item = Item(
                source=_SOURCE,
                external_id=raw.get("full_name") or raw.get("post_id", ""),
                url=url,
                url_hash=url_hash,
                title=title[:500],
                content=content[:5000],
                platform_data={
                    "subreddit": raw.get("subreddit", ""),
                    "post_id": raw.get("post_id", ""),
                    "author": raw.get("author", ""),
                    "ups": raw.get("ups", 0),
                    "upvote_ratio": raw.get("upvote_ratio", 0.0),
                    "num_comments": raw.get("num_comments", 0),
                    "score": raw.get("score", 0),
                    "total_awards": raw.get("total_awards", 0),
                    "is_self": raw.get("is_self", True),
                    "flair": raw.get("link_flair_text", ""),
                    "domain": raw.get("domain", ""),
                },
                source_run_id=run_id,
                item_at=item_at,
            )
            session.add(item)
            await session.flush()

            blob = RawBlob(
                item_id=item.id,
                payload=json.dumps(raw, ensure_ascii=False),
                content_type="application/json",
            )
            session.add(blob)
            new_count += 1

    return new_count
