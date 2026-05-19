"""Incident 修复动作注册表（S8 实现后补充具体动作）"""
from __future__ import annotations

from typing import Any, Callable, Awaitable

import structlog

from radar.storage.database import get_session
from radar.storage.models import Incident, IncidentAction

logger = structlog.get_logger(__name__)

# action_key → 异步处理函数
_registry: dict[str, Callable[..., Awaitable[Any]]] = {}


def register(action_key: str):
    """装饰器：注册一键修复动作"""
    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        _registry[action_key] = fn
        return fn
    return decorator


async def dispatch_action(incident_id: str, action_key: str) -> dict:
    from datetime import datetime, timezone

    handler = _registry.get(action_key)
    if not handler:
        return {"status": "no_handler", "action_key": action_key}

    async with get_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(Incident).where(Incident.id == incident_id)
        )
        incident = result.scalar_one_or_none()
        if not incident:
            return {"status": "incident_not_found"}

        # 更新 action 记录
        action_result = await session.execute(
            select(IncidentAction).where(
                IncidentAction.incident_id == incident_id,
                IncidentAction.action_key == action_key,
            )
        )
        action = action_result.scalar_one_or_none()

    try:
        output = await handler(incident_id=incident_id)
        if action:
            async with get_session() as session:
                action.executed_at = datetime.now(timezone.utc)
                action.last_error = None
                session.add(action)
        return {"status": "ok", "output": output}
    except Exception as exc:
        logger.exception("执行修复动作失败", incident_id=incident_id, action_key=action_key)
        if action:
            async with get_session() as session:
                action.last_error = str(exc)
                session.add(action)
        return {"status": "error", "error": str(exc)}


# ── 内置动作（S8 完成后扩充）──────────────────────────────────────────────


@register("retry_source")
async def retry_source(incident_id: str) -> str:
    """重试失败的数据源"""
    async with get_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(Incident).where(Incident.id == incident_id))
        inc = result.scalar_one_or_none()
        if not inc or not inc.affected_resource:
            return "找不到关联数据源"

    from radar.runtime.crawler import run_crawl
    results = await run_crawl(source=inc.affected_resource)
    return str(results)
