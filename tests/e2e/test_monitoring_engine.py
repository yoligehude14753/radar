"""
E2E 测试：监控引擎（S8）

验收条件（用户可观察结果）：
  1. 零数据但有成功运行时，zero_items Incident 被创建
  2. LLM 不可达时，llm_unreachable Incident 被创建
  3. 调度器未运行时，scheduler_dead Incident 被创建
  4. 执行 retry_source 动作能触发实际抓取
  5. 执行 dismiss 动作能解决 Incident
  6. 执行未知动作返回明确错误，不崩溃
  7. 所有 Incident 可通过 /api/incidents 查询
  8. restart_scheduler 动作能正确重启调度器
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


@pytest.mark.asyncio
async def test_watcher_detects_zero_items(db_url: str) -> None:
    """
    有成功运行记录但 Item 为零时，创建 zero_items Incident
    """
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Incident, SourceRun
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    # 写入一条成功的 SourceRun（但没有 Item）
    async with get_session() as session:
        run = SourceRun(
            source="github",
            status="done",
            items_in=5,
            items_new=0,  # 没有新数据（假设已全部去重）
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
        session.add(run)

    with patch("radar.runtime.watcher.settings") as mock_settings, \
         patch("radar.runtime.watcher.shutil.disk_usage") as mock_disk:
        mock_settings.data_stale_seconds = 99999
        mock_settings.disk_low_gb = 0.001
        mock_settings.github_token = ""
        mock_settings.llm_base_url = ""
        mock_settings.macos_notify = False
        mock_settings.output_dir = MagicMock()
        mock_disk.return_value = MagicMock(free=100 * 1e9)

        from radar.runtime.watcher import run_checks
        await run_checks()

    async with get_session() as session:
        inc = (await session.execute(
            select(Incident).where(Incident.signal_type == "zero_items")
        )).scalar_one_or_none()

    assert inc is not None
    assert inc.severity == "critical"


@pytest.mark.asyncio
async def test_watcher_detects_llm_unreachable(db_url: str) -> None:
    """LLM 接口不可达时创建 llm_unreachable Incident"""
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Incident
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    with patch("radar.runtime.watcher.settings") as mock_settings, \
         patch("radar.runtime.watcher.shutil.disk_usage") as mock_disk, \
         patch("openai.AsyncOpenAI") as MockLLM:
        mock_settings.data_stale_seconds = 99999
        mock_settings.disk_low_gb = 0.001
        mock_settings.github_token = ""
        mock_settings.llm_base_url = "http://localhost:11434/v1"
        mock_settings.llm_api_key = "test"
        mock_settings.macos_notify = False
        mock_settings.output_dir = MagicMock()
        mock_disk.return_value = MagicMock(free=100 * 1e9)

        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(side_effect=Exception("Connection refused"))
        MockLLM.return_value = mock_client

        from radar.runtime.watcher import run_checks
        await run_checks()

    async with get_session() as session:
        inc = (await session.execute(
            select(Incident).where(Incident.signal_type == "llm_unreachable")
        )).scalar_one_or_none()

    assert inc is not None
    assert inc.severity == "warning"


@pytest.mark.asyncio
async def test_watcher_detects_scheduler_dead(db_url: str) -> None:
    """调度器未运行时创建 scheduler_dead Incident"""
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Incident
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    # 确保调度器停止
    from radar.runtime.scheduler import stop_scheduler
    await stop_scheduler()

    with patch("radar.runtime.watcher.settings") as mock_settings, \
         patch("radar.runtime.watcher.shutil.disk_usage") as mock_disk:
        mock_settings.data_stale_seconds = 99999
        mock_settings.disk_low_gb = 0.001
        mock_settings.github_token = ""
        mock_settings.llm_base_url = ""
        mock_settings.macos_notify = False
        mock_settings.output_dir = MagicMock()
        mock_disk.return_value = MagicMock(free=100 * 1e9)

        from radar.runtime.watcher import run_checks
        await run_checks()

    async with get_session() as session:
        inc = (await session.execute(
            select(Incident).where(Incident.signal_type == "scheduler_dead")
        )).scalar_one_or_none()

    assert inc is not None
    assert inc.severity == "critical"


@pytest.mark.asyncio
async def test_action_retry_source_github(db_url: str) -> None:
    """retry_source 动作能触发 GitHub 抓取"""
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Incident
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    # 创建一个 source_failing Incident
    async with get_session() as session:
        inc = Incident(
            signal_type="source_failing",
            severity="critical",
            affected_resource="github",
            title="GitHub 连续失败",
            status="open",
        )
        session.add(inc)
        await session.flush()
        incident_id = inc.id

    with patch("radar.sources.github.crawler.GitHubClient", autospec=True) as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_trending_repos = AsyncMock(return_value=[])

        from radar.runtime.actions import dispatch_action
        result = await dispatch_action(incident_id, "retry_source")

    assert result["status"] == "ok"
    assert "github" in result["message"].lower()

    # Incident 应变为 resolved
    async with get_session() as session:
        inc = (await session.execute(select(Incident).where(Incident.id == incident_id))).scalar_one()
    assert inc.status == "resolved"


@pytest.mark.asyncio
async def test_action_dismiss(db_url: str) -> None:
    """dismiss 动作能忽略 Incident"""
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Incident
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    async with get_session() as session:
        inc = Incident(
            signal_type="data_stale",
            severity="warning",
            affected_resource="github",
            title="数据超期",
            status="open",
        )
        session.add(inc)
        await session.flush()
        incident_id = inc.id

    from radar.runtime.actions import dispatch_action
    result = await dispatch_action(incident_id, "dismiss")

    assert result["status"] == "ok"

    async with get_session() as session:
        inc = (await session.execute(select(Incident).where(Incident.id == incident_id))).scalar_one()
    assert inc.status == "dismissed"


@pytest.mark.asyncio
async def test_action_unknown_returns_error(db_url: str) -> None:
    """未知动作返回 error，不崩溃"""
    from radar.runtime.actions import dispatch_action

    result = await dispatch_action("fake-incident-id", "nonexistent_action")
    assert result["status"] == "error"
    assert "nonexistent_action" in result["message"]


@pytest.mark.asyncio
async def test_incidents_visible_in_api(client, db_url: str, app_with_db) -> None:
    """创建的 Incident 可通过 /api/incidents 查询"""
    from radar.storage.database import override_engine, get_session
    from radar.storage.models import Incident

    override_engine(db_url)

    async with get_session() as session:
        session.add(Incident(
            signal_type="disk_low",
            severity="critical",
            affected_resource="disk",
            title="磁盘空间不足",
            status="open",
        ))

    resp = await client.get("/api/incidents?status=open")
    assert resp.status_code == 200
    incidents = resp.json()

    disk_inc = next((i for i in incidents if i["signal_type"] == "disk_low"), None)
    assert disk_inc is not None
    assert disk_inc["severity"] == "critical"
    assert disk_inc["title"] == "磁盘空间不足"
