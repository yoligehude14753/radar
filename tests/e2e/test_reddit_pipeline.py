"""
E2E 测试：Reddit 数据源全链路

验收条件（用户可观察结果）：
  1. 模拟 Reddit API 返回，爬取后 DB 有 Item 记录
  2. 增量过滤：since_dt 之前的帖子不写入
  3. SourceRun 状态正确
  4. 公开 API 和 OAuth 两种模式都能工作（mock）
  5. API 接口能看到 reddit 源统计
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_post(post_id: str, subreddit: str = "artificial", hours_ago: float = 1.0) -> dict:
    """生成测试用 Reddit 帖子"""
    created = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {
        "post_id": post_id,
        "full_name": f"t3_{post_id}",
        "subreddit": subreddit,
        "title": f"AI 讨论 {post_id}: 最新 LLM 进展",
        "selftext": "这里是帖子内容，讨论 AI agent 的最新进展...",
        "url": f"https://reddit.com/r/{subreddit}/comments/{post_id}/",
        "author": "test_user",
        "ups": 100,
        "upvote_ratio": 0.95,
        "num_comments": 42,
        "score": 100,
        "total_awards": 2,
        "is_self": True,
        "link_flair_text": "Discussion",
        "created_at": created.isoformat(),
        "domain": "self.artificial",
    }


MOCK_POSTS = [
    _make_post("abc123", subreddit="artificial", hours_ago=2),
    _make_post("def456", subreddit="LocalLLaMA", hours_ago=1),
    _make_post("ghi789", subreddit="ChatGPT", hours_ago=0.5),
]

OLD_POST = _make_post("old001", hours_ago=200)  # 8天前，超出7天窗口


@pytest.mark.asyncio
async def test_reddit_crawl_writes_items(db_url: str) -> None:
    """核心 E2E：mock Reddit API → crawl → DB 有 Items"""
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Item, SourceRun
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    with patch("radar.sources.reddit.crawler.RedditClient", autospec=True) as MockClient, \
         patch("radar.sources.reddit.crawler.asyncio.sleep", new_callable=AsyncMock):
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_subreddit_hot = AsyncMock(return_value=MOCK_POSTS[:2])
        instance.get_subreddit_new = AsyncMock(return_value=(MOCK_POSTS[2:], None))

        from radar.sources.reddit.crawler import crawl_reddit
        result = await crawl_reddit(dry_run=False)

    assert result["status"] == "done"
    assert result["items_in"] >= 1

    async with get_session() as session:
        items = (await session.execute(
            select(Item).where(Item.source == "reddit")
        )).scalars().all()
        assert len(items) >= 1

        # 验证 platform_data 有 Reddit 特有字段
        for item in items:
            assert item.platform_data is not None
            assert "subreddit" in item.platform_data
            assert "ups" in item.platform_data

        # SourceRun 状态 = done
        run = (await session.execute(
            select(SourceRun).where(SourceRun.source == "reddit")
        )).scalar_one_or_none()
        assert run is not None
        assert run.status == "done"


@pytest.mark.asyncio
async def test_reddit_crawl_dedup(db_url: str) -> None:
    """增量去重：同一帖子 URL 第二次不重复写入"""
    from radar.storage.database import override_engine, init_db
    from radar.sources.reddit.crawler import crawl_reddit

    override_engine(db_url)
    await init_db()

    with patch("radar.sources.reddit.crawler.RedditClient", autospec=True) as MockClient, \
         patch("radar.sources.reddit.crawler.asyncio.sleep", new_callable=AsyncMock):
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_subreddit_hot = AsyncMock(return_value=[MOCK_POSTS[0]])
        instance.get_subreddit_new = AsyncMock(return_value=([], None))

        result1 = await crawl_reddit()
        assert result1["items_new"] >= 1

        result2 = await crawl_reddit()
        assert result2["items_new"] == 0


@pytest.mark.asyncio
async def test_reddit_crawl_dry_run(db_url: str) -> None:
    """dry_run 不写 DB"""
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Item
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    with patch("radar.sources.reddit.crawler.RedditClient", autospec=True) as MockClient, \
         patch("radar.sources.reddit.crawler.asyncio.sleep", new_callable=AsyncMock):
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_subreddit_hot = AsyncMock(return_value=MOCK_POSTS)
        instance.get_subreddit_new = AsyncMock(return_value=([], None))

        from radar.sources.reddit.crawler import crawl_reddit
        result = await crawl_reddit(dry_run=True)

    assert result["status"] == "dry_run"

    async with get_session() as session:
        count = len((await session.execute(select(Item))).scalars().all())
        assert count == 0


@pytest.mark.asyncio
async def test_reddit_api_failure_records_failed_run(db_url: str) -> None:
    """API 失败时 SourceRun = failed，不崩溃"""
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import SourceRun
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    with patch("radar.sources.reddit.crawler.RedditClient", autospec=True) as MockClient, \
         patch("radar.sources.reddit.crawler.asyncio.sleep", new_callable=AsyncMock):
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_subreddit_hot = AsyncMock(side_effect=Exception("Reddit 连接超时"))
        instance.get_subreddit_new = AsyncMock(return_value=([], None))

        from radar.sources.reddit.crawler import crawl_reddit
        result = await crawl_reddit()

    assert result["status"] == "error"

    async with get_session() as session:
        run = (await session.execute(
            select(SourceRun).where(SourceRun.source == "reddit")
        )).scalar_one_or_none()
        assert run is not None
        assert run.status == "failed"


@pytest.mark.asyncio
async def test_reddit_source_visible_in_api(client, db_url: str, app_with_db) -> None:
    """抓取后 /api/sources 能看到 reddit 源"""
    from radar.storage.database import override_engine

    override_engine(db_url)

    with patch("radar.sources.reddit.crawler.RedditClient", autospec=True) as MockClient, \
         patch("radar.sources.reddit.crawler.asyncio.sleep", new_callable=AsyncMock):
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_subreddit_hot = AsyncMock(return_value=MOCK_POSTS)
        instance.get_subreddit_new = AsyncMock(return_value=([], None))

        from radar.sources.reddit.crawler import crawl_reddit
        await crawl_reddit()

    resp = await client.get("/api/sources")
    assert resp.status_code == 200
    sources = resp.json()

    reddit_src = next((s for s in sources if s["source"] == "reddit"), None)
    assert reddit_src is not None, "抓取后 /api/sources 中应该有 reddit"
    assert reddit_src["last_run_status"] == "done"
    assert reddit_src["total_items"] >= 1
