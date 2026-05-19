"""
E2E 测试：GitHub 数据源全链路

验收条件（用户可观察结果）：
  1. 模拟 GitHub API 返回数据，爬取后 DB 有 Item 记录
  2. 增量游标：第二次爬取不重复写入相同 url
  3. SourceRun 记录状态正确（done/failed）
  4. dry_run 模式不写库
  5. API 返回 GitHub 源统计
  6. Token 无效时返回明确错误，不崩溃
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from radar.storage.models import Item, SourceRun


# ── 测试用 Fixture GitHub API 返回 ────────────────────────────────────────

MOCK_REPOS = [
    {
        "full_name": "test-org/ai-agent-tool",
        "html_url": "https://github.com/test-org/ai-agent-tool",
        "description": "An AI agent toolkit",
        "stars": 500,
        "forks": 50,
        "language": "Python",
        "topics": ["llm", "agent"],
        "license": "MIT",
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-10T00:00:00Z",
        "pushed_at": "2026-05-10T00:00:00Z",
        "owner_login": "test-org",
        "owner_type": "Organization",
        "is_fork": False,
        "is_archived": False,
        "watchers": 500,
        "open_issues": 10,
    },
    {
        "full_name": "alice/mcp-server",
        "html_url": "https://github.com/alice/mcp-server",
        "description": "MCP server implementation",
        "stars": 200,
        "forks": 20,
        "language": "TypeScript",
        "topics": ["mcp", "llm"],
        "license": "Apache-2.0",
        "created_at": "2026-05-05T00:00:00Z",
        "updated_at": "2026-05-12T00:00:00Z",
        "pushed_at": "2026-05-12T00:00:00Z",
        "owner_login": "alice",
        "owner_type": "User",
        "is_fork": False,
        "is_archived": False,
        "watchers": 200,
        "open_issues": 5,
    },
]


@pytest.mark.asyncio
async def test_github_crawl_writes_items(db_url: str) -> None:
    """
    核心 E2E：mock GitHub API → crawl → DB 有 Items
    验收：items 数量 = mock 返回数量，source_run 状态 = done
    """
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Item, SourceRun
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    with patch(
        "radar.sources.github.crawler.GitHubClient",
        autospec=True,
    ) as MockClient:
        # 设置 mock：get_trending_repos 返回 MOCK_REPOS
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_trending_repos = AsyncMock(return_value=MOCK_REPOS)
        instance.get_rate_limit = AsyncMock(return_value={"limit": 5000, "remaining": 4999})

        from radar.sources.github.crawler import crawl_github
        result = await crawl_github(dry_run=False)

    assert result["status"] == "done"
    assert result["items_in"] == 2
    assert result["items_new"] == 2

    # 验证数据库中有记录
    async with get_session() as session:
        items = (await session.execute(select(Item).where(Item.source == "github"))).scalars().all()
        assert len(items) == 2

        full_names = {i.external_id for i in items}
        assert "test-org/ai-agent-tool" in full_names
        assert "alice/mcp-server" in full_names

        # platform_data 存储了 stars 等字段
        for item in items:
            assert item.platform_data is not None
            assert "stars" in item.platform_data
            assert item.source_run_id is not None

        # SourceRun 状态 = done
        run = (await session.execute(
            select(SourceRun).where(SourceRun.source == "github").order_by(SourceRun.created_at.desc())
        )).scalar_one_or_none()
        assert run is not None
        assert run.status == "done"
        assert run.items_in == 2
        assert run.items_new == 2


@pytest.mark.asyncio
async def test_github_crawl_incremental_dedup(db_url: str) -> None:
    """
    增量去重：同一 repo 第二次爬取不新增
    验收：第二次 items_new = 0
    """
    from radar.storage.database import override_engine, init_db
    from radar.sources.github.crawler import crawl_github

    override_engine(db_url)
    await init_db()

    with patch("radar.sources.github.crawler.GitHubClient", autospec=True) as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_trending_repos = AsyncMock(return_value=MOCK_REPOS)

        # 第一次抓取
        result1 = await crawl_github()
        assert result1["items_new"] == 2

        # 第二次抓取：同样的 repos
        result2 = await crawl_github()
        assert result2["items_new"] == 0, "同一 URL 不应重复写入"
        assert result2["items_in"] == 2  # 抓到了，但是去重后不新增


@pytest.mark.asyncio
async def test_github_crawl_dry_run_no_db_write(db_url: str) -> None:
    """
    dry_run 模式：不写入数据库
    验收：DB 中没有 Item，返回 status=dry_run
    """
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Item
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    with patch("radar.sources.github.crawler.GitHubClient", autospec=True) as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_trending_repos = AsyncMock(return_value=MOCK_REPOS)

        from radar.sources.github.crawler import crawl_github
        result = await crawl_github(dry_run=True)

    assert result["status"] == "dry_run"

    async with get_session() as session:
        count = len((await session.execute(select(Item))).scalars().all())
        assert count == 0, "dry_run 不应写入任何数据"


@pytest.mark.asyncio
async def test_github_crawl_api_failure_records_failed_run(db_url: str) -> None:
    """
    GitHub API 失败时：SourceRun 状态 = failed，不崩溃
    验收：返回 status=error，DB 中有 failed 状态的 SourceRun
    """
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import SourceRun
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    with patch("radar.sources.github.crawler.GitHubClient", autospec=True) as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_trending_repos = AsyncMock(side_effect=Exception("网络超时"))

        from radar.sources.github.crawler import crawl_github
        result = await crawl_github()

    assert result["status"] == "error"
    assert "网络超时" in result.get("error", "")

    async with get_session() as session:
        run = (await session.execute(
            select(SourceRun).where(SourceRun.source == "github")
        )).scalar_one_or_none()
        assert run is not None
        assert run.status == "failed"
        assert run.error is not None


@pytest.mark.asyncio
async def test_github_source_visible_in_api(client, db_url: str, app_with_db) -> None:
    """
    抓取完成后，/api/sources 接口能看到 github 源的统计
    验收：source=github，last_run_status=done，total_items >= 1
    """
    from radar.storage.database import override_engine

    override_engine(db_url)

    with patch("radar.sources.github.crawler.GitHubClient", autospec=True) as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_trending_repos = AsyncMock(return_value=MOCK_REPOS)

        from radar.sources.github.crawler import crawl_github
        await crawl_github()

    resp = await client.get("/api/sources")
    assert resp.status_code == 200
    sources = resp.json()

    github_src = next((s for s in sources if s["source"] == "github"), None)
    assert github_src is not None, "抓取后 /api/sources 中应该有 github"
    assert github_src["total_items"] >= 1
    assert github_src["last_run_status"] == "done"
    assert github_src["last_run_items_new"] == 2


@pytest.mark.asyncio
async def test_github_raw_blob_saved(db_url: str) -> None:
    """
    RawBlob 原始 payload 正确保存（供评分重跑使用）
    验收：每个 Item 都有对应的 RawBlob，且 payload 是合法 JSON
    """
    import json

    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Item, RawBlob
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    override_engine(db_url)
    await init_db()

    with patch("radar.sources.github.crawler.GitHubClient", autospec=True) as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_trending_repos = AsyncMock(return_value=MOCK_REPOS)

        from radar.sources.github.crawler import crawl_github
        await crawl_github()

    async with get_session() as session:
        items = (await session.execute(
            select(Item)
            .options(selectinload(Item.raw_blob))
            .where(Item.source == "github")
        )).scalars().all()

        assert len(items) == 2
        for item in items:
            assert item.raw_blob is not None, f"Item {item.external_id} 缺少 RawBlob"
            payload = json.loads(item.raw_blob.payload)
            assert "full_name" in payload
            assert "stars" in payload
