"""
E2E 测试：全链路验证
数据进来 → 存储 → 评分 → 报告渲染 → API 可读 → 文件可下载

验收条件（用户可观察结果）：
  1. 调用 /api/sources 能看到 github 源的条目数 ≥ 1
  2. 调用 /api/reports/latest/projects 能得到一个 period_key
  3. 访问 /api/reports/{id}/file 能拿到包含关键字段的 HTML
  4. 调用 /api/system/health 返回 status=ok
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient


# ── 辅助：直接写入 DB 模拟 GitHub 抓取结果 ────────────────────────────────


async def _seed_github_items(db_url: str, tmp_path: Path, count: int = 5) -> None:
    """
    模拟 GitHub 爬取 + 评分 + 报告渲染的结果写入 DB。
    代替真实网络请求，保证测试确定性。
    """
    import hashlib
    from radar.storage.database import override_engine, init_db, get_session
    from radar.storage.models import Item, Score, Tag, SourceRun, Report

    override_engine(db_url)
    await init_db()

    async with get_session() as session:
        run = SourceRun(
            source="github",
            status="done",
            items_in=count,
            items_new=count,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.flush()

        for i in range(count):
            url = f"https://github.com/test-org/repo-{i}"
            url_hash = hashlib.sha256(url.encode()).hexdigest()
            item = Item(
                source="github",
                external_id=f"test-org/repo-{i}",
                url=url,
                url_hash=url_hash,
                title=f"测试仓库 {i}",
                content=f"这是测试仓库 {i} 的 README 内容，包含 AI 相关关键词",
                platform_data={"stars": 100 + i * 10, "language": "Python", "topics": ["ai", "llm"]},
                source_run_id=run.id,
                item_at=datetime.now(timezone.utc),
            )
            session.add(item)
            await session.flush()

            score = Score(
                item_id=item.id,
                evaluator="qag",
                score=0.75 + i * 0.02,
                dimensions={"pain": 0.8, "market": 0.7, "feasibility": 0.75},
                llm_profile="ollama",
            )
            session.add(score)

            tag = Tag(item_id=item.id, namespace="domain", value="llm-tools")
            session.add(tag)

        # 模拟报告渲染结果
        report_file = tmp_path / "outputs" / f"2026-05-19_projects.html"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            "<html><head><title>Radar Projects</title></head>"
            "<body><h1>AI 项目周报</h1>"
            "<div class='project-list'>测试仓库 0, 测试仓库 1</div>"
            "</body></html>",
            encoding="utf-8",
        )

        report = Report(
            template="projects",
            period_key="2026-05-19",
            file_path=str(report_file),
            item_count=count,
            status="ok",
            llm_profile="ollama",
        )
        session.add(report)


# ── 测试用例 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    """健康检查返回 ok"""
    resp = await client.get("/api/system/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_sources_empty_initially(client: AsyncClient) -> None:
    """空 DB 下 sources 返回空列表"""
    resp = await client.get("/api/sources")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_full_pipeline_data_visible(
    client: AsyncClient,
    db_url: str,
    tmp_path: Path,
    app_with_db,
) -> None:
    """
    核心 E2E：数据进来后，所有下游接口都能读到
    验收：source 可见 → report 可查 → HTML 文件可下载 → 内容正确
    """
    # 模拟一轮完整的抓取 + 分析 + 渲染
    await _seed_github_items(db_url, tmp_path, count=5)

    # 1. 数据源列表能看到 github，且条目数 ≥ 1
    resp = await client.get("/api/sources")
    assert resp.status_code == 200
    sources = resp.json()
    github_src = next((s for s in sources if s["source"] == "github"), None)
    assert github_src is not None, "sources 列表中应该有 github"
    assert github_src["total_items"] >= 1
    assert github_src["last_run_status"] == "done"

    # 2. 报告列表能拿到 projects 报告
    resp = await client.get("/api/reports")
    assert resp.status_code == 200
    reports = resp.json()
    assert len(reports) >= 1
    project_report = next((r for r in reports if r["template"] == "projects"), None)
    assert project_report is not None, "应该有 projects 报告"
    assert project_report["status"] == "ok"
    assert project_report["item_count"] == 5

    # 3. 最新报告接口
    resp = await client.get("/api/reports/latest/projects")
    assert resp.status_code == 200
    latest = resp.json()
    assert latest["period_key"] == "2026-05-19"

    # 4. 下载报告 HTML 文件
    report_id = latest["id"]
    resp = await client.get(f"/api/reports/{report_id}/file")
    assert resp.status_code == 200
    html_content = resp.text
    assert "Radar Projects" in html_content, "HTML 文件应包含报告标题"
    assert "AI 项目周报" in html_content, "HTML 文件应包含关键内容"


@pytest.mark.asyncio
async def test_no_report_returns_404(client: AsyncClient) -> None:
    """没有报告时 latest 接口返回 404"""
    resp = await client.get("/api/reports/latest/projects")
    assert resp.status_code == 404
    assert "没有可用的" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_incidents_empty_initially(client: AsyncClient) -> None:
    """初始状态没有 Incident"""
    resp = await client.get("/api/incidents")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_incident_dismiss_flow(
    client: AsyncClient,
    db_url: str,
    app_with_db,
) -> None:
    """
    Incident 端到端：创建 → 查询 → 忽略 → 状态变化
    """
    from radar.storage.database import override_engine, get_session
    from radar.storage.models import Incident

    override_engine(db_url)

    # 直接写入一个 Incident
    async with get_session() as session:
        inc = Incident(
            signal_type="source_failing",
            severity="warning",
            affected_resource="github",
            title="GitHub 连续 3 次抓取失败",
            status="open",
        )
        session.add(inc)
        await session.flush()
        inc_id = inc.id

    # 查询 open incidents
    resp = await client.get("/api/incidents")
    assert resp.status_code == 200
    incidents = resp.json()
    assert len(incidents) == 1
    assert incidents[0]["signal_type"] == "source_failing"

    # 忽略该 Incident
    resp = await client.post(f"/api/incidents/{inc_id}/dismiss")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # 再次查询 open，应为空
    resp = await client.get("/api/incidents")
    assert resp.status_code == 200
    assert resp.json() == []

    # 查询 all，应该还在
    resp = await client.get("/api/incidents?status=dismissed")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
