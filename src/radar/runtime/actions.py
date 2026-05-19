"""Incident 修复动作注册表

支持在 CLI 和 Web UI 中触发的一键修复动作。
每个动作通过 `@register(action_key)` 注册，dispatch_action 按 key 路由。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable, Optional

import structlog

logger = structlog.get_logger(__name__)

_REGISTRY: dict[str, Callable[[str, dict], Awaitable[dict]]] = {}


def register(action_key: str):
    """装饰器：注册 Incident 修复动作"""
    def decorator(func: Callable[[str, dict], Awaitable[dict]]):
        _REGISTRY[action_key] = func
        return func
    return decorator


async def dispatch_action(incident_id: str, action_key: str, params: Optional[dict] = None) -> dict:
    """
    执行指定动作，返回 {status, message}。
    同时更新 Incident 状态为 resolving。
    """
    handler = _REGISTRY.get(action_key)
    if not handler:
        return {"status": "error", "message": f"未知动作: {action_key}"}

    # 更新 Incident 状态
    await _set_incident_resolving(incident_id)

    try:
        result = await handler(incident_id, params or {})
        logger.info("动作执行完成", action_key=action_key, result=result)
        return result
    except Exception as exc:
        logger.exception("动作执行失败", action_key=action_key, error=str(exc))
        return {"status": "error", "message": str(exc)}


def list_actions() -> list[str]:
    """列出已注册的所有动作"""
    return list(_REGISTRY.keys())


# ── 内置动作实现 ───────────────────────────────────────────────────────────

@register("retry_source")
async def retry_source(incident_id: str, params: dict) -> dict:
    """重试抓取（从 Incident 关联资源判断数据源）"""
    source = await _get_incident_resource(incident_id)
    if not source:
        return {"status": "error", "message": "无法确定数据源"}

    if source == "github":
        from radar.sources.github.crawler import crawl_github
        result = await crawl_github()
    elif source == "reddit":
        from radar.sources.reddit.crawler import crawl_reddit
        result = await crawl_reddit()
    else:
        return {"status": "error", "message": f"不支持的数据源: {source}"}

    if result.get("status") == "done":
        await _resolve_incident(incident_id)
        return {"status": "ok", "message": f"{source} 重试成功", "detail": result}
    else:
        return {"status": "error", "message": f"{source} 重试失败", "detail": result}


@register("refresh_token")
async def refresh_token(incident_id: str, params: dict) -> dict:
    """引导用户刷新 Token（返回向导 URL）"""
    source = await _get_incident_resource(incident_id)
    return {
        "status": "ok",
        "message": "请在 Web UI 中完成 Token 配置",
        "redirect": f"/tokens?source={source}&action=wizard",
    }


@register("render_report")
async def render_report_action(incident_id: str, params: dict) -> dict:
    """立即触发报告渲染"""
    template = params.get("template", "projects")
    from radar.outputs.renderer import render_report
    result = await render_report(template)
    if result.get("status") == "ok":
        await _resolve_incident(incident_id)
    return result


@register("restart_scheduler")
async def restart_scheduler(incident_id: str, params: dict) -> dict:
    """重启调度器"""
    from radar.runtime.scheduler import stop_scheduler, start_scheduler
    await stop_scheduler()
    await asyncio.sleep(1)
    await start_scheduler()
    await _resolve_incident(incident_id)
    return {"status": "ok", "message": "调度器已重启"}


@register("dismiss")
async def dismiss_action(incident_id: str, params: dict) -> dict:
    """手动忽略 Incident（用户确认已知晓，不需要修复）"""
    await _resolve_incident(incident_id, status="dismissed")
    return {"status": "ok", "message": "Incident 已忽略"}


# ── 辅助函数 ──────────────────────────────────────────────────────────────


async def _get_incident_resource(incident_id: str) -> Optional[str]:
    from radar.storage.database import get_session
    from radar.storage.models import Incident
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(select(Incident).where(Incident.id == incident_id))
        inc = result.scalar_one_or_none()
        return inc.affected_resource if inc else None


async def _set_incident_resolving(incident_id: str) -> None:
    from radar.storage.database import get_session
    from radar.storage.models import Incident
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(select(Incident).where(Incident.id == incident_id))
        inc = result.scalar_one_or_none()
        if inc and inc.status == "open":
            inc.status = "resolving"


async def _resolve_incident(incident_id: str, status: str = "resolved") -> None:
    from datetime import datetime, timezone
    from radar.storage.database import get_session
    from radar.storage.models import Incident
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(select(Incident).where(Incident.id == incident_id))
        inc = result.scalar_one_or_none()
        if inc:
            inc.status = status
            inc.resolved_at = datetime.now(timezone.utc)
