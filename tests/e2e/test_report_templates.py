"""
E2E 测试：报告模板渲染（S6 Projects + S7 Communities）

验收条件（用户可观察结果）：
  1. 有评分数据后，渲染 projects 报告能生成 HTML 文件且结构正确
  2. 有 reddit 数据后，渲染 communities 报告能生成 HTML + JSON 数据文件
  3. 两种报告都有对应的 Report 数据库记录
  4. API /api/reports/latest/projects 和 /api/reports/latest/communities 返回 200
  5. 报告文件大小合理（> 1KB）
  6. 空数据时渲染不崩溃（返回空页面）
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


async def _seed_scored_github_item(session, domain: str = "coding") -> str:
    """创建有评分的 GitHub Item"""
    from radar.storage.models import Item, Score, Tag
    url = f"https://github.com/test/{domain}-project-{id(session)}"
    item = Item(
        source="github",
        external_id=f"test/{domain}-project",
        url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        title=f"test/{domain}-project",
        content=f"AI {domain} tool with excellent features",
        platform_data={"stars": 1200, "language": "Python", "topics": [domain, "ai"]},
    )
    session.add(item)
    await session.flush()

    session.add(Score(
        item_id=item.id,
        evaluator="qag",
        score=0.78,
        dimensions={"pain": 0.85, "market": 0.70, "feasibility": 0.75, "velocity": 0.60, "reason": "测试原因"},
        llm_profile="test",
    ))
    session.add(Tag(item_id=item.id, namespace="domain", value=domain))
    return item.id


async def _seed_reddit_item(session) -> str:
    """创建 Reddit Item"""
    from radar.storage.models import Item
    url = "https://reddit.com/r/artificial/comments/test123/"
    item = Item(
        source="reddit",
        external_id="t3_test123",
        url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        title="AI agent 工具推荐：2026 年最值得关注的项目",
        content="本文汇总了最新的 AI agent 工具...",
        platform_data={
            "subreddit": "artificial",
            "ups": 450,
            "num_comments": 67,
            "score": 450,
        },
    )
    session.add(item)
    await session.flush()
    return item.id


@pytest.mark.asyncio
async def test_render_projects_report_with_data(db_url: str, tmp_path: Path) -> None:
    """
    有评分数据时，projects 报告生成成功
    验收：HTML 文件存在，大小 > 1KB，包含领域名称
    """
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Report
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    async with get_session() as session:
        await _seed_scored_github_item(session, domain="coding")

    with patch("radar.outputs.projects.settings") as mock_s:
        mock_s.output_dir = tmp_path

        from radar.outputs.projects import render_projects_report
        result = await render_projects_report()

    assert result["status"] == "ok"
    assert result["items"] >= 1

    # 验证 HTML 文件
    html_files = list(tmp_path.glob("projects_*.html"))
    assert len(html_files) >= 1
    html_content = html_files[0].read_text(encoding="utf-8")
    assert len(html_content) > 1000, "HTML 文件应有实质内容"
    assert "编程开发 Agent" in html_content, "应包含 coding 领域名称"

    # 验证 Report 记录
    async with get_session() as session:
        report = (await session.execute(
            select(Report).where(Report.template == "projects")
        )).scalar_one_or_none()
    assert report is not None
    assert report.item_count >= 1


@pytest.mark.asyncio
async def test_render_communities_report_with_data(db_url: str, tmp_path: Path) -> None:
    """
    有 Reddit 数据时，communities 报告生成成功
    验收：HTML 文件存在，JSON 数据文件存在，Report 记录存在
    """
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Report
    from sqlalchemy import select

    override_engine(db_url)
    await init_db()

    async with get_session() as session:
        await _seed_reddit_item(session)

    with patch("radar.outputs.communities.settings") as mock_s:
        mock_s.output_dir = tmp_path

        from radar.outputs.communities import render_communities_report
        result = await render_communities_report()

    assert result["status"] == "ok"

    # 验证 HTML 文件
    html_files = list(tmp_path.glob("communities_*.html"))
    assert len(html_files) >= 1
    html_content = html_files[0].read_text(encoding="utf-8")
    assert "AI 社群地图" in html_content
    assert len(html_content) > 1000

    # 验证 JSON 数据文件
    json_files = list(tmp_path.glob("communities_data_*.json"))
    assert len(json_files) >= 1
    data = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) >= 1

    # 验证 Report 记录
    async with get_session() as session:
        report = (await session.execute(
            select(Report).where(Report.template == "communities")
        )).scalar_one_or_none()
    assert report is not None


@pytest.mark.asyncio
async def test_render_projects_no_data_no_crash(db_url: str, tmp_path: Path) -> None:
    """空数据时渲染不崩溃，生成空报告页"""
    from radar.storage.database import override_engine, init_db

    override_engine(db_url)
    await init_db()

    with patch("radar.outputs.projects.settings") as mock_s:
        mock_s.output_dir = tmp_path

        from radar.outputs.projects import render_projects_report
        result = await render_projects_report()

    assert result["status"] == "ok"
    assert result["items"] == 0
    html_files = list(tmp_path.glob("projects_*.html"))
    assert len(html_files) >= 1


@pytest.mark.asyncio
async def test_render_communities_no_data_no_crash(db_url: str, tmp_path: Path) -> None:
    """空数据时 communities 渲染不崩溃"""
    from radar.storage.database import override_engine, init_db

    override_engine(db_url)
    await init_db()

    with patch("radar.outputs.communities.settings") as mock_s:
        mock_s.output_dir = tmp_path

        from radar.outputs.communities import render_communities_report
        result = await render_communities_report()

    assert result["status"] == "ok"
    assert result["repos"] == 0


@pytest.mark.asyncio
async def test_api_returns_latest_report(client, db_url: str, app_with_db, tmp_path: Path) -> None:
    """
    渲染后，API /api/reports/latest/projects 返回 200
    验收：响应包含 template, file_path 字段
    """
    from radar.storage.database import override_engine, get_session

    override_engine(db_url)

    async with get_session() as session:
        await _seed_scored_github_item(session, domain="infra")

    with patch("radar.outputs.projects.settings") as mock_s:
        mock_s.output_dir = tmp_path

        from radar.outputs.projects import render_projects_report
        await render_projects_report()

    resp = await client.get("/api/reports/latest/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert data["template"] == "projects"
    assert "file_path" in data
