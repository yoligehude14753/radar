"""Incident 事件管理 API"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from radar.storage.database import get_session
from radar.storage.models import Incident, IncidentAction

router = APIRouter()


class ActionInfo(BaseModel):
    id: str
    action_key: str
    label: str
    endpoint: Optional[str]
    order: int
    executed_at: Optional[str]


class IncidentInfo(BaseModel):
    id: str
    signal_type: str
    severity: str
    affected_resource: Optional[str]
    title: str
    detail: Optional[str]
    status: str
    detected_at: str
    resolved_at: Optional[str]
    actions: list[ActionInfo]


def _to_info(inc: Incident) -> IncidentInfo:
    return IncidentInfo(
        id=inc.id,
        signal_type=inc.signal_type,
        severity=inc.severity,
        affected_resource=inc.affected_resource,
        title=inc.title,
        detail=inc.detail,
        status=inc.status,
        detected_at=inc.detected_at.isoformat(),
        resolved_at=inc.resolved_at.isoformat() if inc.resolved_at else None,
        actions=[
            ActionInfo(
                id=a.id,
                action_key=a.action_key,
                label=a.label,
                endpoint=a.endpoint,
                order=a.order,
                executed_at=a.executed_at.isoformat() if a.executed_at else None,
            )
            for a in inc.actions
        ],
    )


@router.get("", response_model=list[IncidentInfo], summary="Incident 列表（默认只看 open）")
async def list_incidents(
    status: Optional[str] = "open",
    limit: int = 50,
) -> list[IncidentInfo]:
    async with get_session() as session:
        q = (
            select(Incident)
            .options(selectinload(Incident.actions))
            .order_by(Incident.detected_at.desc())
            .limit(limit)
        )
        if status:
            q = q.where(Incident.status == status)
        result = await session.execute(q)
        return [_to_info(inc) for inc in result.scalars()]


@router.post("/{incident_id}/actions/{action_key}", summary="执行一键修复动作")
async def execute_action(incident_id: str, action_key: str) -> dict:
    """
    触发对应 action_key 的修复逻辑，结果异步执行。
    具体逻辑在 S8（监控引擎）中注册，这里只负责分发。
    """
    from radar.runtime.actions import dispatch_action  # S8 中实现

    result = await dispatch_action(incident_id=incident_id, action_key=action_key)
    return {"ok": True, "result": result}


@router.post("/{incident_id}/dismiss", summary="忽略 Incident")
async def dismiss_incident(incident_id: str) -> dict:
    from datetime import datetime, timezone

    async with get_session() as session:
        result = await session.execute(select(Incident).where(Incident.id == incident_id))
        inc = result.scalar_one_or_none()
        if not inc:
            raise HTTPException(404, "Incident 不存在")
        inc.status = "dismissed"
        inc.resolved_at = datetime.now(timezone.utc)
        return {"ok": True}
