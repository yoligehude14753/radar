"""
E2E 测试：模拟真实用户操作路径

验收条件（用户可观察结果）：
  1. 用户打开 dashboard（health check ok）
  2. 用户看到数据源列表（含运行状态）
  3. 用户看到 Incident 通知并执行忽略操作
  4. 用户切换到报告页，看到两种模板的最新报告
  5. 用户下载报告 HTML，内容完整可用
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_user_onboarding_flow(client: AsyncClient) -> None:
    """
    用户首次打开 Radar 的完整路径：
    1. 确认服务在线
    2. 看到数据源列表（空的）
    3. 看到 Incident 列表（空的）
    4. 看到报告列表（空的）
    每一步都不报错，给出清晰的空状态
    """
    # Step 1: 服务在线
    resp = await client.get("/api/system/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Step 2: 数据源（空，但不报错）
    resp = await client.get("/api/sources")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # Step 3: Incident（空，但不报错）
    resp = await client.get("/api/incidents")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # Step 4: 报告列表（空）
    resp = await client.get("/api/reports")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # Step 5: 请求 latest 报告时得到有意义的 404
    resp = await client.get("/api/reports/latest/projects")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "没有可用的" in detail or "等待" in detail


@pytest.mark.asyncio
async def test_user_views_incident_and_dismisses(
    client: AsyncClient,
    db_url: str,
    app_with_db,
) -> None:
    """
    用户收到 Incident 通知，查看详情，执行忽略操作的完整路径
    """
    from radar.storage.database import override_engine, get_session
    from radar.storage.models import Incident, IncidentAction

    override_engine(db_url)

    # 系统检测到 token 即将过期，创建 Incident
    async with get_session() as session:
        inc = Incident(
            signal_type="token_expiring",
            severity="warning",
            affected_resource="github",
            title="GitHub Token 将在 3 天后过期",
            detail="请及时更新 Personal Access Token，否则抓取将中断",
            status="open",
        )
        session.add(inc)
        await session.flush()

        # 附带修复动作
        action = IncidentAction(
            incident_id=inc.id,
            action_key="refresh_token",
            label="重新配置 GitHub Token",
            endpoint=f"/api/incidents/{inc.id}/actions/refresh_token",
            order=0,
        )
        session.add(action)
        inc_id = inc.id

    # 用户查看 Incident 列表，看到告警
    resp = await client.get("/api/incidents")
    assert resp.status_code == 200
    incidents = resp.json()
    assert len(incidents) == 1
    inc_data = incidents[0]
    assert inc_data["signal_type"] == "token_expiring"
    assert inc_data["severity"] == "warning"
    assert len(inc_data["actions"]) == 1
    assert inc_data["actions"][0]["action_key"] == "refresh_token"

    # 用户选择"暂时忽略"
    resp = await client.post(f"/api/incidents/{inc_id}/dismiss")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # 确认 Incident 已从 open 列表消失
    resp = await client.get("/api/incidents?status=open")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_user_views_and_downloads_report(
    client: AsyncClient,
    db_url: str,
    tmp_path: Path,
    app_with_db,
) -> None:
    """
    用户访问报告页、查看两种报告、下载 HTML 的完整路径
    """
    from radar.storage.database import override_engine, get_session
    from radar.storage.models import Report

    override_engine(db_url)

    # 准备两个报告文件
    for template, title in [("projects", "AI 项目周报"), ("communities", "AI 社群地图")]:
        html = f"<html><head><title>{title}</title></head><body><h1>{title}</h1></body></html>"
        file_path = tmp_path / "outputs" / f"2026-W20_{template}.html"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(html, encoding="utf-8")

        async with get_session() as session:
            report = Report(
                template=template,
                period_key="2026-W20",
                file_path=str(file_path),
                item_count=10,
                status="ok",
                generated_at=datetime.now(timezone.utc),
            )
            session.add(report)

    # 用户查看报告列表
    resp = await client.get("/api/reports")
    assert resp.status_code == 200
    reports = resp.json()
    assert len(reports) == 2

    templates_seen = {r["template"] for r in reports}
    assert "projects" in templates_seen
    assert "communities" in templates_seen

    # 用户下载 projects 报告
    projects_report = next(r for r in reports if r["template"] == "projects")
    resp = await client.get(f"/api/reports/{projects_report['id']}/file")
    assert resp.status_code == 200
    assert "AI 项目周报" in resp.text

    # 用户下载 communities 报告
    communities_report = next(r for r in reports if r["template"] == "communities")
    resp = await client.get(f"/api/reports/{communities_report['id']}/file")
    assert resp.status_code == 200
    assert "AI 社群地图" in resp.text
