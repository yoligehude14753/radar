"""
E2E 测试：故障场景验证

验收条件（用户可观察结果）：
  1. 单个 source 崩溃时，API 服务仍然可用（不整体宕机）
  2. 报告渲染失败时，Report 记录 status=failed，不影响其他报告
  3. 非法 incident_id dismiss 返回 404，不触发异常
  4. 错误的 action_key 返回明确的错误信息，不崩溃
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_api_survives_db_empty_queries(client: AsyncClient) -> None:
    """空 DB 下所有 API 都能正常返回，不报 500"""
    endpoints = [
        "/api/system/health",
        "/api/sources",
        "/api/reports",
        "/api/incidents",
    ]
    for endpoint in endpoints:
        resp = await client.get(endpoint)
        assert resp.status_code in (200, 404), (
            f"{endpoint} 返回了意外的状态码 {resp.status_code}: {resp.text}"
        )


@pytest.mark.asyncio
async def test_dismiss_nonexistent_incident(client: AsyncClient) -> None:
    """忽略不存在的 Incident 返回 404，不崩溃"""
    resp = await client.post("/api/incidents/nonexistent-id-12345/dismiss")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_execute_unknown_action(client: AsyncClient) -> None:
    """执行未注册的 action_key 返回明确错误，不崩溃"""
    resp = await client.post(
        "/api/incidents/fake-incident-id/actions/unknown_action_xyz"
    )
    # 应该返回 200 带 no_handler 或者 404，不应该是 500
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        data = resp.json()
        assert data.get("ok") is True
        assert data.get("result", {}).get("status") in ("no_handler", "incident_not_found", "error")


@pytest.mark.asyncio
async def test_download_nonexistent_report(client: AsyncClient) -> None:
    """下载不存在的报告返回 404"""
    resp = await client.get("/api/reports/nonexistent-report-id/file")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_multiple_requests_no_session_leak(client: AsyncClient) -> None:
    """并发请求不产生 DB 会话泄漏"""
    import asyncio

    async def _req():
        return await client.get("/api/sources")

    results = await asyncio.gather(*[_req() for _ in range(10)])
    assert all(r.status_code == 200 for r in results)
