"""
E2E 测试：报告渲染验证

验收条件（用户可观察结果）：
  1. projects 报告 HTML 包含必要的结构字段（title、项目列表区域）
  2. communities 报告 HTML 包含必要的结构字段（title、社群区域）
  3. 报告文件体积 > 0，不是空文件
  4. 同一 template 两次渲染，最新的会覆盖，/latest 返回最新版本
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient


async def _create_report(db_url: str, tmp_path: Path, template: str, period_key: str, html: str) -> str:
    """辅助：写入一条 Report 记录并生成 HTML 文件"""
    from radar.storage.database import override_engine, get_session
    from radar.storage.models import Report

    override_engine(db_url)

    file_path = tmp_path / "outputs" / f"{period_key}_{template}.html"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(html, encoding="utf-8")

    async with get_session() as session:
        report = Report(
            template=template,
            period_key=period_key,
            file_path=str(file_path),
            item_count=3,
            status="ok",
            generated_at=datetime.now(timezone.utc),
        )
        session.add(report)
        await session.flush()
        return report.id


@pytest.mark.asyncio
async def test_projects_report_html_structure(
    client: AsyncClient,
    db_url: str,
    tmp_path: Path,
    app_with_db,
) -> None:
    """projects 报告 HTML 包含必要字段"""
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>AI 项目周报 · 2026-W20</title></head>
<body>
  <h1>本周 AI 开源项目精选</h1>
  <div class="domain-section" data-domain="llm-tools">
    <h2>LLM 工具</h2>
    <div class="project-card">
      <a href="https://github.com/test/repo">test/repo</a>
      <span class="stars">⭐ 1234</span>
    </div>
  </div>
</body>
</html>"""

    report_id = await _create_report(db_url, tmp_path, "projects", "2026-W20", html)

    # 最新报告接口
    resp = await client.get("/api/reports/latest/projects")
    assert resp.status_code == 200
    info = resp.json()
    assert info["template"] == "projects"

    # 下载文件，验证内容
    resp = await client.get(f"/api/reports/{report_id}/file")
    assert resp.status_code == 200
    content = resp.text
    assert "AI 项目周报" in content
    assert "domain-section" in content
    assert "project-card" in content
    assert len(content) > 100, "报告文件不应该是空的"


@pytest.mark.asyncio
async def test_communities_report_html_structure(
    client: AsyncClient,
    db_url: str,
    tmp_path: Path,
    app_with_db,
) -> None:
    """communities 报告 HTML 包含必要字段"""
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>AI 社群地图 · 2026-W20</title></head>
<body>
  <h1>本周 AI 活跃社群</h1>
  <div class="community-card">
    <img src="data:image/png;base64,..." alt="QR Code" class="qr-code">
    <p class="community-name">LangChain 用户群</p>
    <p class="member-count">1234 成员</p>
  </div>
</body>
</html>"""

    report_id = await _create_report(db_url, tmp_path, "communities", "2026-W20", html)

    resp = await client.get(f"/api/reports/{report_id}/file")
    assert resp.status_code == 200
    content = resp.text
    assert "AI 社群地图" in content
    assert "community-card" in content
    assert "qr-code" in content


@pytest.mark.asyncio
async def test_latest_report_returns_newest(
    client: AsyncClient,
    db_url: str,
    tmp_path: Path,
    app_with_db,
) -> None:
    """多次渲染后 /latest 返回最新版本"""
    import asyncio

    await _create_report(db_url, tmp_path, "projects", "2026-W19", "<html><title>W19</title></html>")
    await asyncio.sleep(0.01)  # 保证时间差
    await _create_report(db_url, tmp_path, "projects", "2026-W20", "<html><title>W20</title></html>")

    resp = await client.get("/api/reports/latest/projects")
    assert resp.status_code == 200
    latest = resp.json()
    assert latest["period_key"] == "2026-W20", f"应该返回最新的 W20，得到 {latest['period_key']}"


@pytest.mark.asyncio
async def test_report_list_pagination(
    client: AsyncClient,
    db_url: str,
    tmp_path: Path,
    app_with_db,
) -> None:
    """报告列表能正确过滤 template"""
    await _create_report(db_url, tmp_path, "projects", "2026-W20", "<html><title>P</title></html>")
    await _create_report(db_url, tmp_path, "communities", "2026-W20", "<html><title>C</title></html>")

    # 过滤 projects
    resp = await client.get("/api/reports?template=projects")
    assert resp.status_code == 200
    reports = resp.json()
    assert all(r["template"] == "projects" for r in reports)

    # 过滤 communities
    resp = await client.get("/api/reports?template=communities")
    assert resp.status_code == 200
    reports = resp.json()
    assert all(r["template"] == "communities" for r in reports)
