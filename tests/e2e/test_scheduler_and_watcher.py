"""
E2E 测试：调度器 + 监控巡检

验收条件（用户可观察结果）：
  1. 调度器启动后包含所有预期任务
  2. 手动触发 GitHub 抓取任务能正常工作
  3. 数据超期时 watcher 能创建 Incident
  4. 磁盘空间不足时 watcher 能创建 Incident（注入假数据）
  5. 多次巡检同一问题不重复创建 Incident（去重）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


@pytest.mark.asyncio
async def test_scheduler_registers_all_jobs(db_url: str, app_with_db) -> None:
    """调度器启动后包含 5 个预期任务"""
    from radar.storage.database import override_engine
    from radar.runtime.scheduler import get_scheduler, start_scheduler, stop_scheduler

    override_engine(db_url)

    sched = get_scheduler()
    if sched.running:
        await stop_scheduler()

    await start_scheduler()

    try:
        job_ids = {job.id for job in sched.get_jobs()}
        assert "github_crawl" in job_ids, "应有 github_crawl 任务"
        assert "reddit_crawl" in job_ids, "应有 reddit_crawl 任务"
        assert "render_projects" in job_ids, "应有 render_projects 任务"
        assert "render_communities" in job_ids, "应有 render_communities 任务"
        assert "watcher" in job_ids, "应有 watcher 巡检任务"
    finally:
        await stop_scheduler()


@pytest.mark.asyncio
async def test_watcher_detects_stale_data(db_url: str) -> None:
    """
    数据超期检测：写入一条 7 小时前的数据，watcher 应创建 data_stale Incident
    验收：Incident 存在，signal_type = data_stale
    """
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Item, Incident, SourceRun
    from sqlalchemy import select
    import hashlib

    override_engine(db_url)
    await init_db()

    # 配置：数据超期阈值设为 1 小时（7200s）
    # 写入一条 8 小时前的数据
    stale_time = datetime.now(timezone.utc) - timedelta(hours=8)

    async with get_session() as session:
        run = SourceRun(source="github", status="done", started_at=stale_time, finished_at=stale_time)
        session.add(run)
        await session.flush()

        url = "https://github.com/test/stale-repo"
        item = Item(
            source="github",
            external_id="test/stale-repo",
            url=url,
            url_hash=hashlib.sha256(url.encode()).hexdigest(),
            source_run_id=run.id,
            fetched_at=stale_time,
            item_at=stale_time,
        )
        session.add(item)

    # 运行巡检
    with patch("radar.runtime.watcher.settings") as mock_settings:
        mock_settings.data_stale_seconds = 3600  # 1小时阈值
        mock_settings.disk_low_gb = 0.001          # 磁盘检查不触发
        mock_settings.github_token = ""             # Token 检查跳过
        mock_settings.macos_notify = False
        mock_settings.output_dir = MagicMock()

        # 让磁盘检查不触发（空间充足）
        with patch("radar.runtime.watcher.shutil.disk_usage") as mock_disk:
            mock_disk.return_value = MagicMock(free=100 * 1e9)  # 100GB
            from radar.runtime.watcher import run_checks
            await run_checks()

    async with get_session() as session:
        incidents = (await session.execute(
            select(Incident).where(
                Incident.signal_type == "data_stale",
                Incident.affected_resource == "github",
            )
        )).scalars().all()

    assert len(incidents) >= 1, "应该有 data_stale Incident"
    assert incidents[0].severity in ("warning", "critical")
    assert "小时" in incidents[0].title


@pytest.mark.asyncio
async def test_watcher_dedup_incident(db_url: str) -> None:
    """
    去重检测：同类问题 24h 内只创建一次 Incident
    验收：两次巡检后只有 1 条 Incident
    """
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Item, Incident, SourceRun
    from sqlalchemy import select
    import hashlib

    override_engine(db_url)
    await init_db()

    # 写入超期数据
    stale_time = datetime.now(timezone.utc) - timedelta(hours=8)
    async with get_session() as session:
        run = SourceRun(source="github", status="done", started_at=stale_time, finished_at=stale_time)
        session.add(run)
        await session.flush()
        url = "https://github.com/test/stale2"
        item = Item(
            source="github",
            external_id="test/stale2",
            url=url,
            url_hash=hashlib.sha256(url.encode()).hexdigest(),
            source_run_id=run.id,
            fetched_at=stale_time,
        )
        session.add(item)

    with patch("radar.runtime.watcher.settings") as mock_settings, \
         patch("radar.runtime.watcher.shutil.disk_usage") as mock_disk:
        mock_settings.data_stale_seconds = 3600
        mock_settings.disk_low_gb = 0.001
        mock_settings.github_token = ""
        mock_settings.macos_notify = False
        mock_settings.output_dir = MagicMock()
        mock_disk.return_value = MagicMock(free=100 * 1e9)

        from radar.runtime.watcher import run_checks
        await run_checks()
        await run_checks()  # 第二次巡检

    async with get_session() as session:
        count = len((await session.execute(
            select(Incident).where(
                Incident.signal_type == "data_stale",
                Incident.affected_resource == "github",
            )
        )).scalars().all())

    assert count == 1, f"同类 Incident 24h 内应该只有 1 条，实际 {count} 条"


@pytest.mark.asyncio
async def test_crawl_failure_creates_incident(db_url: str) -> None:
    """
    连续抓取失败创建 Incident
    验收：达到阈值后有 source_failing Incident
    """
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import SourceRun, Incident
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    # 写入 5 条失败的 SourceRun（超过阈值）
    async with get_session() as session:
        for i in range(5):
            run = SourceRun(
                source="github",
                status="failed",
                error="连接超时",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
            session.add(run)

    with patch("radar.config.settings") as mock_settings:
        mock_settings.source_fail_threshold = 3  # 阈值设为 3
        mock_settings.macos_notify = False

        from radar.runtime.scheduler import _record_crawl_incident
        await _record_crawl_incident("github", "连接超时")

    async with get_session() as session:
        incidents = (await session.execute(
            select(Incident).where(
                Incident.signal_type == "source_failing",
                Incident.affected_resource == "github",
            )
        )).scalars().all()

    assert len(incidents) >= 1
    assert incidents[0].severity == "critical"
    assert "失败" in incidents[0].title
